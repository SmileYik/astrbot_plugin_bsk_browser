import unittest
from unittest.mock import AsyncMock, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from astrbot_plugin_bsk_browser.bsk.cli import BskCli
    from astrbot_plugin_bsk_browser.bsk.models import BskResult
except ImportError:
    from bsk.cli import BskCli
    from bsk.models import BskResult


class TestInteractArgsBuilding(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.runner = MagicMock()
        self.runner.run = AsyncMock(return_value=BskResult(ok=True, exit_code=0, stdout="", stderr="", data={}))
        self.cli = BskCli(self.runner)

    async def test_wheel_with_observation_id(self) -> None:
        await self.cli.interact("sess1", "wheel", delta_x=0, delta_y=500, observation_id="uuid-obs-1")
        call_args = self.runner.run.call_args[0][0]
        self.assertIn("--observation", call_args)
        idx = call_args.index("--observation")
        self.assertEqual(call_args[idx + 1], "uuid-obs-1")
        self.assertIn("--delta-y", call_args)

    async def test_wheel_with_target_and_no_observation(self) -> None:
        await self.cli.interact("sess1", "wheel", target="@e1", delta_x=0, delta_y=500)
        call_args = self.runner.run.call_args[0][0]
        self.assertEqual(call_args[0], "wheel")
        self.assertEqual(call_args[1], "@e1")
        self.assertNotIn("--observation", call_args)

    async def test_press_with_observation_id(self) -> None:
        await self.cli.interact("sess1", "press", key="Enter", observation_id="uuid-obs-2")
        call_args = self.runner.run.call_args[0][0]
        self.assertEqual(call_args[0], "press")
        self.assertEqual(call_args[1], "Enter")
        self.assertIn("--observation", call_args)
        idx = call_args.index("--observation")
        self.assertEqual(call_args[idx + 1], "uuid-obs-2")
