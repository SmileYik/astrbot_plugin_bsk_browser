# 设计文档：astrbot_plugin_bsk_browser 页面截断治理（大纲/分片/检索）与工具引导提示词全面重构

## 1. 意图与背景 (Intent & Why)

### 故障现象与痛点
在使用 `astrbot_plugin_bsk_browser` 浏览复杂长网页（例如百度搜索 `gtnh`）时，出现以下严重影响可用性的问题：
1. **页面截断严重，重要内容隐形**：
   在 [`bsk/pages.py`](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/bsk/pages.py) 中，`summarize()` 机制硬编码了 `MAX_REFS_SHOWN = 40` 并且字符预算上限仅为 `3000` 字符。一个搜索结果页通常含有 150+ 个可交互元素和大量文本，经过 `summarize()` 后，前 40 个元素几乎全是顶部导航栏、搜索推荐和广告推广；排在后面的真正搜索结果（如 e96+ 的 GTNH 维基、贴吧、博客等）、分页按钮与底部操作项被全部抹除，末尾仅留下一句 `……还有 110 个元素未列出` 与 `……（页面内容过长，已截断）`。
   模型无法获知被截断区域的存在与详情，也缺乏任何参数去查询或翻页，直接导致任务失败或陷入盲目重试。
2. **工具引导与返回提示混乱脱节**：
   各工具的返回引导不一致（`bsk_page` 引导调用 `sync`，`bsk_interact` 引导调用 `observe`）。当遇到底层浏览器策略拒绝（例如 `observation_required`）时，插件直接将冗长生硬的原生错误细节吐给模型，未给出清晰明确的自愈或下一步操作建议。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **长页面自适应展示（Adaptive Presentation）**：
   - **小型页面（元素总数 ≤ 30）**：直接返回全量元素和正文文本，保留当前一步直达的极简体验。
   - **大型长页面（元素总数 > 30）**：默认自动转换为“结构大纲与统计信息”视图，汇报标题、URL、视口尺寸、元素总数（含输入框/按钮/链接分类统计）、正文文本总段数，并给出前 5 个关键元素作为预览，附带清晰的按需拉取引导。
2. **多视图与按需拉取机制（Query & Slice）**：
   - 在 `bsk_inspect`（及 `bsk_read` 兼容层）中扩展 `query`、`offset`、`limit` 与 `view` 参数：
     - `query`：支持关键词模糊检索。直接在插件已解析的内存列表里搜索元素名、目标链接和文本行，秒级高亮返回匹配的 `@eN` 编号及上下文。
     - `offset` / `limit`：支持按范围分页切片查看元素列表或正文文本。
     - `view`：显式指定查看模式（`outline` 大纲 / `elements` 元素列表 / `text` 正文文本 / `auto` 自适应）。
3. **工具引导提示词全面重构（Standardized Guidance）**：
   - 统一所有工具执行返回格式为规范的三段式：`【状态】+【结果摘要】+【推荐后续动作】`。
   - 针对浏览器权限拦截（特别是 `observation_required` 策略拒绝），转化为直接可执行的脱困动作（例如推荐执行 `bsk_session(action="sync")`）。
   - 全面更新 `TOOL_DESCRIPTIONS` 与 `main.py` 的 docstrings，明确工具协同标准流程。
4. **单测覆盖**：
   - 补充针对自适应大纲输出、关键词过滤、范围分片切片、统一提示文案模板的单元测试。

### 非目标 (Non-Goals)
1. 不修改 `BrowserSkill` Rust 源码与 `bsk` 二进制文件（纯在 Python 插件层实现）。
2. 不引入 SQLite 或外部向量数据库等重型检索中间件（利用纯内存列表匹配，保持零额外依赖）。
3. 不增加新的常驻顶级工具（直接增强 `bsk_inspect`，避免稀释模型选工具的准确率）。

### 反目标 (Anti-Goals)
1. **严禁在小页面上强制两轮交互**：短页面必须自适应直接输出完整内容。
2. **严禁再次出现“无脱困路径的截断”**：任何存在剩余元素或文本的场景，必须附带明确的检索与翻页指导。

---

## 3. 约束条件 (Constraints)
1. **纯标准库与框架规范**：遵循 AstrBot 工具类型约束（整数参数声明为 `number`，不使用 `integer`；`type` 限制在 `string/number/boolean/object/array` 内）。
2. **零 IO 纯函数分层**：`bsk/pages.py` 保持无副作用纯函数设计，不依赖外部环境与全局变量，便于脱机单测。
3. **向后兼容**：不破坏既有 `bsk_inspect(action="observe")` 的既有默认调用逻辑。

---

## 4. 备选方案对比与决策 (Approaches)

### 方案 A：内存多视图与检索扩展方案（选定）
* **做法**：
  - 底层 `bsk observe` 调回的数据在插件内存中已包含完整 150+ 元素与文本。在 `bsk_inspect` 中扩展 `query`、`offset`、`limit` 和 `view`。
  - 默认调用时根据元素规模自适应输出（≤ 30 直出，> 30 输出大纲 + 分类统计 + 预览 + 引导）。
  - 提供毫秒级内存关键词检索与区间切片。
  - 全局统一“状态 + 摘要 + 推荐动作”的三段式引导模板。
* **权衡**：
  - 优点：性能最高（内存即时匹配），交互轮次最少（一条 query 直达目标），提示体系统一。
  - 缺点：`bsk_inspect` 新增 4 个可选参数。

### 方案 B：独立检索工具分离方案
* **做法**：新增独立工具 `bsk_search`。
* **放弃原因**：增加常驻工具会带来额外的 token 开销，且会导致大模型在 `inspect` 和 `search` 之间产生决策困惑。

### 方案 C：视口物理滚动方案
* **做法**：依赖 `bsk_interact(action="wheel")` 模拟滚轮下滚后再 `observe`。
* **放弃原因**：交互轮数多、耗时长、坐标容易偏差，极其容易在复杂长网页中迷失或超时。

---

## 5. 详细实现设计 (Detailed Implementation)

### 5.1 页面解析与检索模块设计 (`bsk/pages.py`)

#### 1. 结构大纲生成 (`render_outline`)
根据已解析的 `PageRef` 列表和文本行列表生成精炼大纲：
```python
def render_outline(
    title: str,
    refs: list[PageRef],
    text_lines: list[str],
    viewport: tuple[int, int] | None = None,
) -> str:
    # 统计元素类型
    inputs = [r for r in refs if r.role in ("textbox", "searchbox", "combobox")]
    buttons = [r for r in refs if r.role in ("button",)]
    links = [r for r in refs if r.role in ("link",)]
    other = [r for r in refs if r not in inputs and r not in buttons and r not in links]
    
    # 抽取前 5 个关键元素作为预览
    preview_refs = refs[:5]
    # 抽取前 3 段有代表性的正文
    preview_texts = text_lines[:3]
    
    # 拼装大纲 Markdown
```

#### 2. 元素与文本检索过滤 (`filter_elements_and_text`)
```python
def filter_elements_and_text(
    refs: list[PageRef],
    text_lines: list[str],
    *,
    query: str = "",
    offset: int = 0,
    limit: int = 30,
    view: str = "auto",
) -> tuple[list[PageRef], list[str], bool]:
    """返回 (过滤后元素, 过滤后文本, 是否有更多未展示内容 has_more)"""
```
- **关键词检索优先级与强过滤规则 (`query`)**：
  - **优先级高于大纲**：当传入 `query` 时，不论页面元素总数多大，**强制跳过大纲视图**，直接进入检索结果呈现。
  - **严格强过滤（不填补无关项）**：不区分大小写匹配 `ref.name`、`ref.target`、`ref.role` 以及正文文本行。**仅保留包含关键词的条目**，严禁使用无关元素凑数，避免大模型产生误导性幻觉。
  - **零匹配兜底**：若无匹配项，输出 `【搜索结果】未在当前页面中找到与 "{query}" 匹配的元素或文本`，并附带放宽关键词或按大纲浏览的推荐动作。
- **单维度切片模式 (`offset`/`limit` 与 `view`)**：
  - 元素列表与正文文本由于结构异构、数量级不同，**解耦切片**：
    - `view="elements"`：`offset` 与 `limit` 仅作用于 `refs`，文本区不输出或仅简述。
    - `view="text"`：`offset` 与 `limit` 仅作用于 `text_lines`，元素区不输出。
    - `view="auto"`：若页面 ≤ 30 元素直出全量；若 > 30 且未传 `offset` 时输出大纲；若传了 `offset` 则默认将 `offset`/`limit` 作用于 `refs`（自动化交互以元素操作为主）。
  - `has_more` 根据当前视角的剩余项独立计算。

#### 3. 增强 `summarize()`
在 `summarize()` 中增加 `query=""`, `offset=0`, `limit=30`, `view="auto"` 形参，替换原先简单生硬的 `safe_refs[:40]` 丢弃逻辑，并在底部输出可操作的引导提示。

---

### 5.2 工具参数与 Schema 扩展 (`bsk/tools.py`)

在 `TOOL_SCHEMAS["bsk_inspect"]` 中加入新增参数（纯 `number` / `string` 类型）：
```python
"query": {
    "type": "string",
    "description": "关键词搜索：直接在页面所有元素与文本中模糊匹配（如搜按钮名、文章标题、链接文字），快速定位目标 @ref 编号，无需翻页。",
},
"offset": {
    "type": "number",
    "description": "起始序号（从 0 开始），用于分段查看长页面的元素或正文。默认 0。",
},
"limit": {
    "type": "number",
    "description": "本次返回的元素或文本条数上限，默认 30，最大 100。",
},
"view": {
    "type": "string",
    "enum": ["auto", "outline", "elements", "text"],
    "description": "查看视角：auto（默认自适应，元素少于30直接展示，否则给大纲）、outline（仅查看大纲统计）、elements（查看元素列表）、text（查看页面正文）。",
}
```
并在 `normalize_args` 和 `validate` 中补充对 `query`、`offset`、`limit`、`view` 的有效性校验与清洗。

---

### 5.3 服务层透传 (`bsk/service.py`)

在 `BskService.observe` 与 `BskService.render_page` 中支持接收上述 4 个参数并传递给 `pages.summarize`：
```python
def render_page(
    self,
    observation: PageObservation,
    *,
    query: str = "",
    offset: int = 0,
    limit: int = 30,
    view: str = "auto",
) -> str:
    return summarize(
        observation.text,
        observation.title,
        observation.refs,
        max_chars=self.settings.max_page_chars,
        query=query,
        offset=offset,
        limit=limit,
        view=view,
    )
```

---

### 5.4 框架提示词与引导体系重构 (`main.py`)

#### 1. 统一三段式返回模板与适用范围
三段式结构规范定义为：
```text
【状态】已完成 <动作名>
【摘要】<关键信息，如 URL、坐标、统计数据等>
【推荐后续动作】
- <动作建议 1>
- <动作建议 2>
```

**工具分类适用范围与呈现规则**：
1. **页面导航与交互类工具（强制三段式）**：
   `bsk_page`、`bsk_interact`、`bsk_session` 以及所有动作执行失败时的异常回执，全部采用标准三段式，提供状态确认与推荐后续动作。
2. **页面检查类工具 (`bsk_inspect` / `bsk_read`)**：
   不把庞大的页面树强塞进 `【摘要】` 内部，而是**保持结构化页面内容/大纲直出，在内容末尾统一追加标准化的 `【推荐后续动作】` 区块**，既不破坏模型对 VOM/大纲的解析，又能得到明确的行动指引。
3. **数据调试与控制类工具 (`bsk_debug`)**：
   遵循官方约束，**保持原始 JSON/文本直通（豁免三段式外壳）**，严禁字段重映射破坏结构。兼容层工具亦保持既有数据结构，不增加额外包袱。

示例：
- `bsk_page` 导航完成：
  ```text
  【状态】页面已到达 networkidle 阶段
  【摘要】当前地址：https://www.baidu.com/s?wd=gtnh
  【推荐后续动作】
  1. 调用 bsk_inspect(action="observe") 查看页面内容与元素大纲；
  2. 若需要直接定位目标，可调用 bsk_inspect(action="observe", query="关键词")。
  ```
- `bsk_interact` 点击完成：
  ```text
  【状态】已执行 click 操作
  【摘要】目标元素：@e80，已点击坐标 (915.5, 421.875)
  【推荐后续动作】
  1. 点击可能改变页面或触发跳转，建议调用 bsk_inspect(action="observe") 确认页面最新状态；
  2. 若页面发生了整页跳转，推荐优先调用 bsk_session(action="sync") 重新建立控制权。
  ```

#### 2. 权限策略拦截友好脱困引导
在 `main.py` 的异常捕获与格式化中（特别是捕获到 `observation_required` 或 `cooperation_sync_required`）：
```python
if reason == "observation_required":
    return (
        "【操作受阻】当前操作被浏览器权限策略拒绝（需要先建立有效的页面观察上下文）。\n"
        "【原因分析】页面发生过导航或操作后尚未同步控制状态。\n"
        "【推荐脱困操作】请先调用 bsk_session(action=\"sync\") 同步页面并激活控制权，然后再继续操作。"
    )
```

#### 3. 工具 Docstring 全面润色
更新 `main.py` 中 8 个新工具及主要兼容工具的 docstring，对齐当前推荐的交互模式（强调 `query` 检索能力与状态同步逻辑）。

---

## 6. 留给实现者的自由裁量 (Left to Builder)
1. 关键词检索大小写敏感度与拼音/中英分词匹配细节：实现者可优先采用标准小写包含匹配（`in`），保持高执行效率与鲁棒性；
2. 大纲中各类型元素数量统计的具体分类阈值与排版美化；
3. 单元测试用例的数据构造与断言细节。
