import unittest
from astrbot_plugin_bsk_browser.bsk.models import PageObservation


class TestPageObservationModel(unittest.TestCase):
    def test_observation_id_extracted_from_top_level(self) -> None:
        raw = {"observation_id": "uuid-obs-1", "tab_id": 1, "text": "hello"}
        obs = PageObservation.from_json(raw)
        self.assertEqual(obs.observation_id, "uuid-obs-1")

    def test_observation_id_extracted_from_obs_alias(self) -> None:
        raw = {"obs": "o15", "tab_id": 1, "text": "hello"}
        obs = PageObservation.from_json(raw)
        self.assertEqual(obs.observation_id, "o15")

    def test_observation_id_extracted_from_nested_dict(self) -> None:
        raw = {
            "observation": {"observation_id": "uuid-obs-2"},
            "tab_id": 1,
            "text": "hello",
        }
        obs = PageObservation.from_json(raw)
        self.assertEqual(obs.observation_id, "uuid-obs-2")

    def test_observation_id_defaults_to_empty(self) -> None:
        raw = {"tab_id": 1, "text": "hello"}
        obs = PageObservation.from_json(raw)
        self.assertEqual(obs.observation_id, "")
