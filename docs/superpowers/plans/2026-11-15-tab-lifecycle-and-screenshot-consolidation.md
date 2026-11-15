# 标签页闭环感知与清理、截图工具收敛及绝对路径增强实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底解决外链新标签页脱管与宿主机残留、下线冗余的独立截图工具 `bsk_screenshot`（统一归拢至 `bsk_inspect(action="screenshot")`）、规范全链路截图绝对路径输出，并维护相关 SKILL 文档。

**Architecture:** 
1. 修复底层 `BskService._render_tabs` 数据解析逻辑，使之原生兼容 `{"tabs": [...]}` 字典及 `[...]` 列表；
2. 激活点击后自动感知新标签、切换前台焦点（`tab select <id>`）并在交互回执中提示模型的完整闭环，并在会话停止时执行 `sweep_agent_tabs` 确保零残留；
3. 从 `main.py` 注销并彻底删除独立工具 `bsk_screenshot`，将截图逻辑与图片发送完全收敛至 `bsk_inspect(action="screenshot")`；
4. 确保 `make_shot_path` 与 `screenshot_ex` 均返回 `.resolve().absolute()` 规范绝对路径；
5. 更新 `bsk-browser`、`browse-baidu.com`、`browse-cn.bing.com` 的 SKILL 文档并补充相应测试。

**Tech Stack:** Python 3.10+, AstrBot Star Plugin Framework, BrowserSkill CLI (bsk), Pytest, Asyncio.

**Spec:** [docs/superpowers/specs/2026-11-15-tab-lifecycle-and-screenshot-consolidation-design.md](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-tab-lifecycle-and-screenshot-consolidation-design.md)

## Global Constraints

- 日志等级要求：以 DEBUG 等级输出所有 bsk 指令输入/输出及工具会话/名称日志。
- 工具提示与说明文本：在表义清晰准确的基础上保持精炼简洁不啰嗦。
- SKILL 文档维护：维护 `bsk-browser`、`browse-baidu.com`、`browse-cn.bing.com`，内容精炼准确。
- 严禁误伤用户未授权的非 Agent Window 普通浏览器标签页。
- 每次任务完成后必须 commit `astrbot_plugin_bsk_browser` 仓库。

## Review Focus

1. `bsk tab list --json` 输出了 `{"tabs": [...]}` 字典时，`_render_tabs` 能否正确提取到标签列表；
2. 点击外链生成多个新标签或嵌套弹窗时，`detect_new_tabs_and_switch` 是否能准确识别并成功切换焦点至最新标签；
3. 会话销毁（`close_session` / `shutdown`）时，`sweep_agent_tabs` 是否会逐个将除主标签外的所有弹窗彻底关闭；
4. 截图返回的路径无论在容器内还是宿主机上是否均为标准的绝对路径，无相对路径残留；
5. 独立工具 `bsk_screenshot` 彻底下线后，旧工具常驻计数从 4 个减为 3 个，旧配置项 `legacy_tools` 开关与文档说明是否保持同步。

---

### Task 1: 修复标签页列表数据解析 (`_render_tabs`) 与新标签检测及清理验证

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py:3198-3231`
- Test: `astrbot_plugin_bsk_browser/tests/test_tab_detection.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py`

**Interfaces:**
- Consumes: `result.data` from `bsk tab list --scope agent --json` (dict `{"tabs": [...]}` or list `[...]`)
- Produces: `BskService._render_tabs(data: Any) -> list[dict[str, Any]]`

- [ ] **Step 1: 编写针对 `_render_tabs` 字典格式载荷的失败测试**

在 `astrbot_plugin_bsk_browser/tests/test_tab_detection.py` 中增加用例：
```python
def test_render_tabs_supports_dict_format(self):
    data = {
        "tabs": [
            {"tab_id": 101, "title": "Page 1", "url": "https://a.com", "active": False},
            {"tab_id": 102, "title": "Page 2", "url": "https://b.com", "active": True},
        ]
    }
    rendered = self.service._render_tabs(data)
    self.assertEqual(len(rendered), 2)
    self.assertEqual(rendered[0]["tab_id"], 101)
    self.assertEqual(rendered[1]["tab_id"], 102)
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_tab_detection.py::TestTabDetection::test_render_tabs_supports_dict_format -v`  
Expected: FAIL (`len(rendered) == 0 != 2`)

- [ ] **Step 3: 实现 `_render_tabs` 适配支持字典与列表**

修改 `astrbot_plugin_bsk_browser/bsk/service.py` 中的 `_render_tabs`：
```python
if isinstance(data, dict):
    items = data.get("tabs", [])
elif isinstance(data, list):
    items = data
else:
    return []
if not isinstance(items, list):
    return []
```

- [ ] **Step 4: 运行标签检测与清理测试集验证通过**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_tab_detection.py astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py -v`  
Expected: 全部 PASS

- [ ] **Step 5: Git 提交**

```bash
git add astrbot_plugin_bsk_browser/bsk/service.py astrbot_plugin_bsk_browser/tests/test_tab_detection.py
git commit -m "fix(service): support dict payload with tabs key in _render_tabs"
```

---

### Task 2: 规范化全链路截图绝对路径输出

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/shots.py:280-320`
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py:3460-3530`
- Test: `astrbot_plugin_bsk_browser/tests/test_inspect_screenshot_image.py`

**Interfaces:**
- Consumes: `directory: str | Path`, `session_key: str`
- Produces: `make_shot_path(...) -> Path` (always absolute), `ShotPayload.path: str` (always absolute)

- [ ] **Step 1: 编写截图路径为绝对路径的失败测试**

在 `astrbot_plugin_bsk_browser/tests/test_inspect_screenshot_image.py` 中补充校验：
```python
def test_make_shot_path_returns_absolute_path(self):
    p = make_shot_path("relative/dir", "session_1")
    self.assertTrue(p.is_absolute())
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_inspect_screenshot_image.py::TestInspectScreenshotImage::test_make_shot_path_returns_absolute_path -v`  
Expected: FAIL (`is_absolute() is False`)

- [ ] **Step 3: 修改 `make_shot_path` 与 `screenshot_ex` 强制解析为绝对路径**

在 `astrbot_plugin_bsk_browser/bsk/shots.py:make_shot_path` 中：
```python
base = Path(directory).resolve().absolute() / "shots" / sanitize_session_id(session_id)
```
并在 `screenshot_ex` 中确保 `payload.path` 取 `str(Path(out_path).resolve().absolute())`。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_inspect_screenshot_image.py -v`  
Expected: PASS

- [ ] **Step 5: Git 提交**

```bash
git add astrbot_plugin_bsk_browser/bsk/shots.py astrbot_plugin_bsk_browser/bsk/service.py astrbot_plugin_bsk_browser/tests/test_inspect_screenshot_image.py
git commit -m "feat(shots): ensure all screenshot paths are strictly absolute"
```

---

### Task 3: 彻底移除独立 `bsk_screenshot` 工具并修正日志调用

**Files:**
- Modify: `astrbot_plugin_bsk_browser/main.py`
- Modify: `astrbot_plugin_bsk_browser/bsk/config.py`
- Modify: `astrbot_plugin_bsk_browser/_conf_schema.json`
- Modify: `astrbot_plugin_bsk_browser/metadata.yaml`
- Modify: `astrbot_plugin_bsk_browser/README.md`
- Modify: `astrbot_plugin_bsk_browser/ARCHITECTURE.md`
- Test: `astrbot_plugin_bsk_browser/tests/test_tool_registration.py` (及相关全集)

**Interfaces:**
- Consumes: `bsk_inspect(action="screenshot", full_page=...)`
- Produces: 彻底移除 `@filter.llm_tool("bsk_screenshot")`，常驻旧工具名单 `LEGACY_TOOL_NAMES` 移除非法成员

- [ ] **Step 1: 编写测试断言 `bsk_screenshot` 不再被注册为独立 LLM Tool**

在相关工具注册测试中确认插件导出的工具列表中不含 `bsk_screenshot`。

- [ ] **Step 2: 运行测试验证失败（当前仍能查到 `bsk_screenshot`）**

Run: `pytest astrbot_plugin_bsk_browser/tests/ -k screenshot`  
Expected: 涉及旧工具 `bsk_screenshot` 存在的用例需调整

- [ ] **Step 3: 从 `main.py` 移除 `bsk_screenshot` 并修复 logger**

1. 删除 `main.py` 中的 `@filter.llm_tool("bsk_screenshot") async def bsk_screenshot(...)`；
2. 在 `LEGACY_TOOL_NAMES` 中移除 `"bsk_screenshot"`；
3. 将常驻旧工具描述从 4 个（screenshot, close, status, logs）更新为 3 个（close, status, logs）；
4. 修复 `main.py` 第 1744 行的 `self.logger.debug` 笔误，改为 `astrbot_logger.debug`；
5. 同步更新 `config.py`、`_conf_schema.json`、`metadata.yaml`、`README.md` 与 `ARCHITECTURE.md`。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest astrbot_plugin_bsk_browser/tests/ -v`  
Expected: PASS

- [ ] **Step 5: Git 提交**

```bash
git add astrbot_plugin_bsk_browser/main.py astrbot_plugin_bsk_browser/bsk/config.py astrbot_plugin_bsk_browser/_conf_schema.json astrbot_plugin_bsk_browser/metadata.yaml astrbot_plugin_bsk_browser/README.md astrbot_plugin_bsk_browser/ARCHITECTURE.md
git commit -m "refactor(tools): remove standalone bsk_screenshot and unify into bsk_inspect"
```

---

### Task 4: 更新 SKILL 文档 (`bsk-browser`, `browse-baidu.com`, `browse-cn.bing.com`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/skill/bsk-browser/SKILL.md`
- Modify: `astrbot_plugin_bsk_browser/skill/browse-baidu.com/SKILL.md`
- Modify: `astrbot_plugin_bsk_browser/skill/browse-cn.bing.com/SKILL.md`

**Interfaces:**
- Consumes: [AGENTS.md](file:///run/media/smileyik/G/Workspace/ai/bsk/AGENTS.md) 规则及规范
- Produces: 精炼、简洁、准确的 SKILL 指南

- [ ] **Step 1: 更新 `bsk-browser/SKILL.md`**
  - 移除 `bsk_screenshot`，统一使用 `bsk_inspect(action="screenshot", full_page=...)`；
  - 明确截图输出为绝对路径；
  - 强化点击外链后自动切换焦点感知，以及用完后及时调用 `bsk_tabs(action="close", tab_id=...)` 清理标签页的引导。

- [ ] **Step 2: 更新 `browse-baidu.com/SKILL.md`**
  - 明确在搜索结果页点击条目后新标签页自动切换焦点的处理流程；
  - 强调翻页按钮、指定跳转与结果滚动的准确指引。

- [ ] **Step 3: 更新 `browse-cn.bing.com/SKILL.md`**
  - 明确必应搜索结果点击后的新标签页处理流程与滚动截图规范。

- [ ] **Step 4: 校验 SKILL 文档内容规范**
  - 确认文字表义准确且精炼简洁不啰嗦。

- [ ] **Step 5: Git 提交**

```bash
git add astrbot_plugin_bsk_browser/skill/
git commit -m "docs(skill): update bsk-browser, baidu, and bing skills for unified screenshot and tab flow"
```

---

### Task 5: 全量回归测试与最终交付验证

**Files:**
- Verify all modified files across `astrbot_plugin_bsk_browser`

- [ ] **Step 1: 执行全量测试套件**

Run: `pytest astrbot_plugin_bsk_browser/tests`  
Expected: 100% 测试通过。

- [ ] **Step 2: 检查 git status 与工作区干净度**

Run: `git -C astrbot_plugin_bsk_browser status`  
Expected: 无未跟踪文件、工作区整洁。
