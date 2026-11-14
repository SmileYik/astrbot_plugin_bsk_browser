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
        self.assertIn("优先主动调用 bsk_session(action='sync')", res)


if __name__ == "__main__":
    unittest.main()
