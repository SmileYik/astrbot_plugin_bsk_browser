import unittest
from pathlib import Path


class TestSkillsDoc(unittest.TestCase):
    def test_skills_documents_exist_and_cover_required_guidance(self):
        base = Path(__file__).resolve().parent.parent / "skills"
        bsk_browser = base / "bsk-browser" / "SKILL.md"
        baidu = base / "bsk-browse-baidu" / "SKILL.md"
        bing = base / "bsk-browse-bingcn" / "SKILL.md"
        
        self.assertFalse((base / "bsk-browse-baidu.com").exists())
        self.assertFalse((base / "bsk-browse-cn.bing.com").exists())
        for doc in (bsk_browser, baidu, bing):
            self.assertTrue(doc.exists(), f"Skill document missing: {doc}")
            content = doc.read_text(encoding="utf-8")
            self.assertGreater(len(content), 100)
            self.assertIn(f"name: {doc.parent.name}", content, f"Skill {doc} must declare name: {doc.parent.name}")
            
        # bsk-browser 必须包含 tab_close / bsk_tabs / screenshot 等指引与关闭生命周期
        bsk_content = bsk_browser.read_text(encoding="utf-8")
        self.assertIn("bsk_tabs", bsk_content)
        self.assertIn("close", bsk_content)
        self.assertIn("full_page", bsk_content)
        self.assertTrue("新标签页" in bsk_content or "新标签" in bsk_content)
        self.assertIn("bsk_status", bsk_content)
        for removed in ("bsk_close", "bsk_logs", "bsk_open", "bsk_read", "bsk_act"):
            self.assertNotIn(removed, bsk_content, f"{removed} should not be in bsk-browser/SKILL.md")

        # 后台配置项不得暴露在 SKILL 文档中
        for doc in (bsk_browser, baidu, bing):
            text = doc.read_text(encoding="utf-8")
            for forbidden in (
                "screenshot_compress_to_jpg",
                "screenshot_quality",
                "fullpage_max_height",
                "fullpage_scope",
                "site_whitelist",
                "allowed_actions",
            ):
                self.assertNotIn(forbidden, text, f"{forbidden} should not be exposed in {doc.name}")
        
        # 百度和必应文档必须包含新标签页阅读与关闭指引
        for doc in (baidu, bing):
            text = doc.read_text(encoding="utf-8")
            self.assertTrue("标签页" in text or "tab" in text.lower())
            self.assertIn("关闭", text)
            self.assertIn("bsk_tabs", text)


if __name__ == "__main__":
    unittest.main()
