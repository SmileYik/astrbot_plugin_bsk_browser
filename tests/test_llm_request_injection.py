import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("ASTRBOT_ROOT", os.path.join(os.path.expanduser("~"), ".astrbot"))

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))
if str(_ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tests"))

from astrbot_test_doubles import FakeEvent, ensure_astrbot_modules, make_context

ensure_astrbot_modules()

from astrbot.api.provider import ProviderRequest
from astrbot_plugin_bsk_browser.main import BskBrowserPlugin


class TestLlmRequestInjection(unittest.IsolatedAsyncioTestCase):
    async def test_no_injection_when_prompt_empty(self) -> None:
        plugin = BskBrowserPlugin(
            make_context(),
            config={"admin_only": True, "llm_prompt_injection": ""},
        )
        req = ProviderRequest(system_prompt="base prompt")
        event = FakeEvent(is_admin=True)
        await plugin.on_llm_request(event, req)
        self.assertEqual(req.system_prompt, "base prompt")

    async def test_no_injection_when_prompt_is_whitespace(self) -> None:
        plugin = BskBrowserPlugin(
            make_context(),
            config={"admin_only": True, "llm_prompt_injection": "   \n  "},
        )
        req = ProviderRequest(system_prompt="base prompt")
        event = FakeEvent(is_admin=True)
        await plugin.on_llm_request(event, req)
        self.assertEqual(req.system_prompt, "base prompt")

    async def test_no_injection_when_plugin_disabled(self) -> None:
        plugin = BskBrowserPlugin(
            make_context(),
            config={"enabled": False, "llm_prompt_injection": "注入提示词"},
        )
        req = ProviderRequest(system_prompt="base prompt")
        event = FakeEvent(is_admin=True)
        await plugin.on_llm_request(event, req)
        self.assertEqual(req.system_prompt, "base prompt")

    async def test_no_injection_when_unauthorized_user(self) -> None:
        plugin = BskBrowserPlugin(
            make_context(),
            config={
                "admin_only": True,
                "allowed_users": ["admin_id"],
                "llm_prompt_injection": "注入提示词",
            },
        )
        req = ProviderRequest(system_prompt="base prompt")
        event = FakeEvent(is_admin=False, sender_id="guest_id")
        await plugin.on_llm_request(event, req)
        self.assertEqual(req.system_prompt, "base prompt")

    async def test_injection_appends_to_existing_system_prompt_for_admin(self) -> None:
        plugin = BskBrowserPlugin(
            make_context(),
            config={
                "admin_only": True,
                "llm_prompt_injection": "请优先使用浏览器搜索",
            },
        )
        req = ProviderRequest(system_prompt="原有人设提示词")
        event = FakeEvent(is_admin=True)
        await plugin.on_llm_request(event, req)
        self.assertEqual(req.system_prompt, "原有人设提示词\n\n请优先使用浏览器搜索")

    async def test_injection_sets_system_prompt_when_previously_empty(self) -> None:
        plugin = BskBrowserPlugin(
            make_context(),
            config={
                "admin_only": True,
                "llm_prompt_injection": "请优先使用浏览器搜索",
            },
        )
        req = ProviderRequest(system_prompt="")
        event = FakeEvent(is_admin=True)
        await plugin.on_llm_request(event, req)
        self.assertEqual(req.system_prompt, "请优先使用浏览器搜索")

    async def test_injection_for_allowed_whitelist_user(self) -> None:
        plugin = BskBrowserPlugin(
            make_context(),
            config={
                "admin_only": True,
                "allowed_users": ["user_white"],
                "llm_prompt_injection": "白名单提示词",
            },
        )
        req = ProviderRequest(system_prompt="")
        event = FakeEvent(is_admin=False, sender_id="user_white")
        await plugin.on_llm_request(event, req)
        self.assertEqual(req.system_prompt, "白名单提示词")


if __name__ == "__main__":
    unittest.main()
