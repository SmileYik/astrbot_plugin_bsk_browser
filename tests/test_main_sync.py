import unittest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))
if str(_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tests"))

from astrbot_test_doubles import ensure_astrbot_modules, make_context, FakeEvent

ensure_astrbot_modules()

from astrbot_plugin_bsk_browser.main import BskBrowserPlugin
from astrbot_plugin_bsk_browser.bsk.models import PageObservation


class TestMainSync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.plugin = BskBrowserPlugin(make_context(), config={"admin_only": False})
        self.plugin.service = MagicMock()
        self.event = FakeEvent(is_admin=True, umo="test:user:1")

    async def test_bsk_session_sync_dispatched(self) -> None:
        obs = PageObservation(text="Sync Page Content", title="Sync Title")
        self.plugin.service.sync_session = AsyncMock(return_value=obs)
        self.plugin.service.render_page = MagicMock(return_value="Rendered Sync VOM")

        res = await self.plugin.bsk_session(self.event, action="sync")
        self.assertIn("Rendered Sync VOM", res)
        self.plugin.service.sync_session.assert_called_once()
        call_kwargs = self.plugin.service.sync_session.call_args[1]
        self.assertEqual(call_kwargs.get("key"), "test:user:1")

    async def test_bsk_session_open_dispatched(self) -> None:
        obs = PageObservation(text="Open Page Content", title="Open Title")
        self.plugin.service.open_session = AsyncMock(return_value=obs)
        self.plugin.service.render_page = MagicMock(return_value="Rendered Open VOM")

        res = await self.plugin.bsk_session(self.event, action="open", url="https://example.com")
        self.assertIn("Rendered Open VOM", res)
        self.plugin.service.open_session.assert_called_once()
        call_kwargs = self.plugin.service.open_session.call_args[1]
        self.assertEqual(call_kwargs.get("url"), "https://example.com")

    async def test_interact_renders_auto_synced_notice(self) -> None:
        self.plugin.service.interact = AsyncMock(
            return_value={
                "session": "s1",
                "action": "click",
                "auto_synced": True,
                "auto_scrolled": False,
                "target": "@e1",
            }
        )

        res = await self.plugin.bsk_interact(self.event, action="click", target="@e1")
        self.assertIn("已在后台自动执行 sync 补救重试", res)

    async def test_interact_result_three_tier_format(self) -> None:
        self.plugin.service.interact = AsyncMock(
            return_value={
                "session": "s1",
                "action": "click",
                "target": "@e1",
            }
        )
        res = await self.plugin.bsk_interact(self.event, action="click", target="@e1")
        self.assertIn("【状态】已执行 click", res)
        self.assertIn("【结果摘要】", res)
        self.assertIn("【推荐后续动作】", res)

    async def test_nav_result_three_tier_format(self) -> None:
        self.plugin.service.navigate = AsyncMock(
            return_value={
                "session": "s1",
                "url": "https://example.com",
                "final_url": "https://example.com",
                "reached": "networkidle",
            }
        )
        res = await self.plugin.bsk_page(self.event, action="navigate", url="https://example.com")
        self.assertIn("【状态】", res)
        self.assertIn("【结果摘要】", res)
        self.assertIn("【推荐后续动作】", res)

    async def test_observation_required_recovery_hint(self) -> None:
        from astrbot_plugin_bsk_browser.bsk.errors import BskError
        self.plugin.service.navigate = AsyncMock(
            side_effect=BskError("observation required", reason="observation_required")
        )
        res = await self.plugin.bsk_page(self.event, action="navigate", url="https://example.com")
        self.assertIn("【操作受阻】", res)
        self.assertIn('bsk_session(action="sync")', res)

    async def test_observe_forwards_query_and_slice(self) -> None:
        obs = PageObservation(text="Content", title="Title")
        self.plugin.service.observe = AsyncMock(return_value=obs)
        self.plugin.service.render_page = MagicMock(return_value="Filtered Rendered VOM")

        gen = self.plugin.bsk_inspect(
            self.event, action="observe", query="gtnh", offset=10, limit=20, view="elements"
        )
        items = [item async for item in gen]
        res = items[-1]
        self.assertIn("Filtered Rendered VOM", res)
        self.plugin.service.render_page.assert_called_once()
        call_kwargs = self.plugin.service.render_page.call_args[1]
        self.assertEqual(call_kwargs.get("query"), "gtnh")
        self.assertEqual(call_kwargs.get("offset"), 10)
        self.assertEqual(call_kwargs.get("limit"), 20)
        self.assertEqual(call_kwargs.get("view"), "elements")


if __name__ == "__main__":
    unittest.main()
