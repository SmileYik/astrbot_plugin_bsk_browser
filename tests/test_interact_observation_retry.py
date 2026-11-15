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

    async def test_wheel_explicit_observation_id_not_overwritten(self) -> None:
        service = BskService(settings=MagicMock(), runner=MagicMock())
        service.sessions = MagicMock()
        service._session_observations["s1"] = "cached-obs-token"

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
        await service.interact("s1", "wheel", delta_y=500, observation_id="caller-supplied-token")

        self.assertIn("--observation", executed_argv[0])
        idx = executed_argv[0].index("--observation")
        self.assertEqual(executed_argv[0][idx + 1], "caller-supplied-token")
        # 缓存中的令牌未被覆盖或意外清除
        self.assertEqual(service._session_observations.get("s1"), "cached-obs-token")

    async def test_consecutive_untargeted_wheels_succeed(self) -> None:
        service = BskService(settings=MagicMock(), runner=MagicMock())
        service.sessions = MagicMock()
        service._session_observations["s1"] = "obs-initial-1"

        executed_argv = []
        sync_counter = 0

        async def mock_execute(key, builder, **kwargs):
            res = builder("sid1") if callable(builder) else builder
            if inspect.isawaitable(res):
                res = await res
            executed_argv.append(res)
            # 如果没有传 --observation，底层抛出 observation_required
            if "--observation" not in res:
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

        async def mock_sync(session_key, **kwargs):
            nonlocal sync_counter
            sync_counter += 1
            return PageObservation(observation_id=f"obs-synced-{sync_counter}")

        service.sessions.execute = mock_execute
        service.sync_session = mock_sync

        # 第一次滚动：命中初始缓存
        res1 = await service.interact("s1", "wheel", delta_y=500)
        self.assertFalse(res1.get("auto_synced"))
        self.assertIn("obs-initial-1", executed_argv[0])

        # 第二次连续滚动：缓存已被消耗，首次触发 observation_required，随后自动 sync 重试成功
        res2 = await service.interact("s1", "wheel", delta_y=500)
        self.assertTrue(res2.get("auto_synced"))
        self.assertIn("obs-synced-1", executed_argv[-1])

        # 第三次连续滚动：再次自动自愈重试成功
        res3 = await service.interact("s1", "wheel", delta_y=500)
        self.assertTrue(res3.get("auto_synced"))
        self.assertIn("obs-synced-2", executed_argv[-1])
        self.assertEqual(sync_counter, 2)
