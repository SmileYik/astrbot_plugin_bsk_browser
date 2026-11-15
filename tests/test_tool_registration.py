"""工具注册与停用（bsk_status / bsk_evaluate / 移除旧工具）的测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))
if str(_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tests"))

from astrbot_test_doubles import ensure_astrbot_modules, make_context  # noqa: E402

ensure_astrbot_modules()

from astrbot.core.provider.register import llm_tools  # noqa: E402
import astrbot_plugin_bsk_browser.main as main_mod  # noqa: E402


class FakeFuncTool:
    def __init__(self, name: str, active: bool = True) -> None:
        self.name = name
        self.active = active


class TestToolRegistration(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        llm_tools.func_list.clear()
        llm_tools.func_list.extend(
            [
                FakeFuncTool("bsk_status", active=True),
                FakeFuncTool("bsk_evaluate", active=True),
            ]
        )

    def test_legacy_tools_do_not_exist_on_plugin(self) -> None:
        plugin = main_mod.BskBrowserPlugin(make_context(), config={})
        for name in ("bsk_open", "bsk_read", "bsk_act", "bsk_close", "bsk_logs"):
            self.assertFalse(hasattr(plugin, name), f"{name} should be removed from plugin")

    async def test_default_registration(self) -> None:
        plugin = main_mod.BskBrowserPlugin(make_context(), config={})
        await plugin.initialize()
        status_tool = llm_tools.get_func("bsk_status")
        eval_tool = llm_tools.get_func("bsk_evaluate")
        self.assertIsNotNone(status_tool)
        self.assertIsNotNone(eval_tool)
        self.assertTrue(status_tool.active)
        self.assertFalse(eval_tool.active)

    async def test_enable_status_false(self) -> None:
        plugin = main_mod.BskBrowserPlugin(make_context(), config={"enable_status": False})
        await plugin.initialize()
        status_tool = llm_tools.get_func("bsk_status")
        self.assertIsNotNone(status_tool)
        self.assertFalse(status_tool.active)

    async def test_enable_evaluate_true(self) -> None:
        plugin = main_mod.BskBrowserPlugin(make_context(), config={"enable_evaluate": True})
        await plugin.initialize()
        eval_tool = llm_tools.get_func("bsk_evaluate")
        self.assertIsNotNone(eval_tool)
        self.assertTrue(eval_tool.active)


if __name__ == "__main__":
    unittest.main()
