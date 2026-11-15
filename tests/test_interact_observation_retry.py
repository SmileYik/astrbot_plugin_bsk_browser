import inspect
import unittest
from unittest.mock import AsyncMock, MagicMock
from astrbot_plugin_bsk_browser.bsk.errors import BskError
from astrbot_plugin_bsk_browser.bsk.models import BskResult, PageObservation
from astrbot_plugin_bsk_browser.bsk.service import BskService


class TestInteractObservationRetry(unittest.IsolatedAsyncioTestCase):
    async def test_wheel_untargeted_pre_injects_and_pops_cached_token(self) -> None:
        service = BskService(settings=MagicMock(), runner=MagicMock())
        service.sessions = MagicMock()
        service._session_observations["s1"] = "obs-cached-1"

        executed_argv = []

        async def mock_execute(key, builder, **kwargs):
            res = builder("sid1") if callable(builder) else builder
            if inspect.isawaitable(res):
                res = await res
            executed_argv.append(res)
            return BskResult(
                ok=True,
                exit_code=0,
                stdout="",
                stderr="",
                data={"delta_y": 500, "tab_id": 1},
            )

        service.sessions.execute = mock_execute
        res = await service.interact("s1", "wheel", delta_y=500)

        self.assertIn("--observation", executed_argv[0])
        idx = executed_argv[0].index("--observation")
        self.assertEqual(executed_argv[0][idx + 1], "obs-cached-1")
        self.assertNotIn("s1", service._session_observations)
        self.assertFalse(res.get("auto_synced"))

    async def test_wheel_recovers_from_observation_required(self) -> None:
        service = BskService(settings=MagicMock(), runner=MagicMock())
        service.sessions = MagicMock()
        # 缓存为空，初次不带 token

        call_count = 0
        executed_argv = []

        async def mock_execute(key, builder, **kwargs):
            nonlocal call_count
            call_count += 1
            res = builder("sid1") if callable(builder) else builder
            if inspect.isawaitable(res):
                res = await res
            executed_argv.append(res)
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
                data={"delta_y": 500, "tab_id": 1},
            )

        service.sessions.execute = mock_execute
        service.sync_session = AsyncMock(
            return_value=PageObservation(observation_id="obs-fresh-2")
        )

        res = await service.interact("s1", "wheel", delta_y=500)

        self.assertEqual(call_count, 2)
        self.assertIn("--observation", executed_argv[1])
        idx = executed_argv[1].index("--observation")
        self.assertEqual(executed_argv[1][idx + 1], "obs-fresh-2")
        self.assertTrue(res.get("auto_synced"))
        self.assertNotIn("s1", service._session_observations)

    async def test_press_recovers_from_control_context_invalid(self) -> None:
        service = BskService(settings=MagicMock(), runner=MagicMock())
        service.sessions = MagicMock()

        call_count = 0
        executed_argv = []

        async def mock_execute(key, builder, **kwargs):
            nonlocal call_count
            call_count += 1
            res = builder("sid1") if callable(builder) else builder
            if inspect.isawaitable(res):
                res = await res
            executed_argv.append(res)
            if call_count == 1:
                err = BskError("focus changed", code="permission_denied")
                err.reason = "control_context_invalid"
                err.effect_state = "none"
                raise err
            return BskResult(
                ok=True,
                exit_code=0,
                stdout="",
                stderr="",
                data={"key": "Enter", "tab_id": 1},
            )

        service.sessions.execute = mock_execute
        service.sync_session = AsyncMock(
            return_value=PageObservation(observation_id="obs-fresh-3")
        )

        res = await service.interact("s1", "press", press_key="Enter")

        self.assertEqual(call_count, 2)
        self.assertIn("--observation", executed_argv[1])
        idx = executed_argv[1].index("--observation")
        self.assertEqual(executed_argv[1][idx + 1], "obs-fresh-3")
        self.assertTrue(res.get("auto_synced"))
