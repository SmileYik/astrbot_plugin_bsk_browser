import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bsk.service import BskService
from bsk.errors import BskError, BskUserError
from bsk.models import PageObservation

def test_wheel_auto_recovers_from_observation_changed():
    async def _test():
        service = BskService(settings=MagicMock())
        service.sessions = MagicMock()
        service._resolve_key = MagicMock(return_value="test_session")
        service._timeout = MagicMock(return_value=30.0)
        service._interact_timeout_builtin = MagicMock(return_value=30.0)
        service._session_observations["test_session"] = "stale_obs_token"
        
        # 模拟第一次执行 wheel 抛出 observation_changed，重试后成功
        err = BskError("changed", reason="observation_changed", effect_state="none")
        success_result = MagicMock(data={"delta_y": 2000})
        service.sessions.execute = AsyncMock(side_effect=[err, success_result])
        
        new_obs = PageObservation(text="test", title="Test")
        new_obs.observation_id = "new_obs_token"
        service.sync_session = AsyncMock(return_value=new_obs)
        
        result = await service.interact("test_session", "wheel", delta_y=2000)
        assert result["delta_y"] == 2000
        assert result["auto_synced"] is True
        assert service.sync_session.called
        assert service.sessions.execute.call_count == 2
        # 验证重试时使用的 observation_id 为 new_obs_token
        second_call_builder = service.sessions.execute.call_args_list[1][0][1]
        argv = second_call_builder("test_session")
        assert "--observation" in argv
        obs_idx = argv.index("--observation")
        assert argv[obs_idx + 1] == "new_obs_token"

    asyncio.run(_test())

def test_click_invalidates_session_observations_cache():
    async def _test():
        service = BskService(settings=MagicMock())
        service.sessions = MagicMock()
        service._resolve_key = MagicMock(return_value="test_session")
        service._timeout = MagicMock(return_value=30.0)
        service._interact_timeout_builtin = MagicMock(return_value=30.0)
        service._session_observations["test_session"] = "stale_obs_token"
        
        success_result = MagicMock(data={"used_ref": "e1"})
        service.sessions.execute = AsyncMock(return_value=success_result)
        
        # 点击执行成功
        await service.interact("test_session", "click", target="@e1")
        
        # 点击之后该会话的旧 observation token 必须被清除失效
        assert "test_session" not in service._session_observations

    asyncio.run(_test())

