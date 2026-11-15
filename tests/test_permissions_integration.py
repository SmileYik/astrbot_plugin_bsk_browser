import unittest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))
if str(_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tests"))

from astrbot_test_doubles import ensure_astrbot_modules, make_context, FakeEvent

ensure_astrbot_modules()

from astrbot_plugin_bsk_browser.main import BskBrowserPlugin


class TestPermissionsIntegration(unittest.IsolatedAsyncioTestCase):
    def make_plugin(self, config_dict=None):
        cfg = {
            "enabled": True,
            "admin_only": False,
            "site_whitelist": [
                {
                    "domain": "baidu.com",
                    "allowed_actions": ["click", "fill", "observe"],
                }
            ],
        }
        if config_dict:
            cfg.update(config_dict)

        plugin = BskBrowserPlugin(make_context(), config=cfg)
        plugin.service = MagicMock()
        plugin.service.get_active_url = AsyncMock(return_value="https://www.baidu.com")
        plugin.service.sessions = MagicMock()
        plugin._plugin_logger = MagicMock()
        return plugin

    async def test_dangerous_tool_hard_blocked_for_non_admin(self) -> None:
        plugin = self.make_plugin()
        event = FakeEvent(is_admin=False)
        for tool in ("bsk_load_tools", "bsk_debug", "bsk_assist", "bsk_status", "bsk_evaluate"):
            res = await plugin._dispatch(tool, event, {"action": "status"})
            self.assertTrue(
                "仅限管理员使用" in res or "仅限 AstrBot 管理员使用" in res or "没有权限" in res,
                f"{tool} should be blocked for non-admin, got {res}",
            )

    async def test_lifecycle_allowed_for_non_admin(self) -> None:
        plugin = self.make_plugin()
        event = FakeEvent(is_admin=False)
        plugin._run_tool = AsyncMock(return_value="OK")

        res_stop = await plugin._dispatch("bsk_session", event, {"action": "stop"})
        self.assertEqual(res_stop, "OK")

        res_sync = await plugin._dispatch("bsk_session", event, {"action": "sync"})
        self.assertEqual(res_sync, "OK")

        res_close = await plugin._dispatch("bsk_tabs", event, {"action": "close", "tab_id": 1})
        self.assertEqual(res_close, "OK")

    async def test_non_whitelisted_domain_rejected(self) -> None:
        plugin = self.make_plugin()
        event = FakeEvent(is_admin=False)
        res = await plugin._dispatch(
            "bsk_page", event, {"action": "navigate", "url": "https://evil.com/login"}
        )
        self.assertIn("不在允许访问的白名单中", res)

    async def test_whitelisted_domain_navigation_allowed(self) -> None:
        plugin = self.make_plugin()
        event = FakeEvent(is_admin=False)
        plugin._run_tool = AsyncMock(return_value="NAV_OK")
        res = await plugin._dispatch(
            "bsk_page", event, {"action": "navigate", "url": "https://www.baidu.com"}
        )
        self.assertEqual(res, "NAV_OK")

    async def test_whitelisted_in_page_allowed_and_disallowed(self) -> None:
        plugin = self.make_plugin()
        event = FakeEvent(is_admin=False)
        plugin.service.get_active_url = AsyncMock(return_value="https://www.baidu.com")
        plugin._run_tool = AsyncMock(return_value="ACTION_OK")

        # click is in allowed_actions
        res_click = await plugin._dispatch(
            "bsk_interact", event, {"action": "click", "target": "@e1"}
        )
        self.assertEqual(res_click, "ACTION_OK")

        # screenshot is not in allowed_actions
        items = [x async for x in plugin.bsk_inspect(event, action="screenshot")]
        self.assertTrue(any("未向普通用户开放该操作" in str(x) for x in items), f"Expected denial, got {items}")

    async def test_on_llm_request_strips_dangerous_tools_for_non_admin(self) -> None:
        plugin = self.make_plugin()
        event = FakeEvent(is_admin=False)
        req = MagicMock()
        req.func_tool = MagicMock()
        removed = []
        req.func_tool.remove_tool = MagicMock(side_effect=lambda name: removed.append(name))
        await plugin.on_llm_request(event, req)
        for d in ("bsk_load_tools", "bsk_debug", "bsk_assist", "bsk_status", "bsk_evaluate"):
            self.assertIn(d, removed)

    async def test_on_llm_request_keeps_tools_for_admin(self) -> None:
        plugin = self.make_plugin()
        event = FakeEvent(is_admin=True)
        req = MagicMock()
        req.func_tool = MagicMock()
        removed = []
        req.func_tool.remove_tool = MagicMock(side_effect=lambda name: removed.append(name))
        await plugin.on_llm_request(event, req)
        self.assertEqual(len(removed), 0)

    async def test_audit_log_called_on_check(self) -> None:
        plugin = self.make_plugin()
        event = FakeEvent(is_admin=False)
        await plugin._dispatch(
            "bsk_page", event, {"action": "navigate", "url": "https://evil.com/login"}
        )
        plugin._plugin_logger.debug.assert_called()
        any_audit = any(
            "[权限审计]" in str(call_arg)
            for call_args in plugin._plugin_logger.debug.call_args_list
            for call_arg in call_args[0]
        )
        self.assertTrue(any_audit)


if __name__ == "__main__":
    unittest.main()
