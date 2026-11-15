# 标签页生命周期全自动接管与自主管理、滚动/长截屏自愈与图片压缩防爆实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现浏览器新标签页自动感知、焦点接管与生命周期彻底清理，修复 `observation_changed` 导致的滚动与长截屏中断，并引入长图智能压缩流水线以杜绝 QQ 客户端空白破图。

**Architecture:** 
1. 在 `bsk/shots.py` 中引入智能图片压缩流水线，将原始超大 PNG（长截图）转为高画质受控体积的 JPEG（< 1.5MB），安全通过 WebSocket 发送；
2. 在 `bsk/service.py` 的交互与全页截图中，交互后废弃陈旧 observation 缓存，并将 `observation_changed` 纳入自愈重试白名单，实现自动 `sync_session` 刷新令牌并重试；
3. 在 `service.interact` 点击后执行 Tab Diffing，自动识别新打开的标签页、自动切换控制焦点（`tab select`），并在工具结果中明确提示机器人新 Tab 的 ID、标题与自主清理引导；
4. 在会话结束（`stop_session` / `teardown` / 回收）时，先主动遍历 Agent Window 下的所有 Tab 发送 `tab close`，彻底打破 BrowserSkill 的 `dropOnly: true` 保护机制，确保宿主机 0 残留；
5. 同步更新 `skill/bsk-browser`、`skill/browse-baidu.com`、`skill/browse-cn.bing.com` 文档。

**Tech Stack:** Python 3.12+, Pillow (PIL), asyncio, pytest, AstrBot Plugin Framework

**Spec:** [docs/superpowers/specs/2026-11-15-bsk-tab-lifecycle-and-resilience-design.md](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-bsk-tab-lifecycle-and-resilience-design.md)

## Global Constraints

- 仅修改 `astrbot_plugin_bsk_browser/` 目录下的文件，外部 `BrowserSkill` 与 `./bsk` 仅作只读参考；
- 日志系统严格遵循 `AGENTS.md`：以 DEBUG 等级输出 bsk 命令输入输出与工具调用（会话、工具名）；
- 工具提示与 SKILL 文档必须在准确表达的基础上做到精炼简洁不啰嗦；
- 每次修改后维护 `skill/bsk-browser`、`skill/browse-baidu.com`、`skill/browse-cn.bing.com`；
- 每个 Task 实施完成后必须运行测试并执行 git commit。

## Review Focus

1. **多标签并发与异步竞态**：快速连续点击可能产生多个新 Tab，Tab Diffing 必须基于 Agent Window 的 ID 集合差集，保证不遗漏并选定最新 Tab。
2. **长截屏高宽异常值**：超长页面（如贴吧或长维基，页面高 > 20,000px）若按原尺寸压缩仍可能超出 2MB，必须具备自适应宽高与多级质量降级保护（85 -> 75 -> 65）。
3. **`observation_changed` 遇 `@eN` 目标失效**：若点击带目标 `@eN` 的元素因 DOM 变动触发 `observation_changed`，不能盲目重试原 `@eN`，必须触发 `sync_session` 并提示模型最新的元素大纲。
4. **会话终止时关闭自身唯一活动 Tab**：逐个关闭 Tab 时，关闭最后一个 Tab 可能触发浏览器直接关闭或返回 `session_already_stopped`，不能抛出未捕获异常打断清理流程。
5. **Pillow 缺失或异常安全回退**：若极端情况下运行环境 Pillow 不可用或读取图片损坏，必须平滑回退至原始路径，不能导致工具崩溃。

---

### Task 1: 图片智能自适应压缩流水线（Pillow 压缩 JPEG + 尺寸与大小智能钳位防爆）

**Files:**
- Create: `astrbot_plugin_bsk_browser/tests/test_shot_compression.py`
- Modify: `astrbot_plugin_bsk_browser/bsk/shots.py`
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py:3272-3350`
- Modify: `astrbot_plugin_bsk_browser/main.py:2000-2030,2270-2285`

**Interfaces:**
- Produces: `compress_and_optimize_image(path: Path | str, max_size_bytes: int = 1_500_000, max_width: int = 1920, quality: int = 85) -> Path`
- Consumes: Pillow `PIL.Image`, `ShotPayload`

- [ ] **Step 1: Write the failing tests for image compression**

```python
# astrbot_plugin_bsk_browser/tests/test_shot_compression.py
import pytest
from pathlib import Path
from PIL import Image
from bsk.shots import compress_and_optimize_image

def test_compress_normal_png(tmp_path: Path):
    # 创建一个 1920x1080 的纯色 RGBA PNG
    raw_png = tmp_path / "raw.png"
    img = Image.new("RGBA", (1920, 1080), (255, 0, 0, 255))
    img.save(raw_png, format="PNG")
    
    opt_path = compress_and_optimize_image(raw_png, max_size_bytes=1_500_000)
    assert opt_path.exists()
    assert opt_path.suffix.lower() in (".jpg", ".jpeg")
    assert opt_path.stat().st_size <= 1_500_000
    with Image.open(opt_path) as opt_img:
        assert opt_img.format == "JPEG"
        assert opt_img.size == (1920, 1080)

def test_compress_super_tall_long_screenshot(tmp_path: Path):
    # 创建一个 3840x12000 的超大超长模拟长截图
    raw_png = tmp_path / "super_tall.png"
    img = Image.new("RGB", (3840, 12000), (200, 200, 200))
    img.save(raw_png, format="PNG")
    
    opt_path = compress_and_optimize_image(raw_png, max_size_bytes=1_500_000, max_width=1920)
    assert opt_path.exists()
    assert opt_path.stat().st_size <= 1_500_000
    with Image.open(opt_path) as opt_img:
        assert opt_img.width <= 1920
        # 验证等比缩放
        assert opt_img.height == 6000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_shot_compression.py -v`  
Expected: FAIL with `ImportError: cannot import name 'compress_and_optimize_image' from 'bsk.shots'`

- [ ] **Step 3: Implement `compress_and_optimize_image` in `bsk/shots.py` and integrate into `service.py` & `main.py`**

In `astrbot_plugin_bsk_browser/bsk/shots.py`:
- 实现 `compress_and_optimize_image(path, max_size_bytes=1_500_000, max_width=1920, quality=85) -> Path`：
  - 处理 RGBA/P 等带透明度通道图片（创建白色背景底图 composited 为 RGB）；
  - 若宽度超过 `max_width`，按等比缩放（`Image.Resampling.LANCZOS`）；
  - 循环按质量（`85, 75, 65`）尝试编码至 JPEG；若达标立即写入并返回新文件路径 `<orig_stem>_opt.jpg`；
  - 带有 Pillow 缺失防护（无 Pillow 时记录 warning 并安全返回原路径）。
In `astrbot_plugin_bsk_browser/bsk/service.py`:
- 在 `screenshot_ex` 执行完 `bsk screenshot` 生成图片后，调用 `compress_and_optimize_image(out_path)`，将 `ShotPayload.path` 指向优化后的图片路径，并更新 `ShotPayload.byte_size`。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_shot_compression.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add astrbot_plugin_bsk_browser/bsk/shots.py astrbot_plugin_bsk_browser/bsk/service.py astrbot_plugin_bsk_browser/main.py astrbot_plugin_bsk_browser/tests/test_shot_compression.py
git commit -m "feat: implement image compression pipeline for screenshots and long captures"
```

---

### Task 2: 交互操作后令牌失效清理与 `observation_changed` 完整自愈

**Files:**
- Create: `astrbot_plugin_bsk_browser/tests/test_observation_resilience.py`
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py:2660-2740,3320-3350`

**Interfaces:**
- Consumes: `BskService.sync_session`, `BskService.interact`, `BskService.screenshot_ex`
- Produces: 自动捕获 `observation_changed` 并在后台自愈，不把底层策略报错直接暴露给模型

- [ ] **Step 1: Write the failing tests for observation resilience**

```python
# astrbot_plugin_bsk_browser/tests/test_observation_resilience.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from bsk.service import BskService
from bsk.errors import BskError, BskUserError
from bsk.types import SessionContext

@pytest.mark.asyncio
async def test_wheel_auto_recovers_from_observation_changed():
    service = BskService(settings=MagicMock())
    service.sessions = MagicMock()
    service._resolve_key = MagicMock(return_value="test_session")
    service._timeout = MagicMock(return_value=30.0)
    service._interact_timeout_builtin = MagicMock(return_value=30.0)
    service._session_observations["test_session"] = "stale_obs_token"
    
    # 模拟第一次执行 wheel 抛出 observation_changed，重试后成功
    err = BskError("changed", reason="observation_changed", effect_state="none")
    success_result = MagicMock(data={"delta_y": 2000})
    service.sessions.execute = AsyncMock(side_effect=[err, success_result])
    
    new_obs = SessionContext(
        context_id="ctx1", ctx="c1", observation_id="new_obs_token",
        obs="o1", session_id="test_session", tab_id=101, title="Test",
        url="http://test", unchanged=False, vom=""
    )
    service.sync_session = AsyncMock(return_value=new_obs)
    
    result = await service.interact("test_session", "wheel", delta_y=2000)
    assert result == {"delta_y": 2000}
    assert service.sync_session.called
    assert service.sessions.execute.call_count == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_observation_resilience.py -v`  
Expected: FAIL (because `observation_changed` is not caught in `service.interact`, raising `BskError`)

- [ ] **Step 3: Implement observation invalidation & `observation_changed` recovery in `service.py`**

In `astrbot_plugin_bsk_browser/bsk/service.py`:
1. 在 `interact` 的异常捕获中，将条件改为：
   ```python
   if reason in ("cooperation_sync_required", "observation_required", "control_context_invalid", "observation_changed") and effect_state != "unknown":
   ```
2. 当 `action in ("wheel", "press") and not target` 时，使用 `obs.observation_id` 注入并重新构造 `argv`，自动重试 `_run_action()`；
3. 在 `_run_action()` 成功后，若操作是写类操作（`click`, `fill`, `press`, `select`），立即 `self._session_observations.pop(session_key, None)`，废除陈旧令牌；
4. 在 `screenshot_ex`（全页截图）遇到 `observation_changed` 时，同样自动执行 `sync_session` 刷新 observation ID 并自动重试截图。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_observation_resilience.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add astrbot_plugin_bsk_browser/bsk/service.py astrbot_plugin_bsk_browser/tests/test_observation_resilience.py
git commit -m "fix: auto-recover from observation_changed on wheel and full-page screenshot"
```

---

### Task 3: 新 Tab 自动检测、焦点自动接管与机器人感知通知

**Files:**
- Create: `astrbot_plugin_bsk_browser/tests/test_tab_detection.py`
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py`
- Modify: `astrbot_plugin_bsk_browser/main.py:1710-1760`

**Interfaces:**
- Produces: `service._detect_new_tabs_and_switch(session_key: str) -> dict[str, Any] | None`
- Consumes: `bsk tab list --scope agent`, `bsk tab select <tab_id>`

- [ ] **Step 1: Write the failing tests for new tab detection and auto-switch**

```python
# astrbot_plugin_bsk_browser/tests/test_tab_detection.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bsk.service import BskService

@pytest.mark.asyncio
async def test_detect_new_tab_and_auto_select():
    service = BskService(settings=MagicMock())
    service.sessions = MagicMock()
    service._resolve_key = MagicMock(return_value="sess_1")
    service._session_known_tabs["sess_1"] = {101}
    
    # 模拟 tab list 返回出现了新 tab 102
    tabs_data = {
        "tabs": [
            {"tab_id": 101, "title": "Baidu Search", "url": "https://www.baidu.com"},
            {"tab_id": 102, "title": "GTNH Baidu Tieba", "url": "https://tieba.baidu.com/p/123"}
        ]
    }
    service.tabs = AsyncMock(return_value=tabs_data)
    
    info = await service.detect_new_tabs_and_switch("sess_1")
    assert info is not None
    assert info["new_tab_id"] == 102
    assert info["title"] == "GTNH Baidu Tieba"
    assert info["url"] == "https://tieba.baidu.com/p/123"
    assert 102 in service._session_known_tabs["sess_1"]
    # 验证自动调用了 tab select 102
    service.tabs.assert_any_call("sess_1", "select", tab_id=102)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_tab_detection.py -v`  
Expected: FAIL with `AttributeError: 'BskService' object has no attribute 'detect_new_tabs_and_switch'`

- [ ] **Step 3: Implement `detect_new_tabs_and_switch` in `service.py` and hook into `interact` & `main.py`**

In `astrbot_plugin_bsk_browser/bsk/service.py`:
- 增加属性 `self._session_known_tabs: dict[str, set[int]] = {}`；
- 实现 `async def detect_new_tabs_and_switch(self, key: str) -> dict[str, Any] | None`：
  - 调用 `await self.tabs(key, "list", scope="agent")`；
  - 提取当前所有 tab ID 集合；
  - 与 `self._session_known_tabs[key]` 取差集；
  - 若存在新 tab：选择最新的 tab 执行 `await self.tabs(key, "select", tab_id=new_id)`，并将新 tab 记录到集合中，返回包含 `new_tab_id`, `title`, `url`, `total_tabs` 的字典；
- 在 `service.interact(action="click", ...)` 成功后调用 `detect_new_tabs_and_switch`，将结果附加在返回字典 `result["new_tab_info"]` 中；
In `astrbot_plugin_bsk_browser/main.py`:
- 在 `_run_interact` 的回执文本格式化中，若发现 `new_tab_info`：
  - 追加渲染包含【检测到新标签页】、【焦点已自动切换】、【自主清理提示】的指引段落。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_tab_detection.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add astrbot_plugin_bsk_browser/bsk/service.py astrbot_plugin_bsk_browser/main.py astrbot_plugin_bsk_browser/tests/test_tab_detection.py
git commit -m "feat: auto-detect newly opened tabs, switch focus, and inform model"
```

---

### Task 4: 标签页主动管理强化与会话终止/回收彻底扫尾（宿主机 0 残留）

**Files:**
- Create: `astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py`
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py:1260-1285,2960-3030`
- Modify: `astrbot_plugin_bsk_browser/main.py:1775-1840`

**Interfaces:**
- Produces: `service.sweep_agent_tabs(key: str) -> None`
- Consumes: `service.tabs(action="close")`, `service.stop_session`

- [ ] **Step 1: Write the failing tests for tab lifecycle cleanup**

```python
# astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from bsk.service import BskService

@pytest.mark.asyncio
async def test_stop_session_sweeps_all_agent_tabs_before_stopping():
    service = BskService(settings=MagicMock())
    service.sessions = MagicMock()
    service._resolve_key = MagicMock(return_value="test_sess")
    
    # 模拟当前 Agent Window 存在两个残留 Tab: 101, 102
    tabs_data = {
        "tabs": [
            {"tab_id": 101, "title": "Main Page"},
            {"tab_id": 102, "title": "Popup Tab"}
        ]
    }
    service.tabs = AsyncMock(return_value=tabs_data)
    service.sessions.stop = AsyncMock()
    
    await service.stop_session("test_sess")
    
    # 验证主动关闭了残留的标签页
    service.tabs.assert_any_call("test_sess", "close", tab_id=102)
    assert service.sessions.stop.called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py -v`  
Expected: FAIL (because `stop_session` currently only calls `sessions.stop`, without sweeping tabs)

- [ ] **Step 3: Implement `sweep_agent_tabs` and integrate into `stop_session` and `tabs(action="close")`**

In `astrbot_plugin_bsk_browser/bsk/service.py`:
- 实现 `async def sweep_agent_tabs(self, key: str) -> None`：
  - 查询当前会话的 `tab list --scope agent`；
  - 遍历所有非最后一个 tab（或所有弹出的 popup tabs）执行 `tab close <tab_id>`（安全捕获异常）；
- 在 `stop_session(key)` 及 `teardown()` 中，调用 `session stop` 之前先调用 `await self.sweep_agent_tabs(key)`；
- 在 `tabs(action="close")` 中：
  - 关闭指定标签页后，从 `_session_known_tabs` 移除该 ID；
  - 若还剩其它标签页，自动切换焦点至前一个标签页，并在返回信息中告知机器人当前已切回的标签页 ID 与标题。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add astrbot_plugin_bsk_browser/bsk/service.py astrbot_plugin_bsk_browser/main.py astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py
git commit -m "feat: sweep all agent tabs upon session stop to guarantee zero host leakage"
```

---

### Task 5: 更新三份 SKILL 文档并验证端到端一致性

**Files:**
- Create: `astrbot_plugin_bsk_browser/tests/test_skills_doc.py`
- Modify: `astrbot_plugin_bsk_browser/skill/bsk-browser/SKILL.md`
- Modify: `astrbot_plugin_bsk_browser/skill/browse-baidu.com/SKILL.md`
- Modify: `astrbot_plugin_bsk_browser/skill/browse-cn.bing.com/SKILL.md`

**Interfaces:**
- SKILL 文档必须符合 `AGENTS.md` 规范：准确、精炼简洁、指导模型外链阅读与关闭、长截图与滚动技巧。

- [ ] **Step 1: Write the test verifying skill documentation consistency**

```python
# astrbot_plugin_bsk_browser/tests/test_skills_doc.py
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
        
    # bsk-browser 必须包含 tab_close / bsk_tabs / screenshot 等指引
    bsk_content = bsk_browser.read_text(encoding="utf-8")
    assert "bsk_tabs" in bsk_content
    assert "close" in bsk_content
    assert "full_page" in bsk_content
    
    # 百度和必应文档必须包含新标签页阅读与关闭指引
    for doc in (baidu, bing):
        text = doc.read_text(encoding="utf-8")
        assert "标签页" in text or "tab" in text.lower()
        assert "关闭" in text
```

- [ ] **Step 2: Run test to verify current state**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_skills_doc.py -v`  
Expected: May FAIL if specific keywords or guidance are absent.

- [ ] **Step 3: Update `SKILL.md` for `bsk-browser`, `browse-baidu.com`, `browse-cn.bing.com`**

- `bsk-browser/SKILL.md`：
  - 更新标签页管理章节：明确外链点击会触发新 Tab 并自动切焦，阅读完毕后必须调用 `bsk_tabs(action="close", tab_id=...)` 关闭它；
  - 阐明长截图 `bsk_inspect(action="screenshot", full_page=True)` 具备自动压缩，可放心截取长页；
  - 阐明滚动建议：无目标 `wheel` 必须明确滚动方向，且如需定位元素优先使用 `scroll_to`。
- `browse-baidu.com/SKILL.md` & `browse-cn.bing.com/SKILL.md`：
  - 精炼更新搜索与结果阅读标准流程：
    1. 搜索与大纲浏览；
    2. 点击条目进入外链（注意新 Tab 自动切焦）；
    3. 浏览外链内容；
    4. 执行 `bsk_tabs(action="close")` 关闭该 Tab 自动返回搜索结果页；
    5. 翻页（下一页按钮）或继续浏览其他结果。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_skills_doc.py -v`  
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add astrbot_plugin_bsk_browser/skill/ astrbot_plugin_bsk_browser/tests/test_skills_doc.py
git commit -m "docs(skill): update bsk-browser, baidu, and bing skills for tab lifecycle and capture"
```

---

### Task 6: 全量回归测试与收尾验证

**Files:**
- Test: All tests under `astrbot_plugin_bsk_browser/tests/`

- [ ] **Step 1: Run full test suite**

Run: `pytest astrbot_plugin_bsk_browser/tests/ -v`  
Expected: All tests PASS.

- [ ] **Step 2: Verify git status and commit**

Run: `git status` inside `astrbot_plugin_bsk_browser/` to ensure working tree is clean.
