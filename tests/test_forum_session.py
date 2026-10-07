"""Offline regression tests: python -m unittest discover -s tests -p test_forum_session.py."""
import asyncio
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import aiohttp
from aiohttp import ClientResponseError, CookieJar, web
from yarl import URL

from services import forum_api as forum
from services import forum_cookies_store as store


OLD = {"xf_user": "old-user", "xf_session": "old-session", "xf_tfa_trust": "old-trust"}
NEW = {"xf_user": "new-user", "xf_session": "new-session"}


class FakeAPI:
    instances = []
    failure = None
    member = SimpleNamespace(username="Test account")
    started = None
    proceed = None

    def __init__(self, agent, cookies):
        self.agent = agent
        self.cookies = dict(cookies)
        self.closed = False
        jar = CookieJar()
        jar.update_cookies(cookies, response_url=URL("https://forum.arizona-rp.com/"))
        self._session = SimpleNamespace(closed=False, cookie_jar=jar)
        self.instances.append(self)

    async def connect(self):
        if self.started is not None:
            self.started.set()
            await self.proceed.wait()
        if self.failure is not None:
            raise self.failure
        self._session.cookie_jar.update_cookies(
            {"xf_session": "rotated-session"}, response_url=URL("https://forum.arizona-rp.com/")
        )

    async def get_current_member(self):
        return self.member

    async def close(self):
        self.closed = True
        self._session.closed = True


class ForumSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "cookies.json"
        self.enterContext(patch.object(store, "_STORE_PATH", self.path))
        self.enterContext(patch.object(forum.ForumService, "_read_cookies_from_env", return_value=OLD))
        self.enterContext(patch.object(forum, "ArizonaAPI", FakeAPI))
        self.enterContext(patch.object(forum, "_HAS_ARIZONA", True))
        FakeAPI.instances = []
        FakeAPI.failure = None
        FakeAPI.member = SimpleNamespace(username="Test account")
        FakeAPI.started = None
        FakeAPI.proceed = None
        store.save_persisted_cookies(OLD, user_agent="old-agent")
        self.service = forum.ForumService()
        self.previous = FakeAPI("old-agent", OLD)
        self.service._api = self.previous
        self.service._backend = "arizona"
        self.original_file = self.path.read_bytes()

    async def test_success_saves_rotated_cookies_and_switches_session(self):
        report = await self.service.apply_cookies(NEW, "new-agent")
        self.assertTrue(report.ok)
        self.assertTrue(report.applied)
        self.assertEqual(report.username, "Test account")
        self.assertTrue(self.previous.closed)
        self.assertEqual(self.service.api.cookies, NEW)
        self.assertEqual(store.load_persisted_cookies(), {**NEW, "xf_session": "rotated-session"})
        self.assertEqual(store.load_persisted_user_agent(), "new-agent")
        self.assertNotIn("xf_tfa_trust", forum.ForumService()._cookie_dict())
        self.assertTrue((await self.service.reconnect()).ok)
        self.assertEqual(self.service.api.cookies, {**NEW, "xf_session": "rotated-session"})
        await self.service.close()
        self.assertEqual(store.load_persisted_cookies()["xf_session"], "rotated-session")

    async def test_wrapped_401_preserves_previous_configuration(self):
        cause = ClientResponseError(None, (), status=401, message="sensitive-value")
        wrapped = RuntimeError("sensitive-value")
        wrapped.__cause__ = cause
        FakeAPI.failure = wrapped
        report = await self.service.apply_cookies(NEW, "new-agent")
        self.assertFalse(report.ok)
        self.assertFalse(report.applied)
        self.assertEqual(report.error_kind, "authentication")
        self.assertIn("401", report.error)
        self.assertNotIn("sensitive-value", report.error)
        self.assertIs(self.service.api, self.previous)
        self.assertFalse(self.previous.closed)
        self.assertTrue(FakeAPI.instances[-1].closed)
        self.assertEqual(self.path.read_bytes(), self.original_file)

    async def test_failed_account_check_does_not_save(self):
        FakeAPI.member = None
        report = await self.service.apply_cookies(NEW, "new-agent")
        self.assertFalse(report.applied)
        self.assertEqual(self.path.read_bytes(), self.original_file)
        self.assertTrue(FakeAPI.instances[-1].closed)

    async def test_storage_failure_preserves_file_and_active_session(self):
        with patch.object(store.os, "replace", side_effect=PermissionError("denied")):
            report = await self.service.apply_cookies(NEW, "new-agent")
        self.assertFalse(report.ok)
        self.assertEqual(report.error_kind, "storage")
        self.assertFalse(report.applied)
        self.assertEqual(self.path.read_bytes(), self.original_file)
        self.assertIs(self.service.api, self.previous)
        self.assertTrue(FakeAPI.instances[-1].closed)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    async def test_missing_required_cookie_cannot_fall_back_to_env(self):
        count = len(FakeAPI.instances)
        report = await self.service.apply_cookies({"xf_user": "new"}, "new-agent")
        self.assertEqual(report.error_kind, "validation")
        self.assertEqual(len(FakeAPI.instances), count)
        self.assertEqual(self.path.read_bytes(), self.original_file)

    async def test_connection_failure_does_not_expose_exception(self):
        FakeAPI.failure = TimeoutError("secret-cookie-value")
        report = await self.service.apply_cookies(NEW, "new-agent")
        self.assertEqual(report.error_kind, "connection")
        self.assertNotIn("secret-cookie-value", report.error)
        self.assertEqual(self.path.read_bytes(), self.original_file)

    async def test_invalid_agent_does_not_touch_current_session(self):
        report = await self.service.apply_cookies(NEW, "agent\r\nCookie: value")
        self.assertEqual(report.error_kind, "validation")
        self.assertIs(self.service.api, self.previous)

    async def test_watchdog_reconnect_waits_for_replacement(self):
        FakeAPI.started = asyncio.Event()
        FakeAPI.proceed = asyncio.Event()
        replace = asyncio.create_task(self.service.apply_cookies(NEW, "new-agent"))
        await asyncio.wait_for(FakeAPI.started.wait(), 2)
        reconnect = asyncio.create_task(self.service.reconnect())
        health = asyncio.create_task(self.service.check_health())
        await asyncio.sleep(0)
        self.assertEqual(len(FakeAPI.instances), 2)
        FakeAPI.proceed.set()
        reports = await asyncio.wait_for(asyncio.gather(replace, reconnect, health), 2)
        self.assertTrue(all(report.ok for report in reports))
        self.assertEqual(self.service.api.cookies["xf_user"], NEW["xf_user"])
        self.assertEqual(store.load_persisted_cookies()["xf_user"], NEW["xf_user"])

    async def test_cancelled_trial_is_closed_and_not_saved(self):
        FakeAPI.started = asyncio.Event()
        FakeAPI.proceed = asyncio.Event()
        task = asyncio.create_task(self.service.apply_cookies(NEW, "new-agent"))
        await asyncio.wait_for(FakeAPI.started.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(FakeAPI.instances[-1].closed)
        self.assertIs(self.service.api, self.previous)
        self.assertEqual(self.path.read_bytes(), self.original_file)
        self.assertFalse(self.service._session_lock.locked())

    async def test_cookie_rotation_uses_forum_domain(self):
        jar = self.previous._session.cookie_jar
        jar.update_cookies({"xf_session": "unrelated"}, response_url=URL("https://other.example/"))
        self.assertEqual(self.service._session_cookies(self.previous, OLD)["xf_session"], "old-session")

    async def test_diagnostic_traces_cookie_rotation_without_values(self):
        script = Path(forum.__file__).resolve().parent.parent / "scripts/diagnose_forum_session.py"
        spec = importlib.util.spec_from_file_location("forum_diagnostic", script)
        diagnostic = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(diagnostic)

        async def root_response(request):
            response = web.Response(text="challenge completed")
            response.set_cookie("xf_session", "private-rotated-value")
            return response

        async def account_response(request):
            return web.Response(text="account")

        app = web.Application()
        app.router.add_get("/", root_response)
        app.router.add_get("/account/", account_response)
        runner = web.AppRunner(app)
        await runner.setup()
        self.addAsyncCleanup(runner.cleanup)
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}"

        class DiagnosticAPI:
            def __init__(self, agent, cookies):
                self.cookies = cookies

            async def connect(self):
                self.session = aiohttp.ClientSession(cookies=self.cookies, cookie_jar=CookieJar(unsafe=True))
                async with self.session.get(url + "/") as response:
                    response.raise_for_status()

            async def get_current_member(self):
                async with self.session.get(url + "/account/") as response:
                    response.raise_for_status()
                return SimpleNamespace(username="test")

            async def close(self):
                await self.session.close()

        output = io.StringIO()
        with patch.object(forum, "ArizonaAPI", DiagnosticAPI), contextlib.redirect_stdout(output):
            result = await diagnostic.main()
        self.assertEqual(result, 0)
        text = output.getvalue()
        for secret in (*OLD.values(), "private-rotated-value", "old-agent"):
            self.assertNotIn(secret, text)
        records = [json.loads(line) for line in text.splitlines()]
        account = next(row for row in records if row.get("stage") == "request" and row["path"] == "/account/")
        self.assertTrue(account["original_auth_cookies_unchanged"]["xf_user"])
        self.assertFalse(account["original_auth_cookies_unchanged"]["xf_session"])


if __name__ == "__main__":
    unittest.main()

