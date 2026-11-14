import unittest
from unittest.mock import AsyncMock, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bsk.service import BskService
from bsk.models import PageObservation


class TestServiceSync(unittest.IsolatedAsyncioTestCase):
    async def test_sync_session_calls_bsk_sync(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._with_tab_id = lambda args, tid: args + (["--tab-id", str(tid)] if tid else [])
        service._timeout = lambda builtin: builtin
        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(
            return_value=MagicMock(data={"vom": "@vom 1\n@view 800x600\nRootWebArea \"Test\"\n@e1 button \"OK\"", "tab_id": 1})
        )

        obs = await service.sync_session("s1", tab_id=1, wait_for="Test", timeout_ms=3000)
        self.assertIsInstance(obs, PageObservation)
        self.assertEqual(obs.title, "Test")
        self.assertEqual(len(obs.refs), 1)
        self.assertEqual(obs.refs[0].name, "OK")

        service.sessions.execute.assert_called_once()
        call_args = service.sessions.execute.call_args
        self.assertEqual(call_args[0][0], "s1")
        builder = call_args[0][1]
        argv = builder("s1")
        self.assertEqual(argv[0], "sync")
        self.assertIn("--wait-for", argv)
        self.assertIn("Test", argv)
        self.assertIn("--timeout-ms", argv)
        self.assertIn("3000", argv)
        self.assertIn("--tab-id", argv)
        self.assertIn("1", argv)

    async def test_open_session_calls_bsk_open(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._timeout = lambda builtin: builtin
        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(
            return_value=MagicMock(data={"vom": "@vom 1\n@view 800x600\nRootWebArea \"Open Test\"\n@e1 link \"Home\"", "tab_id": 1})
        )

        obs = await service.open_session("s1", "https://example.com", timeout_ms=5000)
        self.assertIsInstance(obs, PageObservation)
        self.assertEqual(obs.title, "Open Test")
        self.assertEqual(len(obs.refs), 1)

        service.sessions.execute.assert_called_once()
        builder = service.sessions.execute.call_args[0][1]
        argv = builder("s1")
        self.assertEqual(argv[0], "open")
        self.assertEqual(argv[1], "https://example.com")
        self.assertIn("--timeout-ms", argv)
        self.assertIn("5000", argv)

    async def test_interact_auto_sync_retries_css_selector(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._build_interact_args = MagicMock(return_value=(["click", "button.submit"], False))
        service._interact_timeout_builtin = MagicMock(return_value=30.0)
        service._timeout = lambda b: b
        service._logger = MagicMock()
        service._with_tab_id = lambda args, tid: args
        service._session_field = lambda k: "s1"
        service._payload_tab_id = lambda d: None
        service._interact_result = MagicMock(return_value={})
        service.sync_session = AsyncMock(return_value=PageObservation(text="ok"))

        from bsk.errors import BskError
        err = BskError("sync required", reason="cooperation_sync_required")
        success_res = MagicMock(data={"status": "ok"})
        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(side_effect=[err, success_res])

        res = await service.interact("s1", "click", target="button.submit")
        self.assertTrue(res["auto_synced"])
        self.assertEqual(service.sessions.execute.call_count, 2)

    async def test_interact_auto_sync_ref_target_raises_stale_ref_guidance(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._build_interact_args = MagicMock(return_value=(["fill", "@e15", "gtnh"], False))
        service._interact_timeout_builtin = MagicMock(return_value=30.0)
        service._timeout = lambda b: b
        service._logger = MagicMock()
        service._with_tab_id = lambda args, tid: args
        service.sync_session = AsyncMock(return_value=PageObservation(text="new page", title="Search"))
        service.render_page = MagicMock(return_value="标题：Search\n可交互元素：\n  @e56 textbox")

        from bsk.errors import BskError, BskUserError
        err = BskError("sync required", reason="cooperation_sync_required")
        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(side_effect=err)

        with self.assertRaises(BskUserError) as cm:
            await service.interact("s1", "fill", target="@e15", value="gtnh")

        self.assertEqual(cm.exception.code, "ref_stale_after_sync")
        self.assertIn("@e15", cm.exception.friendly)
        self.assertIn("@e56 textbox", cm.exception.friendly)
        # 绝不能发起第二次 execute 重试无效 ref！
        self.assertEqual(service.sessions.execute.call_count, 1)

    async def test_interact_unknown_effect_does_not_auto_sync(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._build_interact_args = MagicMock(return_value=(["fill", "@e1", "gtnh"], False))
        service._interact_timeout_builtin = MagicMock(return_value=30.0)
        service._timeout = lambda b: b
        service._logger = MagicMock()
        service._with_tab_id = lambda args, tid: args
        service._session_field = lambda k: "s1"
        service._payload_tab_id = lambda d: None
        service._interact_result = MagicMock(return_value={"value": "gtnh"})
        service.sync_session = AsyncMock()

        from bsk.errors import BskError
        err = BskError("unknown", reason="cooperation_sync_required", effect_state="unknown")
        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(side_effect=err)

        with self.assertRaises(BskError):
            await service.interact("s1", "fill", target="@e1", value="gtnh")

        service.sync_session.assert_not_called()
        self.assertEqual(service.sessions.execute.call_count, 1)

    async def test_interact_cooperation_sync_retry_fails_once(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._build_interact_args = MagicMock(return_value=(["fill", "input.kw", "gtnh"], False))
        service._interact_timeout_builtin = MagicMock(return_value=30.0)
        service._timeout = lambda b: b
        service._logger = MagicMock()
        service._with_tab_id = lambda args, tid: args
        service._session_field = lambda k: "s1"
        service._payload_tab_id = lambda d: None
        service._interact_result = MagicMock(return_value={"value": "gtnh"})
        service.sync_session = AsyncMock(return_value=PageObservation(text="ok"))

        from bsk.errors import BskError
        err1 = BskError("sync required 1", reason="cooperation_sync_required")
        err2 = BskError("sync required 2", reason="cooperation_sync_required")
        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(side_effect=[err1, err2])

        with self.assertRaises(BskError) as cm:
            await service.interact("s1", "fill", target="input.kw", value="gtnh")

        self.assertEqual(str(cm.exception), "sync required 2")
        service.sync_session.assert_called_once_with("s1", tab_id=None)
        self.assertEqual(service.sessions.execute.call_count, 2)

    async def test_interact_auto_sync_then_auto_scroll(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._build_interact_args = MagicMock(
            side_effect=lambda act, opts: (["scroll-to", "button.submit"], False) if act == "scroll-to" else (["click", "button.submit"], False)
        )
        service._interact_timeout_builtin = MagicMock(return_value=30.0)
        service._timeout = lambda b: b
        service._logger = MagicMock()
        service._with_tab_id = lambda args, tid: args
        service._session_field = lambda k: "s1"
        service._payload_tab_id = lambda d: None
        service._interact_result = MagicMock(return_value={})
        service.sync_session = AsyncMock(return_value=PageObservation(text="ok"))

        from bsk.errors import BskError
        err_sync = BskError("sync required", reason="cooperation_sync_required")
        err_vis = BskError("not visible", reason="element_not_visible")
        scroll_res = MagicMock(data={"status": "ok"})
        click_res = MagicMock(data={"status": "ok"})

        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(side_effect=[err_sync, err_vis, scroll_res, click_res])

        res = await service.interact("s1", "click", target="button.submit")
        self.assertTrue(res["auto_synced"])
        self.assertTrue(res["auto_scrolled"])
        service.sync_session.assert_called_once_with("s1", tab_id=None)
        self.assertEqual(service.sessions.execute.call_count, 4)

    async def test_observe_transparently_calls_sync_session(self) -> None:
        service = BskService.__new__(BskService)
        service.sync_session = AsyncMock(
            return_value=PageObservation(text="@vom 1\nRootWebArea \"Test\"\n@e1 link \"A\"", ref_count=1)
        )
        service._run_observe = AsyncMock()

        obs = await service.observe("s1", tab_id=2, max_tokens=1000)
        self.assertEqual(obs.ref_count, 1)
        service.sync_session.assert_called_once_with("s1", tab_id=2, max_tokens=1000)
        service._run_observe.assert_not_called()

    async def test_observe_sync_session_fallback_on_frame_unobservable(self) -> None:
        service = BskService.__new__(BskService)
        service._logger = MagicMock()
        from bsk.errors import BskError
        service.sync_session = AsyncMock(side_effect=BskError("blank page", reason="frame_unobservable"))
        service._run_observe = AsyncMock(
            return_value=PageObservation(text="@vom 1\nRootWebArea \"about:blank\"", ref_count=0)
        )

        obs = await service.observe("s1")
        self.assertEqual(obs.ref_count, 0)
        service.sync_session.assert_called_once_with("s1", tab_id=None, max_tokens=None)
        service._run_observe.assert_called_once_with("s1", cursor="", max_depth=None, max_tokens=None, tab_id=None)

    async def test_observe_with_max_depth_or_cursor_bypasses_sync(self) -> None:
        service = BskService.__new__(BskService)
        service.sync_session = AsyncMock()
        service._run_observe = AsyncMock(return_value=PageObservation(text="vom", ref_count=1))

        await service.observe("s1", max_depth=3)
        service.sync_session.assert_not_called()
        service._run_observe.assert_called_once_with("s1", cursor="", max_depth=3, max_tokens=None, tab_id=None)




if __name__ == "__main__":
    unittest.main()
