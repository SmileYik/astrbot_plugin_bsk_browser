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


def test_cli_navigate_builds_correct_args():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)
        await cli.navigate(
            "sess1",
            "https://example.com",
            observation="obs-1",
            wait_until="networkidle",
            timeout_ms=10000,
            tab_id=2,
            timeout=45.0,
        )
        runner.run.assert_awaited_once_with(
            [
                "navigate",
                "https://example.com",
                "--observation",
                "obs-1",
                "--wait-until",
                "networkidle",
                "--timeout",
                "10s",
                "--tab-id",
                "2",
                "--session",
                "sess1",
                "--json",
            ],
            timeout=45.0,
        )
    asyncio.run(_test())


def test_cli_reload_and_wait_for_navigation():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)
        await cli.reload("sess1", hard=True, wait_until="load", timeout_ms=5000, tab_id=3, timeout=15.0)
        runner.run.assert_awaited_once_with(
            ["reload", "--hard", "--timeout", "5s", "--tab-id", "3", "--session", "sess1", "--json"],
            timeout=15.0,
        )

        runner.run.reset_mock()
        await cli.wait_for_navigation("sess1", wait_until="commit", timeout_ms=20000, tab_id=1, timeout=35.0)
        runner.run.assert_awaited_once_with(
            ["wait-for-navigation", "--wait-until", "commit", "--timeout", "20s", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=35.0,
        )
    asyncio.run(_test())


def test_cli_observe_snapshot_get_html_evaluate():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)

        # observe
        await cli.observe("sess1", cursor="cur1", max_depth=5, max_tokens=2000, probe_hover=True, debug_surfaces=True, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["observe", "--cursor", "cur1", "--max-depth", "5", "--max-tokens", "2000", "--probe-hover", "--debug-surfaces", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=15.0,
        )

        # snapshot
        runner.run.reset_mock()
        await cli.snapshot("sess1", max_depth=3, max_tokens=1000, tab_id=2)
        runner.run.assert_awaited_once_with(
            ["snapshot", "--max-depth", "3", "--max-tokens", "1000", "--tab-id", "2", "--session", "sess1", "--json"],
            timeout=15.0,
        )

        # get_html
        runner.run.reset_mock()
        await cli.get_html("sess1", ref="@e1", max_bytes=1024, tab_id=2)
        runner.run.assert_awaited_once_with(
            ["get-html", "--max-bytes", "1024", "--ref", "@e1", "--tab-id", "2", "--session", "sess1", "--json"],
            timeout=15.0,
        )

        # evaluate
        runner.run.reset_mock()
        await cli.evaluate("sess1", "1 + 1", timeout_ms=5000, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["evaluate", "1 + 1", "--timeout", "5s", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=45.0,
        )
    asyncio.run(_test())


def test_cli_click_hover_scroll_focus_blur():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)

        # click
        await cli.click("sess1", "@e1", button="right", click_count=2, modifiers=["Control"], capture_id="cap1", image_x=10, image_y=20, timeout_ms=3000, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["click", "@e1", "--button", "right", "--click-count", "2", "--modifiers", "Control", "--capture", "cap1", "--image-x", "10", "--image-y", "20", "--timeout", "3s", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=30.0,
        )

        # hover
        runner.run.reset_mock()
        await cli.hover("sess1", "@e2", modifiers=["Shift"], settle_ms=500, timeout_ms=4000, tab_id=2)
        runner.run.assert_awaited_once_with(
            ["hover", "@e2", "--modifiers", "Shift", "--settle", "500ms", "--timeout", "4s", "--tab-id", "2", "--session", "sess1", "--json"],
            timeout=30.0,
        )

        # scroll_to
        runner.run.reset_mock()
        await cli.scroll_to("sess1", "@e3", timeout_ms=2000, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["scroll-to", "@e3", "--timeout", "2s", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=30.0,
        )

        # focus and blur
        runner.run.reset_mock()
        await cli.focus("sess1", "@e4", tab_id=1)
        runner.run.assert_awaited_once_with(
            ["focus", "@e4", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=30.0,
        )
        runner.run.reset_mock()
        await cli.blur("sess1", "@e4", tab_id=1)
        runner.run.assert_awaited_once_with(
            ["blur", "@e4", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=30.0,
        )
    asyncio.run(_test())


def test_cli_fill_press_select_wheel():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)

        # fill with empty string (must preserve --value "")
        await cli.fill("sess1", "@e1", "", no_clear=True, timeout_ms=1000, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["fill", "@e1", "--value", "", "--no-clear", "--timeout", "1s", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=30.0,
        )

        # press
        runner.run.reset_mock()
        await cli.press("sess1", "Enter", target="@e2", modifiers=["Control"], observation_id="obs1", hold_ms=100, timeout_ms=2000, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["press", "Enter", "--ref", "@e2", "--modifiers", "Control", "--observation", "obs1", "--hold-ms", "100ms", "--timeout", "2s", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=30.0,
        )

        # select multiple
        runner.run.reset_mock()
        await cli.select("sess1", "@e3", ["v1", "v2"], timeout_ms=2000, tab_id=2)
        runner.run.assert_awaited_once_with(
            ["select", "@e3", "--value", "v1", "--value", "v2", "--timeout", "2s", "--tab-id", "2", "--session", "sess1", "--json"],
            timeout=30.0,
        )

        # wheel
        runner.run.reset_mock()
        await cli.wheel("sess1", delta_x=10, delta_y=100, target="@e4", modifiers=["Alt"], observation_id="obs2", timeout_ms=1000, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["wheel", "@e4", "--delta-x", "10", "--delta-y", "100", "--modifiers", "Alt", "--observation", "obs2", "--timeout", "1s", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=30.0,
        )
    asyncio.run(_test())


def test_cli_drag_upload_download_wait_element_wait_ms():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)

        # drag
        await cli.drag("sess1", "@e1", to_ref="@e2", offset_x=15, offset_y=25, timeout_ms=3000, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["drag", "@e1", "--to-ref", "@e2", "--offset-x", "15", "--offset-y", "25", "--timeout", "3s", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=30.0,
        )

        # upload
        runner.run.reset_mock()
        await cli.upload("sess1", "@e1", ["/tmp/a.png", "/tmp/b.png"], tab_id=1)
        runner.run.assert_awaited_once_with(
            ["upload", "@e1", "--file", "/tmp/a.png", "--file", "/tmp/b.png", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=30.0,
        )

        # download
        runner.run.reset_mock()
        await cli.download("sess1", "/tmp/download.zip", timeout_ms=5000, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["download", "/tmp/download.zip", "--timeout", "5s", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=60.0,
        )

        # wait_for_element
        runner.run.reset_mock()
        await cli.wait_for_element("sess1", "@e1", state="visible", timeout_ms=10000, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["wait-for-element", "@e1", "--state", "visible", "--timeout", "10s", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=35.0,
        )

        # wait_ms
        runner.run.reset_mock()
        await cli.wait_ms("sess1", 500, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["wait-ms", "500ms", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=35.0,
        )
    asyncio.run(_test())


def test_cli_diagnostics_screenshot_emulate_window_help():
    async def _test():
        runner = MagicMock()
        runner.run = AsyncMock(return_value=_mock_result())
        cli = BskCli(runner)

        # read_console
        await cli.read_console("sess1", since=100, limit=50, max_text_chars=200, include_stack=True, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["console", "--since", "100", "--limit", "50", "--max-text-chars", "200", "--include-stack", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=5.0,
        )

        # read_network
        runner.run.reset_mock()
        await cli.read_network("sess1", since=100, limit=20, max_text_chars=100, tab_id=2)
        runner.run.assert_awaited_once_with(
            ["network", "--since", "100", "--limit", "20", "--max-text-chars", "100", "--tab-id", "2", "--session", "sess1", "--json"],
            timeout=5.0,
        )

        # debug
        runner.run.reset_mock()
        await cli.debug("sess1", "enable", tab_id=1)
        runner.run.assert_awaited_once_with(
            ["debug", "enable", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=10.0,
        )

        # screenshot
        runner.run.reset_mock()
        await cli.screenshot("sess1", out="/tmp/shot.png", full_page=True, ref="@e1", format="png", quality=90, tab_id=1, timeout=60.0)
        runner.run.assert_awaited_once_with(
            ["screenshot", "--out", "/tmp/shot.png", "--full-page", "--ref", "@e1", "--format", "png", "--quality", "90", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=60.0,
        )

        # emulate
        runner.run.reset_mock()
        await cli.emulate("sess1", device="iPhone 14", width=390, height=844, user_agent="CustomUA", touch=True, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["emulate", "--device", "iPhone 14", "--width", "390", "--height", "844", "--ua", "CustomUA", "--touch", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=10.0,
        )

        # resize_window
        runner.run.reset_mock()
        await cli.resize_window("sess1", 1280, 800)
        runner.run.assert_awaited_once_with(
            ["window", "resize", "--width", "1280", "--height", "800", "--session", "sess1", "--json"],
            timeout=10.0,
        )

        # request_help
        runner.run.reset_mock()
        await cli.request_help("sess1", "Please solve captcha", timeout_sec=60, tab_id=1)
        runner.run.assert_awaited_once_with(
            ["request-help", "--prompt", "Please solve captcha", "--timeout", "60s", "--tab-id", "1", "--session", "sess1", "--json"],
            timeout=60.0,
        )
    asyncio.run(_test())


