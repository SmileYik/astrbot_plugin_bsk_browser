import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from bsk.service import BskService

def test_detect_new_tab_and_auto_select():
    async def _test():
        service = BskService(settings=MagicMock())
        service.sessions = MagicMock()
        service._resolve_key = MagicMock(return_value="sess_1")
        service._session_known_tabs["sess_1"] = {101}
        
        # 模拟 tab list 返回出现了新 tab 102
        tabs_data = {
            "tabs": [
                {"tab_id": 101, "title": "Baidu Search", "url": "https://www.baidu.com"},
                {"tab_id": 102, "title": "GTNH Baidu Tieba", "url": "https://tieba.baidu.com/p/123"}
            ]
        }
        service.tabs = AsyncMock(return_value=tabs_data)
        
        info = await service.detect_new_tabs_and_switch("sess_1")
        assert info is not None
        assert info["new_tab_id"] == 102
        assert info["title"] == "GTNH Baidu Tieba"
        assert info["url"] == "https://tieba.baidu.com/p/123"
        assert 102 in service._session_known_tabs["sess_1"]
        # 验证自动调用了 tab select 102
        service.tabs.assert_any_call("sess_1", "select", tab_id=102)

    asyncio.run(_test())

def test_detect_no_new_tab_returns_none():
    async def _test():
        service = BskService(settings=MagicMock())
        service.sessions = MagicMock()
        service._resolve_key = MagicMock(return_value="sess_1")
        service._session_known_tabs["sess_1"] = {101}
        
        tabs_data = {
            "tabs": [
                {"tab_id": 101, "title": "Baidu Search", "url": "https://www.baidu.com"}
            ]
        }
        service.tabs = AsyncMock(return_value=tabs_data)
        
        info = await service.detect_new_tabs_and_switch("sess_1")
        assert info is None
        # 没有新 tab 时不应调用 select
        assert not any(call[0][1] == "select" for call in service.tabs.call_args_list)

    asyncio.run(_test())

def test_render_tabs_supports_dict_format():
    service = BskService(settings=MagicMock())
    data = {
        "tabs": [
            {"tab_id": 101, "title": "Page 1", "url": "https://a.com", "active": False},
            {"tab_id": 102, "title": "Page 2", "url": "https://b.com", "active": True},
        ]
    }
    rendered = service._render_tabs(data)
    assert len(rendered) == 2
    assert rendered[0]["tab_id"] == 101
    assert rendered[1]["tab_id"] == 102


def test_detect_new_tabs_and_switch_integration_with_dict_payload():
    async def _test():
        service = BskService(settings=MagicMock())
        service._resolve_key = MagicMock(return_value="sess_1")
        service._session_known_tabs["sess_1"] = {101}

        async def mock_execute(key, fn, **kwargs):
            cmd = fn("fake_sid")
            if "list" in cmd:
                return MagicMock(data={
                    "tabs": [
                        {"tab_id": 101, "title": "Page 1", "url": "https://a.com", "active": False},
                        {"tab_id": 102, "title": "Page 2", "url": "https://b.com", "active": True},
                    ]
                })
            elif "select" in cmd:
                return MagicMock(data={"tab_id": 102})
            return MagicMock(data={})

        service.sessions.execute = AsyncMock(side_effect=mock_execute)

        info = await service.detect_new_tabs_and_switch("sess_1")
        assert info is not None
        assert info["new_tab_id"] == 102
        assert 102 in service._session_known_tabs["sess_1"]

    asyncio.run(_test())


def test_render_interact_renders_new_tab_notification():
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
        "action": "click",
        "target": "@e1",
        "tab_id": 102,
        "new_tab_info": {
            "new_tab_id": 102,
            "title": "New Tab Title",
            "url": "https://example.com/item"
        }
    }
    rendered = main.BskBrowserPlugin._render_interact("click", result)
    assert "【检测到新标签页】" in rendered
    assert "标签 ID: 102" in rendered
    assert "New Tab Title" in rendered
    assert "https://example.com/item" in rendered
    assert "【焦点已自动切换】" in rendered
    assert 'bsk_tabs(action="close", tab_id=102)' in rendered

