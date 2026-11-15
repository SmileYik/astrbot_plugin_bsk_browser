from pathlib import Path

def test_skills_documents_exist_and_cover_required_guidance():
    base = Path(__file__).resolve().parent.parent / "skill"
    bsk_browser = base / "bsk-browser" / "SKILL.md"
    baidu = base / "browse-baidu.com" / "SKILL.md"
    bing = base / "browse-cn.bing.com" / "SKILL.md"
    
    for doc in (bsk_browser, baidu, bing):
        assert doc.exists(), f"Skill document missing: {doc}"
        content = doc.read_text(encoding="utf-8")
        assert len(content) > 100
        
    # bsk-browser 必须包含 tab_close / bsk_tabs / screenshot 等指引与关闭生命周期
    bsk_content = bsk_browser.read_text(encoding="utf-8")
    assert "bsk_tabs" in bsk_content
    assert "close" in bsk_content
    assert "full_page" in bsk_content
    assert "新标签页" in bsk_content or "新标签" in bsk_content
    assert "压缩" in bsk_content
    
    # 百度和必应文档必须包含新标签页阅读与关闭指引
    for doc in (baidu, bing):
        text = doc.read_text(encoding="utf-8")
        assert "标签页" in text or "tab" in text.lower()
        assert "关闭" in text
        assert "bsk_tabs" in text
