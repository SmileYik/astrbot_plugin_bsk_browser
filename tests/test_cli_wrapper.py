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
        await cli.stop_session("sess1")
        runner.run.assert_any_await(["session", "stop", "sess1"], timeout=15.0)
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
