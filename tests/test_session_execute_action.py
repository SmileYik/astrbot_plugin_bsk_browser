"""Unit tests for SessionManager.execute_action and close_tab_safe."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from bsk.errors import BskError, BskOutcomeUnknown, BskSessionBusy, BskSessionGone
from bsk.models import BskResult
from bsk.session import SessionManager


def _mock_result(data=None, exit_code=0):
    return BskResult(
        ok=(exit_code == 0),
        exit_code=exit_code,
        stdout="{}",
        stderr="",
        data=data or {},
    )


def test_session_execute_action_success():
    async def _test():
        runner = MagicMock()
        mock_cli = MagicMock()
        mgr = SessionManager(settings=MagicMock(), runner=runner, cli=mock_cli, logger=MagicMock())
        # mock start session
        mock_cli.start_session = AsyncMock(return_value=_mock_result({"session_id": "sid_1"}))
        mock_cli.list_sessions = AsyncMock(return_value=_mock_result({"sessions": []}))

        action = AsyncMock(return_value=_mock_result({"nav": "ok"}))
        res = await mgr.execute_action("key1", action)
        assert res.data == {"nav": "ok"}
        action.assert_awaited_once_with("sid_1")
    asyncio.run(_test())


def test_session_execute_action_rebuilds_on_gone():
    async def _test():
        runner = MagicMock()
        mock_cli = MagicMock()
        mgr = SessionManager(settings=MagicMock(), runner=runner, cli=mock_cli, logger=MagicMock())
        
        # Starts first with sid_1, then restarts with sid_2
        mock_cli.start_session = AsyncMock(
            side_effect=[
                _mock_result({"session_id": "sid_1"}),
                _mock_result({"session_id": "sid_2"}),
            ]
        )
        mock_cli.list_sessions = AsyncMock(return_value=_mock_result({"sessions": []}))

        calls = []
        async def mock_action(sid):
            calls.append(sid)
            if sid == "sid_1":
                raise BskSessionGone("session expired")
            return _mock_result({"status": "recovered"})

        res = await mgr.execute_action("key1", mock_action)
        assert res.data == {"status": "recovered"}
        assert calls == ["sid_1", "sid_2"]
    asyncio.run(_test())


def test_session_close_tab_safe_sequence():
    async def _test():
        runner = MagicMock()
        mock_cli = MagicMock()
        mgr = SessionManager(settings=MagicMock(), runner=runner, cli=mock_cli, logger=MagicMock())

        mock_cli.select_tab = AsyncMock(return_value=_mock_result())
        mock_cli.sync_tab = AsyncMock(return_value=_mock_result({"observation_id": "obs_123", "context_id": "ctx_456"}))
        mock_cli.close_tab = AsyncMock(return_value=_mock_result())

        res = await mgr.close_tab_safe("sid_test", 101)
        assert res.ok

        mock_cli.select_tab.assert_awaited_once_with("sid_test", 101, timeout=5.0)
        mock_cli.sync_tab.assert_awaited_once_with("sid_test", tab_id=101, timeout=5.0)
        mock_cli.close_tab.assert_awaited_once_with(
            "sid_test", 101, observation="obs_123", context="ctx_456", timeout=5.0, raise_on_error=False
        )
    asyncio.run(_test())
