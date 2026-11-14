"""``bsk/runner.py`` 日志注入与记录的单元测试。"""

from __future__ import annotations

import asyncio
import stat
import sys
import tempfile
import unittest
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from bsk.runner import BskRunner  # noqa: E402
from tests.test_logger_injection import RecordingLogger  # noqa: E402

FAKE_SCRIPT = """\
import json
import sys
import time

mode = sys.argv[1] if len(sys.argv) > 1 else "ok"

if mode == "ok":
    sys.stdout.write(json.dumps({"ok": True, "data": "x" * 100}))
    sys.exit(0)
elif mode == "fail":
    sys.stderr.write("something failed: " + "e" * 100)
    sys.exit(1)
elif mode == "hang":
    time.sleep(10)
    sys.exit(0)
"""


class TestBskRunnerLogging(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmpdir = tempfile.TemporaryDirectory()
        cls.fake_dir = Path(cls._tmpdir.name)
        script = cls.fake_dir / "fake_bsk.py"
        script.write_text(FAKE_SCRIPT, encoding="utf-8")
        cls.fake_script = script

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmpdir.cleanup()

    async def test_runner_logs_start_and_finish_on_success(self):
        logger = RecordingLogger()
        runner = BskRunner(
            sys.executable,
            default_timeout=5.0,
            cancel_grace=1.0,
            logger=logger,
            max_log_len=20,
        )
        res = await runner.run([str(self.fake_script), "ok"])
        self.assertTrue(res.ok)

        debug_logs = [r for r in logger.records if r.level == "debug"]
        self.assertGreaterEqual(len(debug_logs), 2)

        start_log = debug_logs[0].render()
        self.assertIn("[bsk] 执行命令开始:", start_log)
        self.assertIn("fake_bsk.py", start_log)

        finish_log = debug_logs[1].render()
        self.assertIn("[bsk] 执行命令完成:", finish_log)
        self.assertIn("退出码: 0", finish_log)
        # 校验 20 字符截断生效
        self.assertIn("[已截断", finish_log)

    async def test_runner_logs_finish_on_error_exit(self):
        logger = RecordingLogger()
        runner = BskRunner(
            sys.executable,
            default_timeout=5.0,
            cancel_grace=1.0,
            logger=logger,
            max_log_len=30,
        )
        res = await runner.run([str(self.fake_script), "fail"])
        self.assertFalse(res.ok)

        debug_logs = [r for r in logger.records if r.level == "debug"]
        self.assertGreaterEqual(len(debug_logs), 2)
        finish_log = debug_logs[1].render()
        self.assertIn("[bsk] 执行命令完成:", finish_log)
        self.assertIn("退出码: 1", finish_log)
        self.assertIn("something failed:", finish_log)

    async def test_runner_logs_finish_on_timeout(self):
        logger = RecordingLogger()
        runner = BskRunner(
            sys.executable,
            default_timeout=0.2,
            cancel_grace=1.0,
            logger=logger,
        )
        res = await runner.run([str(self.fake_script), "hang"], timeout=0.2)
        self.assertFalse(res.ok)

        debug_logs = [r for r in logger.records if r.level == "debug"]
        self.assertGreaterEqual(len(debug_logs), 2)
        finish_log = debug_logs[1].render()
        self.assertIn("[bsk] 执行命令完成:", finish_log)
        self.assertIn("timeout", finish_log)

    async def test_runner_logs_on_spawn_failure(self):
        # 可执行文件不存在时抛出 BskError，并记录执行命令失败
        logger = RecordingLogger()
        runner = BskRunner(
            "/path/to/nonexistent/executable/xyz123",
            default_timeout=5.0,
            logger=logger,
        )
        from bsk.errors import BskError

        with self.assertRaises(BskError):
            await runner.run(["some_arg"])

        debug_logs = [r for r in logger.records if r.level == "debug"]
        self.assertGreaterEqual(len(debug_logs), 2)
        fail_log = debug_logs[1].render()
        self.assertIn("[bsk] 执行命令失败:", fail_log)
        self.assertIn("xyz123", fail_log)

    async def test_runner_logs_finish_on_external_cancellation(self):
        # 外部 Task 被 cancel 时，仍能清理并记录结束日志
        logger = RecordingLogger()
        runner = BskRunner(
            sys.executable,
            default_timeout=5.0,
            cancel_grace=1.0,
            logger=logger,
        )
        task = asyncio.create_task(runner.run([str(self.fake_script), "hang"]))
        await asyncio.sleep(0.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

        debug_logs = [r for r in logger.records if r.level == "debug"]
        self.assertGreaterEqual(len(debug_logs), 2)
        finish_log = debug_logs[1].render()
        self.assertIn("[bsk] 执行命令完成:", finish_log)
        self.assertIn("cancelled", finish_log)

    async def test_runner_without_logger_works_cleanly(self):
        # 未注入 logger 时走 NULL_LOGGER，绝不报错
        runner = BskRunner(sys.executable, default_timeout=5.0, cancel_grace=1.0)
        res = await runner.run([str(self.fake_script), "ok"])
        self.assertTrue(res.ok)


if __name__ == "__main__":
    unittest.main()
