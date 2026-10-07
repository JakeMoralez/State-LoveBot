"""Read-only connection diagnostic. Run on the bot host using its Python environment.

Does not save cookies or print their values. Makes authenticated GET requests only.
"""
from __future__ import annotations

import asyncio
import json
import sys
from http.cookies import SimpleCookie
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp
from services import forum_api


async def main() -> int:
    try:
        library_version = version("arizona-forum-api-async")
    except PackageNotFoundError:
        library_version = "unknown"
    print(json.dumps({"library_version": library_version, "aiohttp_version": aiohttp.__version__}))
    service = forum_api.ForumService()
    original = service._cookie_dict()
    print(json.dumps({"configured_keys": sorted(original), "user_agent_configured": bool(service._user_agent())}))
    if not service.available or forum_api.ArizonaAPI is None:
        print("Cookies или библиотека не настроены")
        return 1

    async def headers_sent(session, context, params):
        jar = SimpleCookie()
        for header in params.headers.getall("Cookie", []):
            jar.load(header)
        # Comparing values in memory is safe; output contains booleans only.
        print(json.dumps({
            "stage": "request", "host": params.url.host, "path": params.url.path,
            "sent_cookie_keys": sorted(jar),
            "original_auth_cookies_unchanged": {
                key: key in jar and jar[key].value == value for key, value in original.items()
            },
        }))

    async def request_end(session, context, params):
        print(json.dumps({"stage": "response", "host": params.url.host,
                          "path": params.url.path, "http_status": params.response.status}))

    trace = aiohttp.TraceConfig()
    trace.on_request_headers_sent.append(headers_sent)
    trace.on_request_end.append(request_end)
    session_class = aiohttp.ClientSession

    def traced_session(*args, **kwargs):
        kwargs["trace_configs"] = [*kwargs.get("trace_configs", []), trace]
        return session_class(*args, **kwargs)

    candidate = None
    try:
        # Standalone process only: instrument sessions created inside the dependency.
        with patch.object(aiohttp, "ClientSession", traced_session):
            candidate = forum_api.ArizonaAPI(service._user_agent(), original)
            await asyncio.wait_for(candidate.connect(), timeout=40)
            member = await asyncio.wait_for(candidate.get_current_member(), timeout=40)
        print(json.dumps({"logged_in": member is not None}))
        return 0 if member is not None else 1
    except Exception as exc:
        cause = exc
        seen = set()
        status = None
        while cause is not None and id(cause) not in seen:
            seen.add(id(cause))
            if isinstance(cause, aiohttp.ClientResponseError):
                status = cause.status
                break
            cause = cause.__cause__ or cause.__context__
        print(json.dumps({"logged_in": False, "http_status": status,
                          "error_kind": "authentication" if status in (401, 403) else "connection"}))
        return 1
    finally:
        if candidate is not None:
            try:
                await candidate.close()
            except Exception:
                print(json.dumps({"cleanup_failed": True}))


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
