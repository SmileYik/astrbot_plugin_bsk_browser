import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bsk.service import BskService

def test_stop_session_sweeps_extra_agent_tabs_before_stopping():
    async def _test():
        service = BskService(settings=MagicMock())
        service.sessions = MagicMock()
        service._resolve_key = MagicMock(return_value="test_sess")
        service._session_known_tabs["test_sess"] = {101, 102}
        
        # 模拟当前 Agent Window 存在两个残留 Tab: 101, 102
        tabs_data = {
            "tabs": [
                {"tab_id": 101, "title": "Main Page", "url": "https://www.baidu.com"},
                {"tab_id": 102, "title": "Popup Tab", "url": "https://tieba.baidu.com"}
            ]
        }
        service.tabs = AsyncMock(return_value=tabs_data)
        service.sessions.release = AsyncMock(return_value=True)
        
        await service.stop_session("test_sess")
        
        # 验证关闭了多余的标签页 102
        service.tabs.assert_any_call("test_sess", "close", tab_id=102)
        # 验证调用了 sessions.release
        service.sessions.release.assert_called_once_with("test_sess")

    asyncio.run(_test())

def test_close_tab_removes_from_known_and_switches_focus():
    async def _test():
        service = BskService(settings=MagicMock())
        service.sessions = MagicMock()
        service._resolve_key = MagicMock(return_value="test_sess")
        service._session_known_tabs["test_sess"] = {101, 102}

        # 模拟底层 execute 调用
        async def mock_execute(key, fn, **kwargs):
            # 模拟执行 tab close 102
            cmd = fn("fake_sid")
            if "close" in cmd:
                return MagicMock(data={"tab_id": 102})
            elif "list" in cmd:
                return MagicMock(data=[
                    {"tab_id": 101, "title": "Main Page", "url": "https://www.baidu.com"}
                ])
            elif "select" in cmd:
                return MagicMock(data={"tab_id": 101})
            return MagicMock(data={})

        service.sessions.execute = AsyncMock(side_effect=mock_execute)

        out = await service.tabs("test_sess", "close", tab_id=102)

        # 验证从 known 集合移除
        assert 102 not in service._session_known_tabs["test_sess"]
        # 验证返回了切回标签页的信息
        assert "switched_to_tab" in out
        assert out["switched_to_tab"]["tab_id"] == 101

    asyncio.run(_test())

def test_render_tabs_renders_switched_focus_notification():
    import sys
    from pathlib import Path
    tests_dir = str(Path(__file__).resolve().parent)
    repo_parent = str(Path(__file__).resolve().parent.parent.parent)
    for p in (tests_dir, repo_parent):
        if p not in sys.path:
            sys.path.insert(0, p)
    from astrbot_test_doubles import ensure_astrbot_modules
    ensure_astrbot_modules()

    from astrbot_plugin_bsk_browser import main
    result = {
        "action": "close",
        "tab_id": 102,
        "switched_to_tab": {
            "tab_id": 101,
            "title": "Baidu Search",
            "url": "https://www.baidu.com"
        }
    }
    rendered = main.BskBrowserPlugin._render_tabs("close", result)
    assert "【焦点已切回】" in rendered
    assert "id=101" in rendered
    assert "Baidu Search" in rendered


def test_session_manager_stop_entry_sweeps_tabs_from_dict_payload():
    async def _test():
        from unittest.mock import AsyncMock, MagicMock
        from bsk.session import SessionManager, _Entry
        from bsk.models import BskSession

        runner = MagicMock()
        # 模拟 tab list 返回字典载荷 {"tabs": [...]}
        async def mock_run(args, timeout=None, **kwargs):
            cmd = " ".join(args)
            if "tab list" in cmd:
                return MagicMock(data={
                    "tabs": [
                        {"tab_id": 101, "title": "Baidu", "url": "https://www.baidu.com"},
                        {"tab_id": 102, "title": "Tieba", "url": "https://tieba.baidu.com"},
                    ]
                })
            elif "tab close" in cmd:
                return MagicMock(data={"tab_id": 102})
            elif "session stop" in cmd:
                return MagicMock(data={}, exit_code=0)
            return MagicMock(data={})

        runner.run = AsyncMock(side_effect=mock_run)
        runner.run_or_raise = AsyncMock(side_effect=mock_run)
        sm = SessionManager(runner, MagicMock())
        
        session = BskSession(session_id="test_sess", agent_window_id=1)
        entry = _Entry(key="k1", session=session, lock=asyncio.Lock(), last_used=100.0)

        success = await sm._stop_entry(entry)
        assert success is True

        # 验证确实对 tab_id=102 发起了 tab close
        close_calls = [call for call in runner.run.call_args_list if "close" in call[0][0]]
        assert len(close_calls) == 1
        assert "102" in close_calls[0][0][0] or "102" in close_calls[0][0]

    asyncio.run(_test())


def test_session_manager_reap_idle_cleans_extra_tabs():
    async def _test():
        from unittest.mock import AsyncMock, MagicMock
        from bsk.session import SessionManager, _Entry
        from bsk.models import BskSession

        runner = MagicMock()
        async def mock_run(args, timeout=None, **kwargs):
            cmd = " ".join(args)
            if "tab list" in cmd:
                return MagicMock(data={"tabs": [{"tab_id": 1}, {"tab_id": 2}]})
            elif "tab close" in cmd:
                return MagicMock(data={"tab_id": 2})
            elif "session stop" in cmd:
                return MagicMock(data={}, exit_code=0)
            return MagicMock(data={})

        runner.run = AsyncMock(side_effect=mock_run)
        runner.run_or_raise = AsyncMock(side_effect=mock_run)
        clock_time = 1000.0
        settings = MagicMock(idle_release_sec=10.0)
        sm = SessionManager(runner, settings)
        sm._clock = lambda: clock_time

        session = BskSession(session_id="idle_sess", agent_window_id=1)
        entry = _Entry(key="k_idle", session=session, lock=asyncio.Lock(), last_used=900.0)
        sm._entries["k_idle"] = entry

        count = await sm.reap_idle()
        assert count == 1
        assert "k_idle" not in sm._entries

        close_calls = [call for call in runner.run.call_args_list if "close" in call[0][0]]
        assert len(close_calls) == 1
        assert "2" in close_calls[0][0][0] or "2" in close_calls[0][0]

    asyncio.run(_test())


def test_detect_new_tabs_syncs_before_select():
    async def _test():
        service = BskService(settings=MagicMock())
        service.sessions = MagicMock()
        service._resolve_key = MagicMock(return_value="test_sess")
        service._session_known_tabs["test_sess"] = {101}

        # 模拟检测到新增了 102
        tabs_data = {
            "tabs": [
                {"tab_id": 101, "title": "Baidu", "url": "https://www.baidu.com"},
                {"tab_id": 102, "title": "Tieba", "url": "https://tieba.baidu.com"},
            ]
        }
        service.tabs = AsyncMock(return_value=tabs_data)
        service.sync = AsyncMock()

        out = await service.detect_new_tabs_and_switch("test_sess")
        assert out is not None
        assert out["new_tab_id"] == 102

        # 验证调用了 sync 同步新标签
        service.sync.assert_called_once_with("test_sess", tab_id=102)
        # 验证调用了 tabs(action="select")
        service.tabs.assert_any_call("test_sess", "select", tab_id=102)

    asyncio.run(_test())




