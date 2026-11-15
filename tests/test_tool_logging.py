"""``main.py`` 工具调用追踪切面的单元测试。"""

from __future__ import annotations

import dataclasses
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))
if str(_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tests"))

from astrbot_test_doubles import FakeEvent, ensure_astrbot_modules, make_context  # noqa: E402

ensure_astrbot_modules()

import astrbot_plugin_bsk_browser.main as main_mod  # noqa: E402
from astrbot_plugin_bsk_browser.bsk.models import PageObservation  # noqa: E402
from astrbot_plugin_bsk_browser.bsk.service import ShotPayload  # noqa: E402
from astrbot_plugin_bsk_browser.main import BskBrowserPlugin  # noqa: E402
from test_logger_injection import RecordingLogger  # noqa: E402


class TestToolLogging(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.logger = RecordingLogger()
        self.plugin = BskBrowserPlugin(
            make_context(),
            config={"admin_only": False, "log_max_output_length": 50},
        )
        self.plugin.service = MagicMock()
        self.event = FakeEvent(is_admin=True, sender_id="10001", umo="aiocqhttp:group:123")

    async def test_normal_async_tool_logs_start_and_finish(self) -> None:
        """测试普通异步工具（走 _dispatch 的新工具）调用起止成对记录。"""
        self.plugin.service.list_sessions = MagicMock(return_value={"sessions": []})
        with patch.object(main_mod, "astrbot_logger", self.logger):
            res = await self.plugin.bsk_session(self.event, action="list")

        self.assertIn("本插件当前没有任何浏览器会话", res)
        debug_logs = [r for r in self.logger.records if r.level == "debug"]
        self.assertGreaterEqual(len(debug_logs), 2)

        start_log = debug_logs[0].render()
        self.assertIn("[工具调用开始]", start_log)
        self.assertIn("工具: bsk_session", start_log)
        self.assertIn("umo=aiocqhttp:group:123", start_log)
        self.assertIn("sender=10001", start_log)
        self.assertIn("'action': 'list'", start_log)

        finish_log = debug_logs[1].render()
        self.assertIn("[工具调用结束]", finish_log)
        self.assertIn("工具: bsk_session", finish_log)
        self.assertIn("耗时:", finish_log)
        self.assertIn("状态: 成功", finish_log)

    async def test_status_tool_logs_start_and_finish(self) -> None:
        """测试独立扩展工具（bsk_status）调用起止成对记录。"""
        self.plugin.service.status = AsyncMock(return_value={"bsk_resolved": "/usr/bin/bsk", "error": ""})

        with patch.object(main_mod, "astrbot_logger", self.logger):
            res = await self.plugin.bsk_status(self.event)

        self.assertIn("bsk 可执行文件", res)
        debug_logs = [r for r in self.logger.records if r.level == "debug"]
        self.assertGreaterEqual(len(debug_logs), 2)

        start_log = debug_logs[0].render()
        self.assertIn("[工具调用开始]", start_log)
        self.assertIn("工具: bsk_status", start_log)

        finish_log = debug_logs[1].render()
        self.assertIn("[工具调用结束]", finish_log)
        self.assertIn("工具: bsk_status", finish_log)

    async def test_async_generator_tool_logs_start_and_finish(self) -> None:
        """测试异步生成器工具（bsk_inspect screenshot）的起止记录与 yield 透传。"""
        payload = ShotPayload(
            path="/tmp/shot.png",
            for_llm="LLM screenshot result " + "s" * 100,
            byte_size=1024,
            warning="",
        )
        self.plugin.service.screenshot_ex = AsyncMock(return_value=payload)
        self.event.image_result = MagicMock(return_value="[IMAGE:/tmp/shot.png]")

        with patch.object(main_mod, "astrbot_logger", self.logger):
            gen = self.plugin.bsk_inspect(self.event, action="screenshot")
            items = [item async for item in gen]

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0], "[IMAGE:/tmp/shot.png]")

        debug_logs = [r for r in self.logger.records if r.level == "debug"]
        self.assertGreaterEqual(len(debug_logs), 2)

        start_log = debug_logs[0].render()
        self.assertIn("[工具调用开始]", start_log)
        self.assertIn("工具: bsk_inspect", start_log)

        finish_log = debug_logs[1].render()
        self.assertIn("[工具调用结束]", finish_log)
        self.assertIn("工具: bsk_inspect", finish_log)
        self.assertIn("状态: 成功", finish_log)

    async def test_permission_denied_logs_start_and_finish(self) -> None:
        """测试被权限门拦截时，仍成对输出开始与结束日志。"""
        non_admin_event = FakeEvent(is_admin=False, sender_id="9999", umo="group:456")
        self.plugin.settings = dataclasses.replace(self.plugin.settings, admin_only=True)

        with patch.object(main_mod, "astrbot_logger", self.logger):
            res = await self.plugin.bsk_session(non_admin_event, action="start")

        self.assertIn("仅管理员可用", res)
        debug_logs = [r for r in self.logger.records if r.level == "debug"]
        self.assertGreaterEqual(len(debug_logs), 2)

        start_log = debug_logs[0].render()
        self.assertIn("[工具调用开始]", start_log)
        self.assertIn("sender=9999", start_log)

        finish_log = debug_logs[1].render()
        self.assertIn("[工具调用结束]", finish_log)
        self.assertIn("仅管理员可用", finish_log)

    async def test_tool_exception_logs_start_and_error_finish(self) -> None:
        """测试工具抛出异常时，正确记录开始日志与异常结束日志，且异常原样抛出。"""
        # 覆写 _dispatch 让其直接抛出未捕获异常
        self.plugin._dispatch = AsyncMock(side_effect=RuntimeError("critical tool failure"))

        with patch.object(main_mod, "astrbot_logger", self.logger):
            with self.assertRaises(RuntimeError):
                await self.plugin.bsk_session(self.event, action="sync")

        debug_logs = [r for r in self.logger.records if r.level == "debug"]
        self.assertGreaterEqual(len(debug_logs), 2)
        finish_log = debug_logs[1].render()
        self.assertIn("[工具调用结束]", finish_log)
        self.assertIn("状态: 异常", finish_log)
        self.assertIn("critical tool failure", finish_log)

    async def test_async_generator_early_break_logs_finish(self) -> None:
        """测试消费方提前 break 生成器时，GeneratorExit 仍能触发结束日志。"""
        payload = ShotPayload(path="/tmp/shot.png", for_llm="LLM shot", byte_size=100, warning="")
        self.plugin.service.screenshot_ex = AsyncMock(return_value=payload)
        self.event.image_result = MagicMock(return_value="[IMAGE]")

        with patch.object(main_mod, "astrbot_logger", self.logger):
            gen = self.plugin.bsk_inspect(self.event, action="screenshot")
            async for item in gen:
                # 只消费第一项就提前退出，触发 GeneratorExit
                break
            await gen.aclose()

        debug_logs = [r for r in self.logger.records if r.level == "debug"]
        self.assertGreaterEqual(len(debug_logs), 2)
        finish_log = debug_logs[1].render()
        self.assertIn("[工具调用结束]", finish_log)

    async def test_tool_start_log_truncates_large_args(self) -> None:
        """测试工具开始日志中过大的输入参数被保护性截断。"""
        self.plugin.service.list_sessions = MagicMock(return_value={"sessions": []})
        huge_val = "x" * 200

        with patch.object(main_mod, "astrbot_logger", self.logger):
            await self.plugin.bsk_session(self.event, action="list", huge=huge_val)

        debug_logs = [r for r in self.logger.records if r.level == "debug"]
        start_log = debug_logs[0].render()
        self.assertIn("[工具调用开始]", start_log)
        self.assertIn("[已截断", start_log)

    async def test_file_logger_mounted_and_receives_tool_logs(self) -> None:
        """测试配置 log_file_path 后，工具日志同步转存到指定文件并在 terminate 时关闭。"""
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            log_file = Path(td) / "plugin.log"
            plugin = BskBrowserPlugin(
                make_context(),
                config={
                    "admin_only": False,
                    "log_file_path": str(log_file),
                },
            )
            plugin.service.list_sessions = MagicMock(return_value={"sessions": []})
            self.assertIsNotNone(plugin._file_logger)

            await plugin.bsk_session(self.event, action="list")
            await plugin.terminate()

            self.assertIsNone(plugin._file_logger)
            content = log_file.read_text(encoding="utf-8")
            self.assertIn("[工具调用开始]", content)
            self.assertIn("工具: bsk_session", content)
            self.assertIn("[工具调用结束]", content)


if __name__ == "__main__":
    unittest.main()
