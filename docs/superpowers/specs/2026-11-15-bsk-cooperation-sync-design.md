# 设计文档：astrbot_plugin_bsk_browser 协同控制同步机制（Cooperation Sync）与交互自愈增强

## 1. 意图与背景 (Intent & Why)

### 故障回顾
在最新代码环境下，向机器人提出复合自动化需求：
> “先打开百度，在搜索框内输入gtnh，然后按下回车，等待界面加载完毕后找到下一页按钮，点击下一页按钮，然后点击第一个搜索结果。”

机器人执行过程中出现严重故障：
1. `bsk_session(action='start')` 成功启动；
2. `bsk_page(action='navigate', url='https://www.baidu.com')` 导航成功（利用了 BrowserSkill 在初始 `about:blank` 标签页的 bootstrap 导航豁免机制）；
3. `bsk_inspect(action='observe')` 读取页面元素成功（只读操作，不依赖控制权凭证）；
4. 当机器人试图调用 `bsk_interact(action='fill', target='@e15', value='gtnh')` 时，底层报出严重错误：
   ```
   页面交互失败：操作被浏览器权限策略拒绝（原因：cooperation_sync_required）。
   详情: This action requires the context returned by the latest cooperate sync
   （提示：Use cooperate wait, then cooperate sync. Keep the assigned goal; reconcile the live result before issuing a new action. Never replay an uncertain submission.）
   ```
5. 机器人随后尝试 `bsk_interact(focus)`、`bsk_page(navigate)` 均被同样的 `cooperation_sync_required` 拒绝；
6. 机器人绕道使用 `bsk_tabs(action='create', url='...')` 新开标签页（再次利用新标签页的 bootstrap 豁免）直接进入搜索结果页后，在试图点击下一页（`@e27`）和结果链接时，再次全部因 `cooperation_sync_required` 彻底卡死，任务彻底失败。

### 根本原因
BrowserSkill 的架构基于人机协同设计（Cooperation Policy）：
- 所有页面写入/点击交互（`click`、`fill`、`press` 以及非空白页的 `navigate`）都必须在有效的控制上下文（`context_id`）下执行。
- 只有通过 `bsk sync`（底层 `tool.cooperate sync`），BrowserSkill 浏览器扩展才会签发 `context_id`，且 `bsk daemon` 会在本地维护该会话/标签页的 `target` 控制策略，并在后续 CLI 命令中自动注入 `context_id`（`auto_inject_context`）。
- **当前插件从始至终未实现也未调用过 `bsk sync`**。插件仅依赖只读的 `bsk observe`，导致 daemon 中从未注册过上下文凭据，浏览器扩展因此强制拦截所有非初始页的交互操作。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **对齐官方 MCP 规范暴露 `sync` 与 `open`**：在 `bsk_session` 工具中支持 `action="sync"` 和 `action="open"`，让大模型能够自主同步页面状态并获得控制上下文。
2. **交互层自动 `sync` 补救重试**：在 `service.interact` 中捕获 `cooperation_sync_required` 错误，当处于无副作用的安全状态（`effect_state: none`）时，在后台自动执行一次 `bsk sync` 重新建立控制权并单次重试交互。
3. **显式告知大模型补救发生**：在交互结果中打标 `auto_synced=True`，在最终返回给大模型的文本中显式附带提示，告知其刚才执行了自动 sync 补救，并引导模型在后续页面跳转后主动调用 `bsk_session(action='sync')`。
4. **完善错误引导**：在 `bsk/errors.py` 中为 `cooperation_sync_required` 提供清晰准确的中文指引，杜绝泛化的未知权限拒绝报错。
5. **单元测试与回归防护**：编写完整的测试用例，覆盖 `sync`、`open`、交互自动补救、重试显式提示以及异常分支。

### 非目标 (Non-Goals)
1. 不修改 BrowserSkill（Rust CLI / TypeScript 扩展）本身的底层源码；
2. 不取消只读的 `bsk_inspect(action="observe")`，保持既有能力与向后兼容；
3. 不对未知副作用状态（`effect_state: "unknown"`）进行盲目重试。

### 反目标 (Anti-Goals)
1. **禁止无限循环同步重试**：每次交互调用中，`sync` 补救重试严格限制为最多 1 次；若重试仍失败，必须如实向模型抛出错误；
2. **禁止静默重试不通知模型**：用户明确要求必须显式告诉模型补救发生，避免模型形成“不需要同步也能交互”的错误认知。

---

## 3. 约束条件 (Constraints)
1. 保持现有工具对既有提示词与调用的完全向后兼容；
2. 保持对 Python 3.10+ 标准库与 AstrBot 插件运行环境的兼容；
3. 严格遵循项目中已有的 `auto_scrolled` 自愈与回显设计模式，保持代码风格与架构一致性。

---

## 4. 备选方案对比与决策 (Approaches)

### 方案 A：轻量级 MCP 对齐 + 交互补救方案
- **做法**：仅在 `bsk_session` 增加 `action="sync"`，并在 `interact` 中实现自动补救重试。
- **缺点**：缺少官方 MCP 规范中常用的高效 `bsk_session(action="open")`，模型在初次访问页面时仍必须分步调用 `start` -> `navigate` -> `sync`，容易在第一步跳转后遗漏同步。

### 方案 B：完整 MCP 规范对齐 + 双向协同鲁棒方案（已选定）
- **做法**：
  1. `bsk_session` 完整扩充 `sync` 与 `open`（`open` 实现“启动 + 导航 + 稳定等待 + 自动 sync”一步到位）；
  2. `interact` 遭遇 `cooperation_sync_required` 自动执行后台 `sync` 并重试一次；
  3. 回执中打标 `auto_synced=True` 并显式渲染教学提示；
  4. 更新 `bsk_page` 与 `bsk_inspect` 工具描述与返回提示，指引模型在交互前主动 `sync`。
- **决策理由**：用户明确选择方案 B。该方案既规范实现了官方 MCP 规范，又具备底层容错自愈能力，能彻底解决各类大模型因时序不规范导致的卡死问题。

---

## 5. 详细实现设计 (Detailed Implementation)

### 5.1 会话管理与服务层 (`bsk/service.py`)

1. **实现 `sync_session`**：
   ```python
   async def sync_session(
       self,
       key: str,
       *,
       tab_id: int | None = None,
       wait_for: str = "",
       wait_not: str = "",
       timeout_ms: int | None = None,
   ) -> PageObservation:
       """调用 bsk sync --session <sid> --json。
       同步页面 VOM 并激活 daemon 的 target 控制策略 context_id。
       """
   ```
   - 构造 `["sync"]`，附带可选的 `--tab-id`、`--wait-for`、`--wait-not`、`--timeout-ms`；
   - 通过 `self.sessions.execute(session_key, ..., allow_uncertain=True)` 执行；
   - 解析并返回 `PageObservation`。

2. **实现 `open_session`**：
   ```python
   async def open_session(
       self,
       key: str,
       url: str,
       *,
       browser: str | None = None,
       timeout_ms: int | None = None,
   ) -> PageObservation:
       """调用 bsk open <url> --session <sid> --json。
       原子完成打开网页并同步初始上下文。
       """
   ```
   - 若会话未启动则启动，执行 `["open", url]`；
   - 返回初始页面的 `PageObservation`。

3. **`interact` 自动补救与重试**：
   在 `BskService.interact` 中：
   ```python
   auto_synced = False
   try:
       result = await self.sessions.execute(...)
   except BskError as exc:
       if getattr(exc, "reason", "") == "cooperation_sync_required" and not auto_synced:
           self._logger.info("交互操作触发 cooperation_sync_required，尝试自动 sync 后重试")
           await self.sync_session(session_key, tab_id=tab_id)
           result = await self.sessions.execute(...)
           auto_synced = True
       elif getattr(exc, "reason", "") == "element_not_visible" and target and action != "scroll-to":
           ... # 既有 auto_scrolled 逻辑
   ```
   在返回字典中携带 `"auto_synced": auto_synced`。

### 5.2 工具参数与 Schema (`bsk/tools.py`)

1. **`bsk_session` 动作清单扩充**：
   ```python
   TOOL_ACTIONS["bsk_session"] = ("start", "stop", "list", "sync", "open")
   ```
2. **Schema 与参数校验更新**：
   - 为 `TOOL_SCHEMAS["bsk_session"]` 增加 `url` 参数描述（供 `action="open"` 使用）；
   - 在 `_validate_session` 中：
     - 若 `action == "open"`：要求 `url` 必填且为合法非空字符串；
     - 若 `action == "sync"`：允许携带可选的 `tab_id`、`wait_for` 等。

### 5.3 错误分类与提示 (`bsk/errors.py`)

在 `classify` 中处理 `CODE_PERMISSION_DENIED`：
```python
elif reason == "cooperation_sync_required":
    friendly = "当前页面控制权未同步或已失效，请先调用 bsk_session(action='sync') 同步页面控制权后再操作。"
```

### 5.4 调度与展示层 (`main.py`)

1. **`bsk_session` 分支路由**：
   在 `_run_session` 中增加对 `sync` 和 `open` 的分发：
   - `action == "sync"`：调用 `service.sync_session`，渲染返回页面 VOM 摘要；
   - `action == "open"`：调用 `service.open_session`，渲染初始页面 VOM。
2. **交互补救提示显式回显**：
   在 `_run_interact` / `_render_action_result` 中：
   ```python
   notes = []
   if result.get("auto_scrolled"):
       notes.append("目标不在视口内，已自动滚动到可视区域。")
   if result.get("auto_synced"):
       notes.append(
           "检测到页面控制权未同步，已在后台自动执行 sync 补救重试。"
           "注意：后续在页面跳转或导航后，请优先主动调用 bsk_session(action='sync') 同步页面。"
       )
   ```
3. **工具描述微调**：
   - `bsk_session` 文档注明 `sync` 用于同步页面与获取控制权，`open` 用于一步打开并同步；
   - `bsk_page` 文档注明“页面跳转后元素编号与控制权会失效，请在跳转后调用 bsk_session(action='sync') 同步页面”；
   - `bsk_interact` 文档注明“操作前确保已执行过 sync 同步”。

---

## 6. 测试与验证策略 (Testing Strategy)

1. **工具层校验单测 (`tests/test_tools.py`)**：
   - 验证 `bsk_session(action="sync")` 校验通过；
   - 验证 `bsk_session(action="open", url="https://example.com")` 校验通过，缺 url 时报错；
2. **服务层自愈与协同单测 (`tests/test_cooperation_sync.py`)**：
   - Mock 首次执行抛出 `cooperation_sync_required`，验证：
     1) 触发 `sync_session`；
     2) 再次重试原始交互动作；
     3) 返回结果 `auto_synced=True`；
     4) 第二次仍报错时正确向上抛出异常；
3. **展示层回显单测**：
   - 验证 `auto_synced=True` 时成功附加显式提示文本；
4. **既有测试套件回归**：
   - 运行全部已有单测确保无回归破坏。
