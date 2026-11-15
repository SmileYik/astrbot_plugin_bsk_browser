import inspect
import sys
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bsk.errors import BskError
from bsk.models import BskResult, PageObservation
from bsk.service import BskService


class TestScreenshotResilience(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings = MagicMock()
        self.settings.screenshot_dir = "/tmp/test_shots"

    @patch("bsk.service.cleanup_shots", return_value=0)
    @patch("bsk.service.verify_shot", return_value=(True, ""))
    async def test_screenshot_full_page_consumes_cached_observation_id(self, _mock_verify, _mock_cleanup) -> None:
        service = BskService(settings=self.settings, runner=MagicMock())
        service.sessions = MagicMock()
        service._session_observations["s1"] = "obs-token-123"

        executed_argv = []

        async def mock_run_or_raise(argv, **kwargs):
            executed_argv.append(argv)
            return BskResult(
                ok=True,
                exit_code=0,
                stdout="",
                stderr="",
                data={"path": "/tmp/test_shots/shot.png", "width": 800, "height": 600, "byte_size": 1024},
            )

        service.runner.run_or_raise = AsyncMock(side_effect=mock_run_or_raise)

        async def mock_execute_action(key, action, **kwargs):
            res = action("sid1")
            if inspect.isawaitable(res):
                res = await res
            return res

        service.sessions.execute_action = mock_execute_action
        res = await service.screenshot("s1", full_page=True)

        self.assertEqual(res.path, "/tmp/test_shots/shot.png")
        self.assertIn("--full-page", executed_argv[0])
        self.assertIn("--observation", executed_argv[0])
        idx = executed_argv[0].index("--observation")
        self.assertEqual(executed_argv[0][idx + 1], "obs-token-123")
        self.assertNotIn("s1", service._session_observations)

    @patch("bsk.service.cleanup_shots", return_value=0)
    @patch("bsk.service.verify_shot", return_value=(True, ""))
    async def test_screenshot_full_page_recovers_from_observation_required(self, _mock_verify, _mock_cleanup) -> None:
        service = BskService(settings=self.settings, runner=MagicMock())
        service.sessions = MagicMock()

        call_count = 0
        executed_argv = []

        async def mock_run_or_raise(argv, **kwargs):
            nonlocal call_count
            call_count += 1
            executed_argv.append(argv)
            if call_count == 1:
                err = BskError("observation required", code="permission_denied")
                err.reason = "observation_required"
                err.effect_state = "none"
                raise err
            return BskResult(
                ok=True,
                exit_code=0,
                stdout="",
                stderr="",
                data={"path": "/tmp/test_shots/shot2.png", "width": 800, "height": 600, "byte_size": 1024},
            )

        service.runner.run_or_raise = AsyncMock(side_effect=mock_run_or_raise)

        async def mock_execute_action(key, action, **kwargs):
            res = action("sid1")
            if inspect.isawaitable(res):
                res = await res
            return res

        service.sessions.execute_action = mock_execute_action
        service.sync_session = AsyncMock(
            return_value=PageObservation(observation_id="obs-fresh-456")
        )

        res = await service.screenshot("s1", full_page=True)

        self.assertEqual(call_count, 2)
        self.assertIn("--full-page", executed_argv[1])
        self.assertIn("--observation", executed_argv[1])
        idx = executed_argv[1].index("--observation")
        self.assertEqual(executed_argv[1][idx + 1], "obs-fresh-456")
        self.assertEqual(res.path, "/tmp/test_shots/shot2.png")
        self.assertNotIn("s1", service._session_observations)

    @patch("bsk.service.cleanup_shots", return_value=0)
    @patch("bsk.service.verify_shot", return_value=(True, ""))
    async def test_screenshot_ex_full_page_supports_explicit_and_cached_observation(self, _mock_verify, _mock_cleanup) -> None:
        service = BskService(settings=self.settings, runner=MagicMock())
        service.sessions = MagicMock()
        service._session_observations["s1"] = "obs-cached-ex"

        executed_argv = []

        async def mock_run_or_raise(argv, **kwargs):
            executed_argv.append(argv)
            return BskResult(
                ok=True,
                exit_code=0,
                stdout="",
                stderr="",
                data={"path": "/tmp/test_shots/shot_ex.png", "width": 800, "height": 600, "byte_size": 1024},
            )

        service.runner.run_or_raise = AsyncMock(side_effect=mock_run_or_raise)

        async def mock_execute_action(key, action, **kwargs):
            res = action("sid1")
            if inspect.isawaitable(res):
                res = await res
            return res

        service.sessions.execute_action = mock_execute_action
        # 1. 自动消费缓存
        res1 = await service.screenshot_ex("s1", full_page=True)
        self.assertIn("--observation", executed_argv[0])
        idx = executed_argv[0].index("--observation")
        self.assertEqual(executed_argv[0][idx + 1], "obs-cached-ex")
        self.assertNotIn("s1", service._session_observations)

        # 2. 传入显式 observation
        res2 = await service.screenshot_ex("s1", full_page=True, observation="obs-explicit")
        self.assertIn("--observation", executed_argv[1])
        idx2 = executed_argv[1].index("--observation")
        self.assertEqual(executed_argv[1][idx2 + 1], "obs-explicit")

    @patch("bsk.service.cleanup_shots", return_value=0)
    @patch("bsk.service.verify_shot", return_value=(True, ""))
    @patch("bsk.service.truncate_image_height", return_value=("/tmp/test_shots/shot_trunc.png", True))
    async def test_screenshot_ex_truncation_warning(self, mock_truncate, _mock_verify, _mock_cleanup) -> None:
        self.settings.fullpage_max_height = 5000
        self.settings.screenshot_compress_to_jpg = False
        service = BskService(settings=self.settings, runner=MagicMock())
        service.sessions = MagicMock()

        service.runner.run_or_raise = AsyncMock(return_value=BskResult(
            ok=True,
            exit_code=0,
            stdout="",
            stderr="",
            data={"path": "/tmp/test_shots/shot.png", "width": 800, "height": 10000, "byte_size": 2048},
        ))

        async def mock_execute_action(key, action, **kwargs):
            res = action("sid1")
            if inspect.isawaitable(res):
                res = await res
            return res

        service.sessions.execute_action = mock_execute_action
        res = await service.screenshot_ex("s1", full_page=True)
        self.assertIn("已按配置截断至最大高度 5000px", res.warning)
        self.assertEqual(res.height, 5000)


