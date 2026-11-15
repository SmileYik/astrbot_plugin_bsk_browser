import dataclasses
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))
if str(_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tests"))

from astrbot_test_doubles import ensure_astrbot_modules, make_context, FakeEvent

ensure_astrbot_modules()

from astrbot_plugin_bsk_browser.main import BskBrowserPlugin
from astrbot_plugin_bsk_browser.bsk.models import PageObservation
from astrbot_plugin_bsk_browser.bsk.service import ShotPayload
from astrbot_plugin_bsk_browser.bsk.errors import BskError


class TestInspectScreenshotImage(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.plugin = BskBrowserPlugin(make_context(), config={"admin_only": False})
        self.plugin.service = MagicMock()
        self.event = FakeEvent(is_admin=True, umo="test:user:1")
        self.event.image_result = MagicMock(side_effect=lambda path: f"[IMAGE:{path}]")

    async def test_inspect_screenshot_yields_image(self) -> None:
        payload = ShotPayload(
            path="/tmp/test_shot.png",
            for_llm="当前页面视口截图完成，尺寸 1280x800",
            byte_size=2048,
            warning="",
        )
        self.plugin.service.screenshot_ex = AsyncMock(return_value=payload)

        gen = self.plugin.bsk_inspect(self.event, action="screenshot", full_page=True)
        items = [item async for item in gen]

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0], "[IMAGE:/tmp/test_shot.png]")
        self.plugin.service.screenshot_ex.assert_called_once()
        call_kwargs = self.plugin.service.screenshot_ex.call_args[1]
        self.assertTrue(call_kwargs.get("full_page"))

    async def test_inspect_screenshot_default_full_page_false(self) -> None:
        payload = ShotPayload(
            path="/tmp/test_shot.png",
            for_llm="视口截图完成",
            byte_size=2048,
            warning="",
        )
        self.plugin.service.screenshot_ex = AsyncMock(return_value=payload)

        gen = self.plugin.bsk_inspect(self.event, action="screenshot")
        items = [item async for item in gen]

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0], "[IMAGE:/tmp/test_shot.png]")
        call_kwargs = self.plugin.service.screenshot_ex.call_args[1]
        self.assertFalse(call_kwargs.get("full_page"))

    async def test_inspect_screenshot_image_fail_degrades_gracefully(self) -> None:
        payload = ShotPayload(
            path="/tmp/test_shot.png",
            for_llm="视口截图完成",
            byte_size=2048,
            warning="",
        )
        self.plugin.service.screenshot_ex = AsyncMock(return_value=payload)
        self.event.image_result.side_effect = RuntimeError("Upload error")

        gen = self.plugin.bsk_inspect(self.event, action="screenshot")
        items = [item async for item in gen]

        self.assertEqual(len(items), 1)
        self.assertIn("图片发送失败了，截图文件在：/tmp/test_shot.png", items[0])

    async def test_inspect_observe_yields_text_only(self) -> None:
        obs = PageObservation(text="Page content", title="Title")
        self.plugin.service.observe = AsyncMock(return_value=obs)
        self.plugin.service.render_page = MagicMock(return_value="Rendered VOM")

        gen = self.plugin.bsk_inspect(self.event, action="observe")
        items = [item async for item in gen]

        self.assertEqual(len(items), 1)
        self.assertIn("Rendered VOM", items[0])
        self.event.image_result.assert_not_called()

    async def test_inspect_permission_denied(self) -> None:
        self.plugin.settings = dataclasses.replace(self.plugin.settings, enabled=False)

        gen = self.plugin.bsk_inspect(self.event, action="screenshot")
        items = [item async for item in gen]

        self.assertEqual(len(items), 1)
        self.assertIn("已在插件配置中停用", items[0])


    async def test_make_shot_path_returns_absolute_path(self) -> None:
        from astrbot_plugin_bsk_browser.bsk.shots import make_shot_path
        import tempfile
        import os
        orig_cwd = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp_dir:
            os.chdir(tmp_dir)
            try:
                p = make_shot_path("relative_subdir", "test_session_1")
                self.assertTrue(p.is_absolute())
                self.assertTrue(str(p).startswith(tmp_dir))
            finally:
                os.chdir(orig_cwd)


if __name__ == "__main__":
    unittest.main()
