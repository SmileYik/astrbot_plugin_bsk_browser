import unittest
from pathlib import Path


class TestSkillsDoc(unittest.TestCase):
    def test_skills_documents_exist_and_cover_required_guidance(self):
        base = Path(__file__).resolve().parent.parent / "skill"
        bsk_browser = base / "bsk-browser" / "SKILL.md"
        baidu = base / "browse-baidu.com" / "SKILL.md"
        bing = base / "browse-cn.bing.com" / "SKILL.md"
        
        for doc in (bsk_browser, baidu, bing):
            self.assertTrue(doc.exists(), f"Skill document missing: {doc}")
            content = doc.read_text(encoding="utf-8")
            self.assertGreater(len(content), 100)
            
        # bsk-browser 必须包含 tab_close / bsk_tabs / screenshot 等指引与关闭生命周期
        bsk_content = bsk_browser.read_text(encoding="utf-8")
        self.assertIn("bsk_tabs", bsk_content)
        self.assertIn("close", bsk_content)
        self.assertIn("full_page", bsk_content)
        self.assertTrue("新标签页" in bsk_content or "新标签" in bsk_content)
        self.assertIn("压缩", bsk_content)
        self.assertIn("bsk_status", bsk_content)
        for removed in ("bsk_close", "bsk_logs", "bsk_open", "bsk_read", "bsk_act"):
            self.assertNotIn(removed, bsk_content, f"{removed} should not be in bsk-browser/SKILL.md")
        
        # 百度和必应文档必须包含新标签页阅读与关闭指引
        for doc in (baidu, bing):
            text = doc.read_text(encoding="utf-8")
            self.assertTrue("标签页" in text or "tab" in text.lower())
            self.assertIn("关闭", text)
            self.assertIn("bsk_tabs", text)


if __name__ == "__main__":
    unittest.main()
