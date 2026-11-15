import sys
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bsk.models import BskResult
from bsk.service import BskService


class TestServiceObservationCache(unittest.IsolatedAsyncioTestCase):
    async def test_sync_and_open_cache_observation_id(self) -> None:
        service = BskService(settings=MagicMock(), runner=MagicMock())
        service.sessions = MagicMock()

        # 模拟 sync_session 返回 observation_id
        mock_sync_result = BskResult(
            ok=True,
            exit_code=0,
            stdout="",
            stderr="",
            data={
                "observation_id": "obs-sync-1",
                "tab_id": 1,
                "vom": "@vom 1\nL1 page",
            },
        )
        service.sessions.execute = AsyncMock(return_value=mock_sync_result)
        service.sessions.execute_action = AsyncMock(return_value=mock_sync_result)
        obs = await service.sync_session("s1")
        self.assertEqual(obs.observation_id, "obs-sync-1")
        self.assertEqual(service._session_observations.get("s1"), "obs-sync-1")

        # 模拟 open_session 返回 obs 别名
        mock_open_result = BskResult(
            ok=True,
            exit_code=0,
            stdout="",
            stderr="",
            data={"obs": "o20", "tab_id": 1, "vom": "@vom 1\nL1 page"},
        )
        service.sessions.execute = AsyncMock(return_value=mock_open_result)
        service.sessions.execute_action = AsyncMock(return_value=mock_open_result)
        obs2 = await service.open_session("s1", "https://example.com")
        self.assertEqual(obs2.observation_id, "o20")
        self.assertEqual(service._session_observations.get("s1"), "o20")

    async def test_navigate_and_history_clear_observation_cache(self) -> None:
        service = BskService(settings=MagicMock(), runner=MagicMock())
        service.sessions = MagicMock()
        service._session_observations["s1"] = "obs-old"

        mock_nav_result = BskResult(
            ok=True,
            exit_code=0,
            stdout="",
            stderr="",
            data={"url": "https://example.com/2"},
        )
        service.sessions.execute = AsyncMock(return_value=mock_nav_result)
        service.sessions.execute_action = AsyncMock(return_value=mock_nav_result)
        service.observe = AsyncMock()

        await service.navigate("s1", "https://example.com/2")
        self.assertNotIn("s1", service._session_observations)

    async def test_release_clears_observation_cache(self) -> None:
        service = BskService(settings=MagicMock(), runner=MagicMock())
        service.sessions = MagicMock()
        service.sessions.release = AsyncMock(return_value=True)
        service._session_observations["s1"] = "obs-1"

        await service.release_session("s1")
        self.assertNotIn("s1", service._session_observations)
