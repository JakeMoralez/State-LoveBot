"""Internal HTTP API for State Admin integration (VK DM, form notifications)."""

from __future__ import annotations

import logging
import os

from aiohttp import web
from vkbottle import API

from database.models.court_form import CourtForm
from database.models.user import User, UserServerAccess
from database.repository.user_repo import UserRepository
from middlewares.access import AccessChecker
from services.court_form_notify import CourtFormNotifier

logger = logging.getLogger(__name__)

SLED_BOT_SECRET = os.getenv("SLED_BOT_SECRET", "")
SLED_INTERNAL_PORT = int(os.getenv("SLED_INTERNAL_PORT", "8081"))


def _check_secret(request: web.Request) -> bool:
    if not SLED_BOT_SECRET:
        return False
    return request.headers.get("X-Sled-Secret") == SLED_BOT_SECRET


async def handle_notify(request: web.Request) -> web.Response:
    if not _check_secret(request):
        return web.json_response({"error": "unauthorized"}, status=401)
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    vk_id = data.get("vk_id")
    message = data.get("message")
    if not vk_id or not message:
        return web.json_response({"error": "vk_id and message required"}, status=400)

    api: API = request.app["vk_api"]
    try:
        await api.messages.send(
            peer_id=int(vk_id),
            message=str(message),
            random_id=0,
        )
        return web.json_response({"ok": True})
    except Exception as exc:
        logger.warning("sled notify failed vk_id=%s: %s", vk_id, exc)
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
            level = max(level, 10)
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


async def start_sled_internal_server(api: API) -> web.AppRunner | None:
    if not SLED_BOT_SECRET:
        logger.info("SLED_BOT_SECRET not set — internal API disabled")
        return None

    app = web.Application()
    app["vk_api"] = api
    app.router.add_get("/internal/staff-ca", handle_staff_ca)
    app.router.add_get("/internal/staff-full", handle_staff_full)
    app.router.add_get("/internal/chat-members", handle_chat_members)
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
