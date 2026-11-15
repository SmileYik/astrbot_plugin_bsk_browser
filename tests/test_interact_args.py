import unittest
from astrbot_plugin_bsk_browser.bsk.service import BskService


class TestInteractArgsBuilding(unittest.TestCase):
    def test_wheel_with_observation_id(self) -> None:
        argv, readonly = BskService._build_interact_args(
            "wheel", {"delta_x": 0, "delta_y": 500, "observation_id": "uuid-obs-1"}
        )
        self.assertTrue(readonly)
        self.assertIn("--observation", argv)
        idx = argv.index("--observation")
        self.assertEqual(argv[idx + 1], "uuid-obs-1")
        self.assertIn("--delta-y", argv)

    def test_wheel_with_target_and_no_observation(self) -> None:
        argv, readonly = BskService._build_interact_args(
            "wheel", {"target": "@e1", "delta_x": 0, "delta_y": 500}
        )
        self.assertTrue(readonly)
        self.assertEqual(argv[0], "wheel")
        self.assertEqual(argv[1], "@e1")
        self.assertNotIn("--observation", argv)

    def test_press_with_observation_id(self) -> None:
        argv, readonly = BskService._build_interact_args(
            "press", {"key": "Enter", "observation_id": "uuid-obs-2"}
        )
        self.assertFalse(readonly)
        self.assertEqual(argv[0], "press")
        self.assertEqual(argv[1], "Enter")
        self.assertIn("--observation", argv)
        idx = argv.index("--observation")
        self.assertEqual(argv[idx + 1], "uuid-obs-2")
