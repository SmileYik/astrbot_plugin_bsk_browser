# 标签页闭环感知与清理、截图工具收敛及绝对路径增强设计文档

**文档标识**：`2026-11-15-tab-lifecycle-and-screenshot-consolidation-design`  
**作者**：Antigravity  
**状态**：待用户审批 (Pending Approval)  
**涉及模块**：
- `astrbot_plugin_bsk_browser/bsk/service.py`
- `astrbot_plugin_bsk_browser/bsk/shots.py`
- `astrbot_plugin_bsk_browser/main.py`
- `astrbot_plugin_bsk_browser/bsk/config.py`
- `astrbot_plugin_bsk_browser/metadata.yaml`
- `astrbot_plugin_bsk_browser/_conf_schema.json`
- `astrbot_plugin_bsk_browser/README.md`
- `astrbot_plugin_bsk_browser/skill/bsk-browser/SKILL.md`
- `astrbot_plugin_bsk_browser/skill/browse-baidu.com/SKILL.md`
- `astrbot_plugin_bsk_browser/skill/browse-cn.bing.com/SKILL.md`
- `astrbot_plugin_bsk_browser/tests/`

---

## 1. 意图与核心背景 (Intent & Why)

在最近一轮线上机器人测试中（用户搜索 `gtnh` 并点击第一条百度贴吧搜索结果后滚动截图），暴露出以下问题：
1. **外链新标签页脱管与宿主机桌面残留**：机器人点击搜索结果（包含 `target="_blank"` 的贴吧链接）后，Chrome 打开了新 Tab。但机器人完全未感知新 Tab，焦点停留在后台的原搜索页。会话超时停止后，贴吧标签页由于属于 BrowserSkill 保护的 `observedTabs`，被永久留在宿主机桌面上。
2. **根因定位**：`bsk tab list --json` 返回的实际载荷是 `{"tabs": [...]}` 字典结构。然而现有 `BskService._render_tabs` 中硬编码了 `if not isinstance(data, list): return []`，导致所有标签页查询在运行时全部被解析为空列表。这导致 `detect_new_tabs_and_switch`（新标签检测与焦点自动切换）和 `sweep_agent_tabs`（多余标签清理）全部空转。
3. **截图失败与调用链异常**：由于焦点未切换，原搜索页处于后台遮挡隐藏状态，导致后续全页截图被 Chrome CDP 拦截并报错 `page_hidden`。首轮工具报错中断，未触发发图，引发大模型幻觉回复“截图已发送”；并且因 trace span 数量触达阈值或失败记录残留，让用户困惑。
4. **工具冗余**：目前存在两个截图工具：独立工具 `bsk_screenshot` 与 `bsk_inspect(action="screenshot")`，造成语义割裂与工具说明字符冗余。
5. **路径规范**：目前生成的截图文件路径为相对路径，用户要求统一使用绝对路径以保证各环境调用和发送的确定性。

---

## 2. 目标、非目标与反向目标 (Goals, Non-Goals & Anti-Goals)

### 目标 (Goals)
1. **健壮解析标签页数据**：使 `_render_tabs` 既支持 `{"tabs": [...]}` 字典结构，也兼容裸列表 `[...]`。
2. **全自动新标签感知与切换**：点击外链产生新标签时，自动完成 `tab select <id>`，并向模型返回明确的新标签通知。
3. **彻底清理无残留**：会话关闭（`close_session` / `shutdown` / 超时回收）时，确保当前 Agent Window 内所有派生标签页全量安全关闭，宿主机桌面 0 残留。
4. **截图路径绝对化**：所有截图生成与返回的路径必须是绝对路径（`Path.resolve().absolute()`）。
5. **彻底下线独立工具 `bsk_screenshot`**：仅保留 `bsk_inspect(action="screenshot")`，更新旧工具名单、配置项描述、文档与技能说明。
6. **修复潜在异常与日志规范**：修正 `main.py` 中 `self.logger` 的作用域笔误，严格遵守以 DEBUG 级别记录 bsk 调用日志与工具会话日志。

### 非目标 (Non-Goals)
- 不改动 `bsk` 命令行可执行文件底层 Rust 逻辑。
- 不关闭用户在个人浏览器窗口中手动创建的普通标签页（仅清理 Agent Window 受控标签页）。

### 反向目标 (Anti-Goals)
- 严禁因标签清理误伤用户未授权的个人浏览标签。
- 严禁在页面仍处于后台被遮挡时盲目调用整页截图导致 `page_hidden` 报错。

---

## 3. 架构对比与方案选型 (Approaches)

在方案沟通中，考虑了两种演进路径：

| 方案 | 标签管理策略 | 截图工具治理 | 优劣与裁决 |
| :--- | :--- | :--- | :--- |
| **方案 1：智能自治闭环方案（选中）** | 修复解析；点击后**自动切焦点**并通知模型；会话结束**全量扫除派生标签** | 彻底下线 `bsk_screenshot`；统一采用 `bsk_inspect(action="screenshot")` 且全链路采用绝对路径 | **选中**：彻底根除贴吧页面残留和前台遮挡导致的 `page_hidden`，模型心智负担低，代码完全对齐新版规范。 |
| **方案 2：显式受控与人工介入方案** | 修复解析；点击后不自动切焦点，仅提示模型自行调用 `bsk_tabs` 切页；不主动全量清理 | 同样下线旧工具并采用绝对路径 | **未选中**：模型需反复执行决策步骤，极易遗忘切换或遗忘清理，再次发生桌面残留与 `page_hidden`。 |

---

## 4. 详细技术实现方案 (The How)

### 4.1 修复标签列表解析 (`bsk/service.py`)
- 重构 `_render_tabs(data: Any) -> list[dict[str, Any]]`：
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
  提取并规范化每个条目的 `tab_id`、`title`、`url`、`active`、`window_id`。

### 4.2 标签页自动切换与会话销毁全量扫尾 (`bsk/service.py`)
- **点击自动切换**：
  `detect_new_tabs_and_switch(key: str)` 在 `current_tab_ids` 发现 `new_ids` 时：
  1. 调用 `self.tabs(session_key, "select", tab_id=new_tab_id)` 切换前台焦点；
  2. 将新 ID 记入 `_session_known_tabs`；
  3. 返回包含 `new_tab_id`、`title`、`url`、`total_tabs` 的信息供渲染。
- **全量无残留扫尾 (`sweep_agent_tabs`)**：
  在 `close_session` 及 `shutdown` 阶段，遍历 `tabs(session_key, "list", scope="agent")` 获得的所有标签。将其余或全部派生标签按 ID 依次执行 `tabs(session_key, "close", tab_id=tid)`，打破 BrowserSkill 的 `dropOnly` 保护陷阱，保证会话终止时窗口彻底关闭。

### 4.3 截图工具精简与彻底下线 `bsk_screenshot` (`main.py`, `bsk/config.py` 等)
- **删除 `main.py` 中的 `bsk_screenshot`**：
  - 移除 `@filter.llm_tool("bsk_screenshot") async def bsk_screenshot(...)`；
  - 从 `LEGACY_TOOL_NAMES` 元组中移除 `"bsk_screenshot"`；
  - 常驻旧工具数量由 4 个减为 3 个（`bsk_close`, `bsk_status`, `bsk_logs`）；
  - 更新 `main.py` 顶部注释与工具注册计数。
- **配置与元数据同步**：
  - 更新 `bsk/config.py` 中的常量与工具说明文本；
  - 更新 `_conf_schema.json`、`metadata.yaml`、`README.md`。

### 4.4 截图路径绝对化 (`bsk/shots.py`, `bsk/service.py`)
- 在 `bsk/shots.py:make_shot_path` 中，确保返回的 `Path` 经过 `.resolve().absolute()` 处理；
- 在 `service.py:screenshot_ex` 中，确保生成和返回给 `ShotPayload` 的路径字符串为纯绝对路径（例如 `/AstrBot/data/temp/...` 或 `/run/media/...`）；
- `bsk_inspect(action="screenshot")` 无论是发送图片 `event.image_result(abs_path)` 还是返回给模型的文件路径描述，均使用此绝对路径。

### 4.5 代码修复与日志要求
- 修复 `main.py` 中 `self.logger.debug` 笔误，修正为全局统一的 `astrbot_logger.debug`；
- 遵循 `AGENTS.md`：保持 DEBUG 等级输出所有 bsk 指令输入/输出及工具调用会话/名称。

### 4.6 SKILL 文档维护 (`astrbot_plugin_bsk_browser/skill/`)
- `bsk-browser/SKILL.md`：
  - 删除 `bsk_screenshot` 相关描述，统一指导使用 `bsk_inspect(action="screenshot", full_page=...)`；
  - 补充说明截图返回的绝对路径以及点击链接自动切 Tab 的工作流；
  - 强调自主关闭派生标签页的最佳实践。
- `browse-baidu.com/SKILL.md` 与 `browse-cn.bing.com/SKILL.md`：
  - 更新关于搜索结果链接点击后新标签页产生时的感知与操作说明；
  - 保持准确、精炼、简洁。

---

## 5. 验证协议与测试计划 (Verification Protocol)

1. **单元测试与回归测试**：
   - `tests/test_tab_detection.py`：测试 `_render_tabs` 支持 `{"tabs": [...]}` 字典结构，并验证新标签感知与 `tab select` 触发；
   - `tests/test_tab_lifecycle_cleanup.py`：测试 `sweep_agent_tabs` 正确提取多个标签并逐一调用关闭；
   - `tests/test_inspect_screenshot_image.py`：测试 `bsk_inspect(action="screenshot")` 正确产出绝对路径并触发图片发送；
   - 验证旧工具列表中不再有 `bsk_screenshot`，且 `main.py` 语法与工具装载正常。
2. **端到端校验**：
   - 运行项目全量测试集：`pytest astrbot_plugin_bsk_browser/tests` 保证 100% 通过。
3. **Git 交付**：
   - 按照规范在全部修改与验证完成后 commit 提交至 `astrbot_plugin_bsk_browser` 仓库。
