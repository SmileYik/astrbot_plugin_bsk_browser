"""tests for BskCli semantic wrapper methods."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from bsk.models import BskResult
from bsk.cli import BskCli


def _mock_result(data=None, exit_code=0):
    return BskResult(
        ok=(exit_code == 0),
        exit_code=exit_code,
        stdout="{}",
        stderr="",
        data=data or {},
    )


def test_cli_select_tab_builds_correct_args():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)
        res = await cli.select_tab("sess1", 101)
        assert res.exit_code == 0
        runner.run.assert_awaited_once_with(
            ["tab", "select", "101", "--session", "sess1", "--json"],
            timeout=5.0,
        )
    asyncio.run(_test())


def test_cli_close_tab_builds_correct_args():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)
        await cli.close_tab("sess1", 102, observation="obs1", context="ctx1")
        runner.run.assert_awaited_once_with(
            ["tab", "close", "102", "--session", "sess1", "--observation", "obs1", "--context", "ctx1", "--json"],
            timeout=5.0,
        )
    asyncio.run(_test())


def test_cli_sync_tab_builds_correct_args():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)
        await cli.sync_tab("sess1", tab_id=103)
        runner.run.assert_awaited_once_with(
            ["sync", "--session", "sess1", "--tab-id", "103", "--json"],
            timeout=5.0,
        )
    asyncio.run(_test())


def test_cli_list_tabs_builds_correct_args():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)
        await cli.list_tabs("sess1", scope="agent")
        runner.run.assert_awaited_once_with(
            ["tab", "list", "--scope", "agent", "--session", "sess1", "--json"],
            timeout=5.0,
        )
    asyncio.run(_test())


def test_cli_create_tab_builds_correct_args():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)
        await cli.create_tab("sess1", url="https://example.com", active=False)
        runner.run.assert_awaited_once_with(
            ["tab", "create", "--session", "sess1", "--url", "https://example.com", "--no-active", "--json"],
            timeout=5.0,
        )
    asyncio.run(_test())


def test_cli_borrow_and_return_tab_args():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)
        await cli.borrow_tab("sess1", 104)
        runner.run.assert_any_await(
            ["tab", "borrow", "104", "--session", "sess1", "--json"],
            timeout=5.0,
        )
        await cli.return_tab("sess1", 104)
        runner.run.assert_any_await(
            ["tab", "return", "104", "--session", "sess1", "--json"],
            timeout=5.0,
        )
    asyncio.run(_test())


def test_cli_session_methods():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)
        await cli.list_sessions()
        runner.run.assert_any_await(["session", "list", "--json"], timeout=10.0)
        await cli.stop_session("sess1", json=True)
        runner.run.assert_any_await(["session", "stop", "sess1", "--json"], timeout=15.0)
    asyncio.run(_test())


def test_cli_system_methods():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)
        await cli.get_version()
        runner.run.assert_any_await(["version", "--json"], timeout=5.0)
        await cli.get_status()
        runner.run.assert_any_await(["status", "--json"], timeout=10.0)
    asyncio.run(_test())


def test_cli_close_tab_safe_sequence():
    async def _test():
        call_sequence = []
        async def mock_run(args, timeout=None):
            cmd = " ".join(args)
            call_sequence.append(cmd)
            if "sync" in cmd:
                return _mock_result(data={"observation_id": "obs-999", "context_id": "ctx-888"})
            return _mock_result()

        runner = MagicMock()
        runner.run = AsyncMock(side_effect=mock_run)
        cli = BskCli(runner)

        res = await cli.close_tab_safe("sess1", 105)
        assert res.exit_code == 0
        assert len(call_sequence) == 3
        assert call_sequence[0].startswith("tab select 105 --session sess1")
        assert call_sequence[1].startswith("sync --session sess1 --tab-id 105")
        assert call_sequence[2].startswith("tab close 105 --session sess1")
        assert "--observation obs-999" in call_sequence[2]
        assert "--context ctx-888" in call_sequence[2]
    asyncio.run(_test())


def test_cli_close_tab_safe_tolerates_select_or_sync_failure():
    async def _test():
        call_sequence = []
        async def mock_run(args, timeout=None):
            cmd = " ".join(args)
            call_sequence.append(cmd)
            if "select" in cmd:
                raise Exception("select failed")
            if "sync" in cmd:
                return _mock_result(exit_code=1)
            return _mock_result()

        runner = MagicMock()
        runner.run = AsyncMock(side_effect=mock_run)
        cli = BskCli(runner)

        res = await cli.close_tab_safe("sess1", 106)
        assert res.exit_code == 0
        assert any("tab close 106" in cmd for cmd in call_sequence)
    asyncio.run(_test())


def test_runner_has_cli_instance():
    from bsk.runner import BskRunner
    runner = BskRunner(bsk_path="bsk")
    assert hasattr(runner, "cli")
    assert isinstance(runner.cli, BskCli)


def test_service_uses_cli():
    async def _test():
        from bsk.service import BskService
        runner = MagicMock()
        mock_res = _mock_result(data={"daemon_version": "0.5.0"})
        runner.run = AsyncMock(return_value=mock_res)
        runner.run_or_raise = AsyncMock(return_value=mock_res)
        service = BskService(settings=MagicMock(), runner=runner, logger=MagicMock())
        assert hasattr(service, "cli")
        assert isinstance(service.cli, BskCli)

        status_info = await service.status("default")
        assert status_info.get("daemon", {}).get("version") == "0.5.0"
        runner.run_or_raise.assert_any_await(["status", "--json"], timeout=5.0)
    asyncio.run(_test())
