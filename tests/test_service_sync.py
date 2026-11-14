import unittest
from unittest.mock import AsyncMock, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bsk.service import BskService
from bsk.models import PageObservation


class TestServiceSync(unittest.IsolatedAsyncioTestCase):
    async def test_sync_session_calls_bsk_sync(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._with_tab_id = lambda args, tid: args + (["--tab-id", str(tid)] if tid else [])
        service._timeout = lambda builtin: builtin
        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(
            return_value=MagicMock(data={"vom": "@vom 1\n@view 800x600\nRootWebArea \"Test\"\n@e1 button \"OK\"", "tab_id": 1})
        )

        obs = await service.sync_session("s1", tab_id=1, wait_for="Test", timeout_ms=3000)
        self.assertIsInstance(obs, PageObservation)
        self.assertEqual(obs.title, "Test")
        self.assertEqual(len(obs.refs), 1)
        self.assertEqual(obs.refs[0].name, "OK")

        service.sessions.execute.assert_called_once()
        call_args = service.sessions.execute.call_args
        self.assertEqual(call_args[0][0], "s1")
        builder = call_args[0][1]
        argv = builder("s1")
        self.assertEqual(argv[0], "sync")
        self.assertIn("--wait-for", argv)
        self.assertIn("Test", argv)
        self.assertIn("--timeout-ms", argv)
        self.assertIn("3000", argv)
        self.assertIn("--tab-id", argv)
        self.assertIn("1", argv)

    async def test_open_session_calls_bsk_open(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._timeout = lambda builtin: builtin
        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(
            return_value=MagicMock(data={"vom": "@vom 1\n@view 800x600\nRootWebArea \"Open Test\"\n@e1 link \"Home\"", "tab_id": 1})
        )

        obs = await service.open_session("s1", "https://example.com", timeout_ms=5000)
        self.assertIsInstance(obs, PageObservation)
        self.assertEqual(obs.title, "Open Test")
        self.assertEqual(len(obs.refs), 1)

        service.sessions.execute.assert_called_once()
        builder = service.sessions.execute.call_args[0][1]
        argv = builder("s1")
        self.assertEqual(argv[0], "open")
        self.assertEqual(argv[1], "https://example.com")
        self.assertIn("--timeout-ms", argv)
        self.assertIn("5000", argv)


if __name__ == "__main__":
    unittest.main()
