# 页面截断治理与工具引导提示词全面重构实施规划 (Page Inspection & Guidance Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解决长页面截断导致内容/元素隐形问题（自适应大纲、单维度切片、内存关键词强过滤），并重构全插件工具引导提示词为三段式规范模板。

**Architecture:** 
1. 在 `bsk/pages.py` 中增强纯函数解析，根据元素规模（阈值 30）自适应切换全量/大纲视图，并实现无外部依赖的单维度范围切片与关键词模糊匹配；
2. 在 `bsk/tools.py` 中为 `bsk_inspect` 扩展 `query`、`offset`、`limit`、`view` 规格，并更新全局工具中文描述；
3. 在 `bsk/service.py` 串联参数至 `render_page`；
4. 在 `main.py` 全局落地三段式（`【状态】+【结果摘要】+【推荐后续动作】`）回执模板与 `observation_required` 友好脱困指引。

**Tech Stack:** Python 3.10+, AstrBot Star Plugin SDK, `unittest`

**Spec:** [`astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-bsk-page-inspection-and-guidance-design.md`](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-bsk-page-inspection-and-guidance-design.md)

## Global Constraints

- **纯标准库与无外部依赖**：`bsk/pages.py` 保持纯函数设计，不引入外部第三方库。
- **参数类型白名单**：JSON Schema 属性 `type` 仅允许使用 `string`、`number`、`boolean`、`object`、`array`，严禁使用 `integer`。
- **向后兼容性**：`bsk_debug` 保持原始数据直通契约；旧工具兼容层参数和行为不回退。
- **自适应阈值**：页面可交互元素数 ≤ 30 时必须直接返回全量内容，严禁强制要求大模型分轮拉取。

## Review Focus

1. **带 query 访问超长页面**：页面元素 > 30 时传入 `query="目标"`，预期强制跳过大纲直接返回检索到的匹配项。
2. **query 检索 0 匹配**：输入页面不存在的关键词，预期返回清晰的无结果提示与放宽检索建议，严禁用不相关元素填充。
3. **单维度分片解耦**：`view="text"` 时传 `offset=10, limit=20`，预期仅切片返回文本段落，不混杂元素列表。
4. **权限策略拦截 (`observation_required`)**：页面跳转或未同步时操作受阻，预期输出明确的脱困动作引导（推荐调用 `sync`）。
5. **极小/空白页面边界**：页面无元素或只有 1-2 个元素时，预期自适应输出完整视图，不产生空指针或除零异常。

---

### Task 1: 页面大纲生成、元素分类统计与自适应展示逻辑 (`bsk/pages.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/pages.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_pages.py`

**Interfaces:**
- Produces:
  - `render_outline(title: str, refs: list[PageRef], text_lines: list[str], viewport: tuple[int, int] | None = None) -> str`
  - 更新 `summarize(text: str, title: str, refs: list[PageRef], *, max_chars: int = 3000, view: str = "auto") -> str`

- [ ] **Step 1: Write the failing tests in `tests/test_pages.py`**

```python
def test_render_outline_structure(self):
    from astrbot_plugin_bsk_browser.bsk.models import PageRef
    from astrbot_plugin_bsk_browser.bsk.pages import render_outline
    refs = [
        PageRef(ref="e1", role="textbox", name="搜索框"),
        PageRef(ref="e2", role="button", name="百度一下"),
        PageRef(ref="e3", role="link", name="贴吧"),
    ]
    text_lines = ["段落1", "段落2", "段落3", "段落4"]
    outline = render_outline("测试标题", refs, text_lines, viewport=(1920, 1080))
    self.assertIn("测试标题", outline)
    self.assertIn("1920x1080", outline)
    self.assertIn("可交互元素共 3 个", outline)
    self.assertIn("输入框: 1", outline)
    self.assertIn("按钮: 1", outline)
    self.assertIn("链接: 1", outline)
    self.assertIn("正文文本共 4 段", outline)
    self.assertIn("【推荐后续动作】", outline)

def test_summarize_adaptive_short_page(self):
    from astrbot_plugin_bsk_browser.bsk.models import PageRef
    from astrbot_plugin_bsk_browser.bsk.pages import summarize
    refs = [PageRef(ref=f"e{i}", role="link", name=f"链接{i}") for i in range(1, 10)]
    out = summarize("L1 page\nparagraph \"正文内容\"", "短页面", refs)
    self.assertIn("短页面", out)
    self.assertIn("@e1 link \"链接1\"", out)
    self.assertIn("@e9 link \"链接9\"", out)
    self.assertNotIn("大纲统计", out)

def test_summarize_adaptive_long_page(self):
    from astrbot_plugin_bsk_browser.bsk.models import PageRef
    from astrbot_plugin_bsk_browser.bsk.pages import summarize
    refs = [PageRef(ref=f"e{i}", role="link", name=f"链接{i}") for i in range(1, 50)]
    out = summarize("L1 page\nparagraph \"正文内容\"", "长页面", refs)
    self.assertIn("长页面", out)
    self.assertIn("可交互元素共 49 个", out)
    self.assertIn("【推荐后续动作】", out)
    self.assertIn("query", out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest astrbot_plugin_bsk_browser/tests/test_pages.py`
Expected: FAIL (`render_outline` not defined / `summarize` does not produce outline for > 30 refs).

- [ ] **Step 3: Implement `render_outline` and adaptive logic in `bsk/pages.py`**

- 实现 `render_outline(title, refs, text_lines, viewport)`，对 `refs` 按 `textbox/searchbox/combobox`（输入框）、`button`（按钮）、`link`（链接）、其他角色分类统计；
- 在 `summarize` 中增加自适应判断：当 `view == "auto"` 且 `len(refs) > 30` 时，调用 `render_outline` 输出大纲与引导。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest astrbot_plugin_bsk_browser/tests/test_pages.py`
Expected: PASS.

- [ ] **Step 5: Verify all existing tests pass**

Run: `python -m unittest discover -s astrbot_plugin_bsk_browser/tests`
Expected: PASS (all tests pass).

---

### Task 2: 内存多视图与关键词过滤检索 (`filter_elements_and_text` in `bsk/pages.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/pages.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_pages.py`

**Interfaces:**
- Produces:
  - `filter_elements_and_text(refs: list[PageRef], text_lines: list[str], *, query: str = "", offset: int = 0, limit: int = 30, view: str = "auto") -> tuple[list[PageRef], list[str], bool]`
  - 增强 `summarize(text: str, title: str, refs: list[PageRef], *, max_chars: int = 3000, query: str = "", offset: int = 0, limit: int = 30, view: str = "auto") -> str`

- [ ] **Step 1: Write the failing tests in `tests/test_pages.py`**

```python
def test_filter_by_query_matching(self):
    from astrbot_plugin_bsk_browser.bsk.models import PageRef
    from astrbot_plugin_bsk_browser.bsk.pages import filter_elements_and_text
    refs = [
        PageRef(ref="e1", role="link", name="百度首页"),
        PageRef(ref="e2", role="link", name="GTNH灰机wiki"),
        PageRef(ref="e3", role="button", name="提交"),
    ]
    texts = ["欢迎来到百度", "GTNH是大型整合包", "无关正文"]
    matched_refs, matched_texts, has_more = filter_elements_and_text(
        refs, texts, query="gtnh"
    )
    self.assertEqual(len(matched_refs), 1)
    self.assertEqual(matched_refs[0].ref, "e2")
    self.assertEqual(len(matched_texts), 1)
    self.assertEqual(matched_texts[0], "GTNH是大型整合包")

def test_filter_by_query_zero_matches(self):
    from astrbot_plugin_bsk_browser.bsk.models import PageRef
    from astrbot_plugin_bsk_browser.bsk.pages import filter_elements_and_text
    refs = [PageRef(ref="e1", role="link", name="百度首页")]
    texts = ["正文内容"]
    matched_refs, matched_texts, has_more = filter_elements_and_text(
        refs, texts, query="不存在的词"
    )
    self.assertEqual(len(matched_refs), 0)
    self.assertEqual(len(matched_texts), 0)

def test_filter_by_offset_limit_elements(self):
    from astrbot_plugin_bsk_browser.bsk.models import PageRef
    from astrbot_plugin_bsk_browser.bsk.pages import filter_elements_and_text
    refs = [PageRef(ref=f"e{i}", role="link", name=f"项{i}") for i in range(100)]
    texts = ["段落1", "段落2"]
    matched_refs, matched_texts, has_more = filter_elements_and_text(
        refs, texts, offset=10, limit=20, view="elements"
    )
    self.assertEqual(len(matched_refs), 20)
    self.assertEqual(matched_refs[0].ref, "e10")
    self.assertEqual(len(matched_texts), 0)
    self.assertTrue(has_more)

def test_summarize_query_bypasses_long_page_outline(self):
    from astrbot_plugin_bsk_browser.bsk.models import PageRef
    from astrbot_plugin_bsk_browser.bsk.pages import summarize
    refs = [PageRef(ref=f"e{i}", role="link", name=f"普通项{i}") for i in range(50)]
    refs.append(PageRef(ref="e99", role="link", name="GTNH维基百科"))
    out = summarize("L1 page\nparagraph \"内容\"", "长页面", refs, query="维基")
    self.assertIn("@e99", out)
    self.assertIn("GTNH维基百科", out)
    self.assertNotIn("可交互元素共 51 个", out)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest astrbot_plugin_bsk_browser/tests/test_pages.py`
Expected: FAIL (`filter_elements_and_text` not implemented / `query` in `summarize` not handled).

- [ ] **Step 3: Implement `filter_elements_and_text` and update `summarize` in `bsk/pages.py`**

- 实现大小写不敏感包含匹配（严格强过滤，0 匹配不混入无关条目）；
- 实现单维度 `offset`/`limit` 切片：`view="elements"` 切元素，`view="text"` 切文本；
- 在 `summarize` 中，若有 `query`，无论元素多少均跳过大纲直接展示过滤结果；零匹配时输出友好引导。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest astrbot_plugin_bsk_browser/tests/test_pages.py`
Expected: PASS.

- [ ] **Step 5: Verify all existing tests pass**

Run: `python -m unittest discover -s astrbot_plugin_bsk_browser/tests`
Expected: PASS.

---

### Task 3: 工具规范、Schema 扩展与参数校验 (`bsk/tools.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/tools.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_tools.py`
- Modify: `astrbot_plugin_bsk_browser/tests/verify_tool_params.py`

**Interfaces:**
- Consumes: `bsk/tools.py` 内部校验流
- Produces:
  - `TOOL_SCHEMAS["bsk_inspect"]` 增加 `query`, `offset`, `limit`, `view`
  - 更新 `TOOL_DESCRIPTIONS` 中针对各工具的标准化指引

- [ ] **Step 1: Write the failing tests in `tests/test_tools.py`**

```python
def test_validate_inspect_new_params(self):
    from astrbot_plugin_bsk_browser.bsk.tools import validate
    # 正常参数
    valid = validate("bsk_inspect", {"action": "observe", "query": "gtnh", "offset": 10, "limit": 20, "view": "elements"})
    self.assertEqual(valid["query"], "gtnh")
    self.assertEqual(valid["offset"], 10)
    self.assertEqual(valid["limit"], 20)
    self.assertEqual(valid["view"], "elements")

def test_validate_inspect_invalid_params(self):
    from astrbot_plugin_bsk_browser.bsk.tools import BskToolError, validate
    with self.assertRaises(BskToolError):
        validate("bsk_inspect", {"action": "observe", "offset": -1})
    with self.assertRaises(BskToolError):
        validate("bsk_inspect", {"action": "observe", "limit": 0})
    with self.assertRaises(BskToolError):
        validate("bsk_inspect", {"action": "observe", "view": "invalid_view"})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest astrbot_plugin_bsk_browser/tests/test_tools.py`
Expected: FAIL (`query`/`offset`/`limit`/`view` not recognized or validated).

- [ ] **Step 3: Update `TOOL_SCHEMAS`, `TOOL_DESCRIPTIONS`, `normalize_args`, and `validate` in `bsk/tools.py`**

- 在 `TOOL_SCHEMAS["bsk_inspect"]["properties"]` 增加 `query`, `offset`, `limit`, `view`；
- 在 `validate` 中校验：`offset >= 0`、`1 <= limit <= 100`、`view in ("auto", "outline", "elements", "text")`；
- 润色 `TOOL_DESCRIPTIONS`，明确推荐的工作流。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest astrbot_plugin_bsk_browser/tests/test_tools.py`
Run: `python astrbot_plugin_bsk_browser/tests/verify_tool_params.py`
Expected: PASS.

---

### Task 4: 服务层透传与集成 (`bsk/service.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_service.py`

**Interfaces:**
- Consumes: `bsk/pages.py` 的 `summarize`
- Produces:
  - `BskService.render_page(observation, *, query="", offset=0, limit=30, view="auto") -> str`
  - `BskService.observe(key, *, cursor="", max_depth=None, max_tokens=None, tab_id=None, probe_hover=False, debug_surfaces=False, query="", offset=0, limit=30, view="auto") -> PageObservation`

- [ ] **Step 1: Write the failing tests in `tests/test_service.py`**

```python
def test_render_page_passes_query_and_view(self):
    from astrbot_plugin_bsk_browser.bsk.models import PageObservation, PageRef
    obs = PageObservation(text="L1 page\nparagraph \"内容\"", refs=[PageRef(ref="e1", role="link", name="测试目标")])
    rendered = self.service.render_page(obs, query="目标", view="elements")
    self.assertIn("@e1", rendered)
    self.assertIn("测试目标", rendered)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest astrbot_plugin_bsk_browser/tests/test_service.py`
Expected: FAIL (`render_page` unexpected keyword argument `query`).

- [ ] **Step 3: Update `render_page` and `observe` in `bsk/service.py`**

- 在 `render_page` 增加 `query`, `offset`, `limit`, `view` 并转发给 `summarize`；
- 在 `observe` 中接收这 4 个参数并在 `observation` 对象中妥善传递或在 `_run_observe` 后供渲染使用。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest astrbot_plugin_bsk_browser/tests/test_service.py`
Expected: PASS.

---

### Task 5: 框架入口与三段式提示词体系重构 (`main.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/main.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_main_sync.py`
- Modify: `astrbot_plugin_bsk_browser/tests/verify_failure_ux.py`

**Interfaces:**
- Consumes: `bsk/service.py` 与 `bsk/tools.py`
- Produces:
  - 格式化的三段式成功返回与友好受阻回执（`observation_required`）
  - 全面更新的 `@filter.llm_tool` docstrings

- [ ] **Step 1: Write the failing tests in `tests/test_main_sync.py` and `tests/verify_failure_ux.py`**

```python
def test_interact_result_three_tier_format(self):
    # 验证 main.py 的点击等交互回执包含【状态】、【摘要】和【推荐后续动作】
    res = self.plugin._render_act_result("click", {"target": "@e1"}, used_ref="e1", coords=(100, 200))
    self.assertIn("【状态】已执行 click 操作", res)
    self.assertIn("【摘要】目标元素：@e1", res)
    self.assertIn("【推荐后续动作】", res)

def test_observation_required_recovery_hint(self):
    # 验证遇到 observation_required 时输出直接脱困指引
    err_text = self.plugin._format_error("bsk_page", BskError("observation_required", reason="observation_required"))
    self.assertIn("【操作受阻】", err_text)
    self.assertIn("bsk_session(action=\"sync\")", err_text)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest astrbot_plugin_bsk_browser/tests/test_main_sync.py`
Expected: FAIL.

- [ ] **Step 3: Refactor return formatting and docstrings in `main.py`**

- 重构 `_render_nav`, `_run_interact`, `_run_observe`, `_format_error`；
- 在 `_run_observe` 中将 `query`, `offset`, `limit`, `view` 传给 `service.render_page`；
- 对捕获到的 `observation_required` 给出明确脱困建议；
- 更新所有工具的 docstring。

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest astrbot_plugin_bsk_browser/tests/test_main_sync.py`
Run: `python astrbot_plugin_bsk_browser/tests/verify_failure_ux.py`
Expected: PASS.

---

### Task 6: 全链路回归与现有测试套件校验

**Files:**
- Modify: `astrbot_plugin_bsk_browser/tests/` 下可能受文案格式变更影响的断言用例

- [ ] **Step 1: Run complete test suite**

Run: `python -m unittest discover -s astrbot_plugin_bsk_browser/tests`
Expected: 检查是否有既有用例因断言特定旧文案而失败。

- [ ] **Step 2: Adjust broken string assertions in existing verification scripts**

- 若有测试断言了旧文案（如 `建议接着用 bsk_read`），根据新的三段式规范进行同步更新。

- [ ] **Step 3: Run all verification scripts**

Run:
```bash
python -m unittest discover -s astrbot_plugin_bsk_browser/tests
python astrbot_plugin_bsk_browser/tests/verify_tools_e2e.py
python astrbot_plugin_bsk_browser/tests/verify_failure_ux.py
python astrbot_plugin_bsk_browser/tests/verify_tool_params.py
```
Expected: ALL PASS.
