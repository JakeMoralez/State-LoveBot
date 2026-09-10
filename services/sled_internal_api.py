"""Internal HTTP API for State Admin integration (VK DM, form notifications)."""

from __future__ import annotations

import hmac
import logging
import os

from aiohttp import web
from vkbottle import API

from database.models.court_form import CourtForm
from database.models.user import AccessLevel, User, UserServerAccess
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker
from services.court_form_notify import CourtFormNotifier
from services.request_id import REQUEST_ID_HEADER, get_or_create_request_id, set_request_id

logger = logging.getLogger(__name__)

SLED_BOT_SECRET = os.getenv("SLED_BOT_SECRET", "")
SLED_INTERNAL_PORT = int(os.getenv("SLED_INTERNAL_PORT", "8081"))


def _check_secret(request: web.Request) -> bool:
    if not SLED_BOT_SECRET:
        return False
    provided = request.headers.get("X-Sled-Secret")
    if provided is None:
        return False
    a = provided.encode("utf-8")
    b = SLED_BOT_SECRET.encode("utf-8")
    if len(a) != len(b):
        hmac.compare_digest(b, b)
        return False
    return hmac.compare_digest(a, b)


@web.middleware
async def request_id_middleware(request: web.Request, handler):
    set_request_id(request.headers.get(REQUEST_ID_HEADER))
    rid = get_or_create_request_id()
    try:
        response = await handler(request)
    except Exception:
        logger.exception("internal API error request_id=%s path=%s", rid, request.path)
        raise
    if isinstance(response, web.StreamResponse):
        response.headers[REQUEST_ID_HEADER] = rid
    return response


async def handle_notify(request: web.Request) -> web.Response:
    """Отправка VK-уведомления от панели.

    Произвольный спам запрещён: нужен category из allowlist, лимит длины и rate-limit.
    """
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    from services.notify_guard import (
        ALLOWED_NOTIFY_CATEGORIES,
        check_notify_rate_limit,
        normalize_notify_message,
    )

    vk_id = data.get("vk_id")
    message = data.get("message")
    category = str(data.get("category") or "").strip().lower()
    if not vk_id or message is None:
        return web.json_response({"error": "vk_id and message required"}, status=400)
    if category not in ALLOWED_NOTIFY_CATEGORIES:
        return web.json_response(
            {
                "error": "invalid category",
                "allowed": sorted(ALLOWED_NOTIFY_CATEGORIES),
            },
            status=400,
        )
    try:
        peer = int(vk_id)
    except (TypeError, ValueError):
        return web.json_response({"error": "invalid vk_id"}, status=400)
    if peer <= 0:
        return web.json_response({"error": "invalid vk_id"}, status=400)

    text, err = normalize_notify_message(message)
    if err:
        return web.json_response({"error": err}, status=400)

    ok_rate, rate_err = check_notify_rate_limit(peer)
    if not ok_rate:
        return web.json_response({"error": rate_err}, status=429)

    api: API = request.app["vk_api"]
    rid = get_or_create_request_id()
    try:
        await api.messages.send(
            peer_id=peer,
            message=text,
            random_id=0,
        )
        logger.info(
            "sled notify ok vk_id=%s category=%s request_id=%s len=%s",
            peer,
            category,
            rid,
            len(text),
        )
        return web.json_response({"ok": True, "request_id": rid})
    except Exception as exc:
        logger.warning(
            "sled notify failed vk_id=%s category=%s request_id=%s: %s",
            peer,
            category,
            rid,
            exc,
        )
        return web.json_response({"error": str(exc)}, status=500)


async def handle_staff_ca(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    rows = (
        await UserServerAccess.filter(has_ca_access=True)
        .prefetch_related("user")
        .all()
    )
    staff = []
    for access in rows:
        user: User = access.user
        staff.append(
            {
                "vk_id": user.vk_id,
                "server_id": access.server_id,
                "nickname": access.nickname or user.nickname,
                "access_level": access.access_level,
                "has_ca_access": access.has_ca_access,
                "granted_by": access.granted_by,
                "granted_at": access.granted_at.isoformat() if access.granted_at else None,
            }
        )
    return web.json_response({"staff": staff})


async def handle_staff_full(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        server_id = int(request.rel_url.query.get("server_id", "0"))
    except ValueError:
        return web.json_response({"error": "invalid server_id"}, status=400)
    if not server_id:
        from config.settings import DEFAULT_SERVER_ID

        server_id = DEFAULT_SERVER_ID

    rows = await UserRepository.list_staff(server_id)
    staff = []
    for user, level, access in rows:
        if await UserRepository.is_developer(user.vk_id):
            level = max(level, AccessLevel.DEVELOPER)
        badges: list[str] = []
        if access and access.has_ca_access:
            badges.append("ЦА")
        if access and access.is_judge:
            badges.append("⚖")
        if access and access.is_congress_speaker:
            badges.append("🎙")
        if access and access.is_congress_vice:
            badges.append("🎖")
        if access and access.is_attorney:
            badges.append("📘")
        if access and access.is_leader:
            badges.append("🛡")
        if user.is_admin:
            badges.append("👑")
        staff.append(
            {
                "vk_id": user.vk_id,
                "nickname": (access.nickname if access and access.nickname else None)
                or user.nickname
                or user.username,
                "access_level": level,
                "access_level_name": AccessChecker.level_name(level),
                "badges": badges,
                "has_ca_access": bool(access and access.has_ca_access),
                "granted_by": access.granted_by if access else None,
                "granted_at": access.granted_at.isoformat() if access and access.granted_at else None,
            }
        )
    return web.json_response({"server_id": server_id, "staff": staff})


async def handle_form_decision(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    server_id = data.get("server_id")
    form_id = data.get("form_id")
    reviewer_id = data.get("reviewer_id")
    accepted = data.get("accepted", False)
    reason = data.get("reason")

    if not all([server_id, form_id, reviewer_id is not None]):
        return web.json_response({"error": "missing fields"}, status=400)

    form = await CourtForm.get_or_none(id=form_id, server_id=server_id)
    if not form:
        return web.json_response({"error": "form not found"}, status=404)

    api: API = request.app["vk_api"]
    notifier = CourtFormNotifier(api)
    await notifier.notify_decision(
        server_id=int(server_id),
        form=form,
        reviewer_id=int(reviewer_id),
        accepted=bool(accepted),
        reason=reason,
    )
    return web.json_response({"ok": True})


async def handle_forum_thread_info(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        thread_id = int(request.rel_url.query.get("thread_id", "0"))
    except ValueError:
        return web.json_response({"error": "invalid thread_id"}, status=400)
    if thread_id <= 0:
        return web.json_response({"error": "thread_id required"}, status=400)

    try:
        server_id = int(request.rel_url.query.get("server_id", "0"))
    except ValueError:
        return web.json_response({"error": "invalid server_id"}, status=400)
    if server_id <= 0:
        return web.json_response({"error": "server_id required"}, status=400)

    from services.forum_api import ForumService
    from services.judge_forum_sync import validate_judge_list_thread

    forum = ForumService()
    try:
        if forum.available and not forum._api:
            await forum.connect()
    except Exception as exc:
        return web.json_response({"error": f"forum unavailable: {exc}"}, status=503)

    info = await forum.get_thread_info(thread_id)
    if not info:
        return web.json_response({"error": "thread not found"}, status=404)

    ok, err = await validate_judge_list_thread(server_id, thread_id, forum)
    return web.json_response(
        {
            "thread_id": thread_id,
            "server_id": server_id,
            "category_id": info.get("category_id") or info.get("node_id"),
            "forum_name": info.get("forum_name"),
            "title": info.get("title"),
            "valid": ok,
            "error": err or None,
        }
    )


async def handle_health(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    return web.json_response({"ok": True})


async def handle_chats_list(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        server_id = int(request.rel_url.query.get("server_id", "0"))
    except ValueError:
        return web.json_response({"error": "invalid server_id"}, status=400)
    if server_id <= 0:
        from config.settings import DEFAULT_SERVER_ID

        server_id = DEFAULT_SERVER_ID
    from services.internal_chats import list_chats_payload

    api: API = request.app["vk_api"]
    try:
        payload = await list_chats_payload(api, server_id)
    except Exception as exc:
        logger.exception("internal chats list failed")
        return web.json_response({"error": str(exc)}, status=500)
    return web.json_response(payload)


async def handle_chat_patch(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        peer_id = int(request.match_info["peer_id"])
    except (KeyError, ValueError):
        return web.json_response({"error": "invalid peer_id"}, status=400)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(data, dict):
        return web.json_response({"error": "invalid json"}, status=400)

    from config.settings import DEFAULT_SERVER_ID
    from services.internal_chats import patch_chat

    try:
        server_id = int(data.get("server_id") or DEFAULT_SERVER_ID)
        updated_by = int(data.get("updated_by") or 0)
    except (TypeError, ValueError):
        return web.json_response({"error": "invalid server_id or updated_by"}, status=400)
    if not updated_by:
        return web.json_response({"error": "updated_by required"}, status=400)

    api: API = request.app["vk_api"]
    try:
        row = await patch_chat(
            api,
            peer_id,
            server_id=server_id,
            updated_by=updated_by,
            body=data,
        )
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        logger.exception("internal chat patch failed peer=%s", peer_id)
        return web.json_response({"error": str(exc)}, status=500)
    return web.json_response(row)


async def handle_chat_members(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        peer_id = int(request.rel_url.query.get("peer_id", "0"))
    except ValueError:
        return web.json_response({"error": "invalid peer_id"}, status=400)
    if peer_id < 2_000_000_000:
        return web.json_response({"error": "peer_id required"}, status=400)

    from config.settings import VK_USER_TOKEN
    from services.messaging import MessagingService

    api: API = request.app["vk_api"]
    user_api = API(token=VK_USER_TOKEN) if VK_USER_TOKEN else None
    messaging = MessagingService(api, user_api=user_api)
    member_ids = await messaging.get_member_ids(peer_id)
    return web.json_response({"peer_id": peer_id, "member_ids": member_ids, "count": len(member_ids)})


async def handle_forum_status(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    forum = request.app.get("forum_service")
    if forum is None:
        from services.forum_api import ForumService

        forum = ForumService()
    try:
        report = await forum.check_health()
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)
    cookies = forum.cookies_status() if hasattr(forum, "cookies_status") else {}
    return web.json_response(
        {
            "configured": report.configured,
            "connected": report.connected,
            "logged_in": report.logged_in,
            "username": report.username,
            "error": report.error,
            "ok": report.ok,
            "cookies": cookies,
        }
    )


async def handle_forum_reconnect(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    forum = request.app.get("forum_service")
    if forum is None:
        return web.json_response({"error": "forum service unavailable"}, status=503)
    try:
        report = await forum.reconnect()
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)
    cookies = forum.cookies_status() if hasattr(forum, "cookies_status") else {}
    return web.json_response(
        {
            "ok": report.ok,
            "configured": report.configured,
            "connected": report.connected,
            "logged_in": report.logged_in,
            "username": report.username,
            "error": report.error,
            "cookies": cookies,
        }
    )


async def handle_forum_cookies(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    forum = request.app.get("forum_service")
    if forum is None:
        return web.json_response({"error": "forum service unavailable"}, status=503)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)
    if not isinstance(data, dict):
        return web.json_response({"error": "invalid json"}, status=400)
    cookies = {
        key: str(data[key]).strip()
        for key in ("xf_user", "xf_session", "xf_tfa_trust")
        if data.get(key)
    }
    if not cookies.get("xf_user") or not cookies.get("xf_session"):
        return web.json_response({"error": "Нужны xf_user и xf_session"}, status=400)
    try:
        report = await forum.apply_cookies(cookies)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)
    cookies_meta = forum.cookies_status() if hasattr(forum, "cookies_status") else {}
    return web.json_response(
        {
            "ok": report.ok,
            "configured": report.configured,
            "connected": report.connected,
            "logged_in": report.logged_in,
            "username": report.username,
            "error": report.error,
            "cookies": cookies_meta,
        }
    )


async def handle_forum_sync_judges(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    forum = request.app.get("forum_service")
    if forum is None:
        return web.json_response({"error": "forum service unavailable"}, status=503)
    try:
        server_id = int(request.rel_url.query.get("server_id", "0") or "0")
    except ValueError:
        return web.json_response({"error": "invalid server_id"}, status=400)
    if not server_id:
        from config.settings import DEFAULT_SERVER_ID

        server_id = DEFAULT_SERVER_ID
    from services.judge_forum_sync import sync_judge_list

    ok, msg = await sync_judge_list(server_id, forum)
    return web.json_response({"ok": ok, "message": msg}, status=200 if ok else 400)


async def handle_command_access_get(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        server_id = int(request.rel_url.query.get("server_id", "0") or "0")
    except ValueError:
        return web.json_response({"error": "invalid server_id"}, status=400)
    if not server_id:
        from config.settings import DEFAULT_SERVER_ID

        server_id = DEFAULT_SERVER_ID
    from services.command_access import list_command_access

    return web.json_response(await list_command_access(server_id))


async def handle_command_access_put(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)
    try:
        server_id = int(data.get("server_id") or request.rel_url.query.get("server_id") or "0")
    except (TypeError, ValueError):
        return web.json_response({"error": "invalid server_id"}, status=400)
    if not server_id:
        from config.settings import DEFAULT_SERVER_ID

        server_id = DEFAULT_SERVER_ID
    updates = data.get("updates")
    if not isinstance(updates, list):
        return web.json_response({"error": "updates must be a list"}, status=400)
    from services.command_access import save_command_access

    try:
        result = await save_command_access(server_id, updates)
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)
    except Exception as exc:
        return web.json_response({"error": str(exc)}, status=500)
    return web.json_response(result)


async def start_sled_internal_server(
    api: API,
    forum_service: object | None = None,
) -> web.AppRunner | None:
    if not SLED_BOT_SECRET:
        logger.info("SLED_BOT_SECRET not set — internal API disabled")
        return None

    app = web.Application(middlewares=[request_id_middleware])
    app["vk_api"] = api
    if forum_service is not None:
        app["forum_service"] = forum_service
    app.router.add_get("/internal/health", handle_health)
    app.router.add_get("/internal/staff-ca", handle_staff_ca)
    app.router.add_get("/internal/staff-full", handle_staff_full)
    app.router.add_get("/internal/chats", handle_chats_list)
    app.router.add_patch("/internal/chats/{peer_id}", handle_chat_patch)
    app.router.add_get("/internal/chat-members", handle_chat_members)
    app.router.add_get("/internal/forum/thread-info", handle_forum_thread_info)
    app.router.add_get("/internal/forum/status", handle_forum_status)
    app.router.add_post("/internal/forum/reconnect", handle_forum_reconnect)
    app.router.add_post("/internal/forum/cookies", handle_forum_cookies)
    app.router.add_post("/internal/forum/sync-judges", handle_forum_sync_judges)
    app.router.add_get("/internal/command-access", handle_command_access_get)
    app.router.add_put("/internal/command-access", handle_command_access_put)
    app.router.add_post("/internal/notify", handle_notify)
    app.router.add_post("/internal/form-decision", handle_form_decision)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", SLED_INTERNAL_PORT)
    await site.start()
    logger.info("Sled internal API listening on 127.0.0.1:%s", SLED_INTERNAL_PORT)
    return runner


async def stop_sled_internal_server(runner: web.AppRunner | None) -> None:
    if runner:
        await runner.cleanup()
