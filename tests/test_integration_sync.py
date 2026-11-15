"""全链路端到端集成测试：页面控制权同步 (cooperation sync) 与自愈弹性链路。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))
if str(_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tests"))

from astrbot_test_doubles import ensure_astrbot_modules, make_context, FakeEvent

ensure_astrbot_modules()

from astrbot_plugin_bsk_browser.main import BskBrowserPlugin
from astrbot_plugin_bsk_browser.bsk.errors import classify
from astrbot_plugin_bsk_browser.bsk.models import BskResult
from astrbot_plugin_bsk_browser.bsk.service import BskService
from astrbot_plugin_bsk_browser.bsk.config import parse_settings


class FakeIntegrationRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.handlers: dict[str, Any] = {}

    async def run_or_raise(
        self, args: list[str], *, timeout: float | None = None, expect_json: bool = True
    ) -> BskResult:
        self.calls.append(list(args))
        cmd = args[0]
        if cmd == "session":
            subcmd = args[1] if len(args) > 1 else ""
            if subcmd == "start":
                return BskResult(
                    ok=True,
                    exit_code=0,
                    data={"session_id": "sid-sync-01", "browser_instance_id": "b-sync-01"},
                )
            return BskResult(ok=True, exit_code=0, data={})

        if cmd in self.handlers:
            res = await self.handlers[cmd](args)
            if not res.ok:
                from astrbot_plugin_bsk_browser.bsk.runner import _extract_error_fields

                code, message, hint, reason = _extract_error_fields(res.data)
                effect_state = ""
                if isinstance(res.data, dict):
                    extra = res.data.get("data")
                    if isinstance(extra, dict):
                        effect_state = str(extra.get("effect_state") or "")
                        if not reason:
                            reason = str(extra.get("reason") or "")
                    if not reason:
                        reason = str(res.data.get("reason") or "")
                    if not message:
                        message = str(res.data.get("message") or "")
                    if not code:
                        code = str(res.data.get("code") or "permission_denied")
                raise classify(
                    exit_code=res.exit_code,
                    code=code,
                    message=message,
                    hint=hint,
                    reason=reason,
                    stderr=res.stderr,
                    effect_state=effect_state,
                )
            return res

        return BskResult(ok=True, exit_code=0, data={})


class TestIntegrationSyncSuite(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.runner = FakeIntegrationRunner()
        settings = parse_settings(
            {
                "bsk_path": "bsk",
                "browser_instance_id": "b-sync-01",
                "command_timeout_sec": 30.0,
                "screenshot_dir": self.tmp.name,
                "enable_request_id": False,
            }
        )
        self.service = BskService(settings, runner=self.runner)
        self.plugin = BskBrowserPlugin(make_context(), config={"admin_only": False})
        self.plugin.service = self.service
        self.event = FakeEvent(is_admin=True, umo="test:user:sync")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    async def test_scenario_1_open_and_direct_interact(self) -> None:
        """场景 1：模型使用标准链路 bsk_session(action='open') 打开网页并直接交互。"""
        async def handle_open(args: list[str]) -> BskResult:
            return BskResult(
                ok=True,
                exit_code=0,
                data={
                    "vom": "@vom 1\n@view 800x600\nRootWebArea \"Search Engine\"\n@e1 combobox \"Search\"\n@e2 button \"Submit\"",
                    "tab_id": 1,
                },
            )

        async def handle_fill(args: list[str]) -> BskResult:
            return BskResult(
                ok=True,
                exit_code=0,
                data={"session": "sid-sync-01", "target": "@e1", "value": "gtnh"},
            )

        self.runner.handlers["open"] = handle_open
        self.runner.handlers["fill"] = handle_fill

        # 1. bsk_session(open)
        open_res = await self.plugin._dispatch(
            "bsk_session",
            self.event,
            {"action": "open", "url": "https://www.baidu.com"},
        )
        self.assertIn("Search Engine", open_res)
        self.assertIn("@e1", open_res)

        # 2. bsk_interact(fill)
        fill_res = await self.plugin._dispatch(
            "bsk_interact",
            self.event,
            {"action": "fill", "target": "@e1", "value": "gtnh"},
        )
        self.assertIn("已执行 fill。", fill_res)
        self.assertIn("@e1", fill_res)
        self.assertNotIn("已在后台自动执行 sync 补救重试", fill_res)

        cmds = [c[0] for c in self.runner.calls]
        self.assertEqual(cmds, ["session", "open", "fill"])

    async def test_scenario_2_navigate_observe_interact_workflow(self) -> None:
        """场景 2：模型采用 navigate -> observe -> interact 流程。
        由于 observe 底层透明同步，interact 一次成功，无需补救重试。
        """
        await self.service.start_session(key="test:user:sync")
        self.runner.calls.clear()

        async def handle_navigate(args: list[str]) -> BskResult:
            return BskResult(ok=True, exit_code=0, data={"url": "https://www.baidu.com", "reached": "ready"})

        async def handle_observe(args: list[str]) -> BskResult:
            return BskResult(
                ok=True,
                exit_code=0,
                data={
                    "text": "@vom 1\n@view 800x600\nRootWebArea \"Baidu\"\n@e1 combobox \"kw\"\n@e2 button \"su\"",
                    "tab_id": 1,
                },
            )

        async def handle_fill(args: list[str]) -> BskResult:
            return BskResult(
                ok=True,
                exit_code=0,
                data={"session": "sid-sync-01", "target": "@e1", "value": "gtnh"},
            )

        async def handle_sync(args: list[str]) -> BskResult:
            return BskResult(
                ok=True,
                exit_code=0,
                data={
                    "vom": "@vom 1\n@view 800x600\nRootWebArea \"Baidu\"\n@e1 combobox \"kw\"\n@e2 button \"su\"",
                    "tab_id": 1,
                },
            )

        self.runner.handlers["navigate"] = handle_navigate
        self.runner.handlers["observe"] = handle_observe
        self.runner.handlers["fill"] = handle_fill
        self.runner.handlers["sync"] = handle_sync

        # 1. bsk_page(navigate)
        nav_res = await self.plugin._dispatch(
            "bsk_page", self.event, {"action": "navigate", "url": "https://www.baidu.com"}
        )
        self.assertIn("已导航", nav_res)
        self.assertIn('bsk_session(action="sync")', nav_res)

        # 2. bsk_inspect(observe)
        obs_res = await self.plugin._dispatch(
            "bsk_inspect", self.event, {"action": "observe"}
        )
        self.assertIn("Baidu", obs_res)
        self.assertIn("@e1", obs_res)

        # 3. bsk_interact(fill) -> 正常填入，无需 auto_sync 补救
        fill_res = await self.plugin._dispatch(
            "bsk_interact", self.event, {"action": "fill", "target": "@e1", "value": "gtnh"}
        )
        self.assertIn("已执行 fill。", fill_res)
        self.assertNotIn("已在后台自动执行 sync 补救重试", fill_res)

        cmds = [c[0] for c in self.runner.calls]
        self.assertEqual(cmds, ["navigate", "sync", "fill"])

    async def test_scenario_2_b_cooperation_sync_on_ref_gives_guidance_without_restart(self) -> None:
        """场景 2b：若交互遇到 cooperation_sync_required 且目标为 @ref 时，
        自动执行 sync 后优雅返回失效提示与新 VOM 引导，绝不触发会话重建或空白页。
        """
        await self.service.start_session(key="test:user:sync")
        self.runner.calls.clear()

        async def handle_fill(args: list[str]) -> BskResult:
            return BskResult(
                ok=False,
                exit_code=5,
                data={
                    "code": "permission_denied",
                    "data": {
                        "action": "fill",
                        "effect_state": "none",
                        "reason": "cooperation_sync_required",
                    },
                    "reason": "cooperation_sync_required",
                    "message": "cooperation control context required",
                },
            )

        async def handle_sync(args: list[str]) -> BskResult:
            return BskResult(
                ok=True,
                exit_code=0,
                data={
                    "vom": "@vom 1\n@view 800x600\nRootWebArea \"Baidu New\"\n@e56 combobox \"kw\"\n@e57 button \"su\"",
                    "tab_id": 1,
                },
            )

        self.runner.handlers["fill"] = handle_fill
        self.runner.handlers["sync"] = handle_sync

        fill_res = await self.plugin._dispatch(
            "bsk_interact", self.event, {"action": "fill", "target": "@e15", "value": "gtnh"}
        )
        self.assertIn("已在后台自动执行 sync 完成同步", fill_res)
        self.assertIn("原元素编号「@e15」已失效", fill_res)
        self.assertIn("@e56", fill_res)
        # 会话绝未被标记为 gone，未触发 restart
        cmds = [c[0] for c in self.runner.calls]
        self.assertEqual(cmds, ["fill", "sync"])
        self.assertNotIn("session start", cmds)

    async def test_scenario_3_explicit_session_sync(self) -> None:
        """场景 3：模型主动调用 bsk_session(action='sync') 同步页面控制权。"""
        await self.service.start_session(key="test:user:sync")
        self.runner.calls.clear()

        async def handle_sync(args: list[str]) -> BskResult:
            return BskResult(
                ok=True,
                exit_code=0,
                data={
                    "vom": "@vom 1\n@view 800x600\nRootWebArea \"Active Page\"\n@e1 button \"Confirm\"",
                    "tab_id": 1,
                },
            )

        async def handle_click(args: list[str]) -> BskResult:
            return BskResult(
                ok=True,
                exit_code=0,
                data={"session": "sid-sync-01", "target": "@e1", "clicked": True},
            )

        self.runner.handlers["sync"] = handle_sync
        self.runner.handlers["click"] = handle_click

        sync_res = await self.plugin._dispatch(
            "bsk_session", self.event, {"action": "sync"}
        )
        self.assertIn("Active Page", sync_res)
        self.assertIn("@e1", sync_res)

        click_res = await self.plugin._dispatch(
            "bsk_interact", self.event, {"action": "click", "target": "@e1"}
        )
        self.assertIn("已执行 click。", click_res)
        self.assertNotIn("已在后台自动执行 sync 补救重试", click_res)

        cmds = [c[0] for c in self.runner.calls]
        self.assertEqual(cmds, ["sync", "click", "tab"])

    async def test_scenario_4_dual_auto_sync_and_auto_scroll(self) -> None:
        """场景 4：叠加自愈（同时缺少控制权与元素不在视口），先自动 sync 再自动 scroll-to 最终成功。"""
        await self.service.start_session(key="test:user:sync")
        self.runner.calls.clear()

        click_count = 0

        async def handle_click(args: list[str]) -> BskResult:
            nonlocal click_count
            click_count += 1
            if click_count == 1:
                return BskResult(
                    ok=False,
                    exit_code=5,
                    data={
                        "code": "permission_denied",
                        "data": {
                            "action": "click",
                            "effect_state": "none",
                            "reason": "cooperation_sync_required",
                        },
                        "reason": "cooperation_sync_required",
                        "message": "sync required",
                    },
                )
            if click_count == 2:
                return BskResult(
                    ok=False,
                    exit_code=1,
                    data={
                        "code": "permission_denied",
                        "reason": "element_not_visible",
                        "message": "Element not visible",
                    },
                )
            return BskResult(
                ok=True,
                exit_code=0,
                data={"session": "sid-sync-01", "target": "button.far-below", "clicked": True},
            )

        async def handle_sync(args: list[str]) -> BskResult:
            return BskResult(
                ok=True,
                exit_code=0,
                data={"vom": "@vom 1\nRootWebArea \"Test\"\n@e99 button \"Far Below\"", "tab_id": 1},
            )

        async def handle_scroll_to(args: list[str]) -> BskResult:
            return BskResult(
                ok=True,
                exit_code=0,
                data={"session": "sid-sync-01", "target": "button.far-below", "scrolled": True},
            )

        self.runner.handlers["click"] = handle_click
        self.runner.handlers["sync"] = handle_sync
        self.runner.handlers["scroll-to"] = handle_scroll_to

        res = await self.plugin._dispatch(
            "bsk_interact", self.event, {"action": "click", "target": "button.far-below"}
        )

        self.assertIn("已执行 click。", res)
        self.assertIn("已在后台自动执行 sync 补救重试", res)
        self.assertIn("目标元素原先位于视口外，已自动将其滚动至视口中心", res)

        cmds = [c[0] for c in self.runner.calls]
        self.assertEqual(cmds, ["click", "sync", "click", "scroll-to", "click", "tab"])


if __name__ == "__main__":
    unittest.main()
