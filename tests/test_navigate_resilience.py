import inspect
import unittest
from unittest.mock import AsyncMock, MagicMock
from astrbot_plugin_bsk_browser.bsk.errors import BskError
from astrbot_plugin_bsk_browser.bsk.models import BskResult, PageObservation
from astrbot_plugin_bsk_browser.bsk.service import BskService


class TestNavigateResilience(unittest.IsolatedAsyncioTestCase):
    async def test_navigate_recovers_from_observation_required(self) -> None:
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
                err = BskError("observation required", code="permission_denied")
                err.reason = "observation_required"
                err.effect_state = "none"
                raise err
            return BskResult(
                ok=True,
                exit_code=0,
                stdout="",
                stderr="",
                data={"url": "https://www.baidu.com"},
            )

        service.sessions.execute = mock_execute
        service.sync_session = AsyncMock(
            return_value=PageObservation(observation_id="obs-nav-1")
        )

        res = await service.navigate("s1", "https://www.baidu.com")
        self.assertEqual(call_count, 2)
        self.assertIn("--observation", executed_argv[1])
        idx = executed_argv[1].index("--observation")
        self.assertEqual(executed_argv[1][idx + 1], "obs-nav-1")
        self.assertEqual(res["url"], "https://www.baidu.com")
        self.assertNotIn("s1", service._session_observations)
