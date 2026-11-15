import unittest
from bsk.permissions import (
    check_site_permission,
    is_action_allowed,
    is_domain_match,
    normalize_domain,
)


class TestSitePermissions(unittest.TestCase):
    def test_normalize_domain(self) -> None:
        self.assertEqual(normalize_domain("https://www.baidu.com/s?wd=test"), "baidu.com")
        self.assertEqual(normalize_domain("http://tieba.baidu.com:8080/f"), "tieba.baidu.com")
        self.assertEqual(normalize_domain("cn.bing.com"), "cn.bing.com")
        self.assertEqual(normalize_domain("https://bilibili.com/video/BV123"), "bilibili.com")
        self.assertEqual(normalize_domain("localhost:8000"), "localhost")
        self.assertEqual(normalize_domain(""), "")

    def test_domain_match(self) -> None:
        self.assertTrue(is_domain_match("baidu.com", "baidu.com"))
        self.assertTrue(is_domain_match("baidu.com", "www.baidu.com"))
        self.assertTrue(is_domain_match("baidu.com", "tieba.baidu.com"))
        self.assertFalse(is_domain_match("baidu.com", "notbaidu.com"))
        self.assertFalse(is_domain_match("baidu.com", "baidu.com.cn"))
        self.assertTrue(is_domain_match("cn.bing.com", "cn.bing.com"))
        self.assertFalse(is_domain_match("cn.bing.com", "bing.com"))

    def test_action_allowed(self) -> None:
        self.assertTrue(is_action_allowed(["click", "fill"], "bsk_interact", "click"))
        self.assertTrue(is_action_allowed(["bsk_interact.click"], "bsk_interact", "click"))
        self.assertTrue(is_action_allowed(["bsk_interact.*"], "bsk_interact", "fill"))
        self.assertTrue(is_action_allowed(["*"], "bsk_inspect", "observe"))
        self.assertFalse(is_action_allowed(["click"], "bsk_inspect", "screenshot"))
        self.assertFalse(is_action_allowed(["bsk_page.navigate"], "bsk_interact", "click"))

    def test_check_site_permission_navigation_implied(self) -> None:
        rules = [{"domain": "baidu.com", "allowed_actions": ["click", "fill"]}]
        ok, reason = check_site_permission(rules, "https://www.baidu.com", "bsk_page", "navigate")
        self.assertTrue(ok)
        self.assertEqual(reason, "")

        ok2, reason2 = check_site_permission(rules, "https://www.baidu.com", "bsk_session", "open")
        self.assertTrue(ok2)
        self.assertEqual(reason2, "")

    def test_check_site_permission_in_page_disallowed(self) -> None:
        rules = [{"domain": "baidu.com", "allowed_actions": ["click", "fill"]}]
        ok, reason = check_site_permission(rules, "https://www.baidu.com", "bsk_inspect", "screenshot")
        self.assertFalse(ok)
        self.assertIn("未向普通用户开放", reason)

    def test_check_site_permission_domain_not_in_whitelist(self) -> None:
        rules = [{"domain": "baidu.com", "allowed_actions": ["click", "fill"]}]
        ok, reason = check_site_permission(rules, "https://evil.com/login", "bsk_page", "navigate")
        self.assertFalse(ok)
        self.assertIn("不在允许访问的白名单中", reason)

    def test_check_site_permission_empty_url(self) -> None:
        rules = [{"domain": "baidu.com", "allowed_actions": ["click", "fill"]}]
        ok, reason = check_site_permission(rules, "", "bsk_interact", "click")
        self.assertFalse(ok)
        self.assertIn("尚未打开任何网页", reason)


class TestServiceActiveUrl(unittest.IsolatedAsyncioTestCase):
    async def test_set_and_get_active_url(self) -> None:
        from unittest.mock import MagicMock
        from bsk.service import BskService

        service = BskService(settings=MagicMock(), runner=MagicMock())
        service.set_active_url("s1", "https://www.baidu.com")
        url = await service.get_active_url("s1")
        self.assertEqual(url, "https://www.baidu.com")

    async def test_dirty_url_refreshes_from_tab_list(self) -> None:
        from unittest.mock import AsyncMock, MagicMock
        from bsk.service import BskService

        service = BskService(settings=MagicMock(), runner=MagicMock())
        service.set_active_url("s1", "https://www.baidu.com")
        service.mark_url_dirty("s1")

        service.tab_list = AsyncMock(
            return_value=[
                {"tab_id": 1, "active": True, "url": "https://cn.bing.com"}
            ]
        )
        url = await service.get_active_url("s1")
        self.assertEqual(url, "https://cn.bing.com")


if __name__ == "__main__":
    unittest.main()

