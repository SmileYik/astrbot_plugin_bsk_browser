# 冗余旧工具清理与独立配置注册控制设计文档

**文档标识**：`2026-11-15-legacy-tools-cleanup-design`  
**作者**：Antigravity  
**状态**：待用户审批 (Pending Approval)  
**涉及模块**：
- `astrbot_plugin_bsk_browser/main.py`
- `astrbot_plugin_bsk_browser/bsk/config.py`
- `astrbot_plugin_bsk_browser/_conf_schema.json`
- `astrbot_plugin_bsk_browser/metadata.yaml`
- `astrbot_plugin_bsk_browser/README.md`
- `astrbot_plugin_bsk_browser/ARCHITECTURE.md`
- `astrbot_plugin_bsk_browser/CHANGELOG.md`
- `astrbot_plugin_bsk_browser/skill/bsk-browser/SKILL.md`
- `astrbot_plugin_bsk_browser/tests/`

---

## 1. 意图与背景 (Intent & Why)

`astrbot_plugin_bsk_browser` 现已全面演进到以 8 个标准多动作工具（`bsk_session`、`bsk_page`、`bsk_inspect`、`bsk_debug`、`bsk_load_tools`、`bsk_interact`、`bsk_tabs`、`bsk_assist`）为核心的架构体系。

在之前的兼容期内，项目中维护了一组旧版单动作工具（`LEGACY_TOOL_NAMES` 共 7 个），并配有 `legacy_tools` 与 `legacy_fringe_tools` 两个分层开关。然而：
1. **工具冗余与提示词浪费**：其中 5 个工具（`bsk_open`、`bsk_read`、`bsk_act`、`bsk_close`、`bsk_logs`）的能力已 100% 被新工具原生覆盖（分别对应 `bsk_page/bsk_session`、`bsk_inspect(action="observe")`、`bsk_interact`、`bsk_session(action="stop")`、`bsk_inspect(action="console"|"network")`）。保留它们不仅在开启时产生大量无谓的系统提示词（prompt token）开销，还会造成模型在多工具选择时的心智困惑与误调用。
2. **特殊能力的独立性**：旧工具中的另外 2 个工具（`bsk_status` 和 `bsk_evaluate`）具备特殊定位：
   - `bsk_status`：提供底层 bsk 运行环境自检、扩展连通性检查与版本诊断，安全只读且无副作用，在新工具体系中尚无对等 action。
   - `bsk_evaluate`：执行任意 JavaScript 脚本的高危能力，属于插件独有扩展能力，无直接新工具替代。
3. **治理目标**：彻底清理 5 个冗余旧工具及对应的旧分层配置项（`legacy_tools`、`legacy_fringe_tools`），保留 `bsk_status` 与 `bsk_evaluate`，并通过独立配置项直接控制其是否向大模型注册激活（`tool.active`），实现极简、清晰、安全的工具链体系。

---

## 2. 目标、非目标与反向目标 (Goals, Non-Goals & Anti-Goals)

### 目标 (Goals)
1. **彻底下线 5 个冗余旧工具**：从 `main.py` 中彻底删除 `bsk_open`、`bsk_read`、`bsk_act`、`bsk_close`、`bsk_logs` 的 `@filter.llm_tool` 声明与对应处理逻辑。
2. **清理过时配置项与逻辑**：从 `_conf_schema.json`、`bsk/config.py` 及 `main.py` 中彻底移除 `legacy_tools`、`legacy_fringe_tools`、`LEGACY_CORE_TOOL_NAMES`、`LEGACY_FRINGE_TOOL_NAMES`、`LEGACY_TOOL_NAMES` 等常量与分组停用逻辑。
3. **独立配置控制注册**：
   - 新增 `enable_status` 配置项（布尔值，默认 `true`）：控制是否向模型注册 `bsk_status` 工具。为 `false` 时在初始化阶段设置 `tool.active = False`。
   - 强化 `enable_evaluate` 配置项（布尔值，保持默认 `false`）：由仅在运行时拦截，升级为在初始化阶段联动控制 `bsk_evaluate` 的注册状态（为 `false` 时直接设置 `tool.active = False`，彻底避免提示词占用）；同时保留运行时的安全鉴权与 `evaluate_require_admin` 限制。
4. **同步技能文档**：更新 `skill/bsk-browser/SKILL.md`，彻底移除已下线的旧工具（如 `bsk_close`、`bsk_logs`），更新 `bsk_status` 与 `bsk_evaluate` 的可选说明，确保符合精炼、准确的原则。
5. **同步项目文档与元数据**：更新 `README.md`、`metadata.yaml`、`ARCHITECTURE.md`、`CHANGELOG.md` 中的工具总览与配置项说明。
6. **重构与精简测试用例**：删除专门针对旧工具的测试文件（如 `tests/verify_legacy_groups.py`、`tests/verify_logs_tool.py`），更新配置测试、日志追踪测试和合规检查测试，确保全套 pytest 100% 通过。

### 非目标 (Non-Goals)
- 不修改 8 个新多动作工具（`bsk_session`、`bsk_page` 等）的 schema、action 列表及内部处理逻辑。
- 不改动 `bsk_status` 的诊断信息输出格式与 `bsk_evaluate` 的执行逻辑。
- 不修改底层的 `bsk` 二进制与跨进程通信协议。

### 反向目标 (Anti-Goals)
- 严禁将 `bsk_status` 与 `bsk_evaluate` 捆绑在同一个开关中，避免为了诊断排查而被迫暴露高危脚本执行能力。
- 严禁在删除工具后留下失效的引用、悬空导入或断裂的单元测试。

---

## 3. 架构对比与方案选型 (Approaches)

在工具注册控制方案上，进行了以下对比：

| 方案 | 控制维度与机制 | 优劣分析 | 选型结论 |
| :--- | :--- | :--- | :--- |
| **方案 A：独立粒度开关控制注册（选中）** | 新增 `enable_status`（默认 `true`），强化 `enable_evaluate`（默认 `false`）。两者各自独立控制对应工具的 `tool.active`。 | **优点**：安全隔离性好；`bsk_status` 作为安全诊断工具默认可用，`bsk_evaluate` 作为高危脚本默认不向模型注册、零 token 浪费；权责极其清晰。<br>**缺点**：相比单一开关多一个配置项（但在 schema 层面清晰易懂）。 | **选中** |
| **方案 B：单一扩展工具开关控制注册** | 使用单一配置项（如 `enable_standalone_tools`）统一控制两个工具的注册。 | **优点**：配置项数量少 1 个。<br>**缺点**：违背最小权限原则与安全隔离原则。用户若仅想开启状态自检，就会被迫向模型暴露任意 JS 执行能力；若关掉又失去诊断能力。 | **未选中** |

---

## 4. 详细技术实现方案 (The How)

### 4.1 配置模块重构 (`bsk/config.py` & `_conf_schema.json`)

1. **`bsk/config.py`**：
   - 移除常量：`DEFAULT_LEGACY_TOOLS`、`DEFAULT_LEGACY_FRINGE_TOOLS`。
   - 新增常量：`DEFAULT_ENABLE_STATUS = True`。
   - `Settings` 数据类：
     - 移除字段：`legacy_tools: bool`、`legacy_fringe_tools: bool`。
     - 新增字段：`enable_status: bool = True`。
     - 保留字段：`enable_evaluate: bool = False`、`evaluate_require_admin: bool = True`。
   - `parse_settings` 解析逻辑：
     - 增加 `enable_status=_as_bool(raw.get("enable_status"), DEFAULT_ENABLE_STATUS)`。
     - 移除对 `legacy_tools`、`legacy_fringe_tools` 的读取。
   - 保持现有的 `enable_evaluate` 安全校验提示（若开启 evaluate 且关闭管理员则输出告警）。

2. **`_conf_schema.json`**：
   - 删除 `legacy_tools` 与 `legacy_fringe_tools` 配置项定义。
   - 增加 `enable_status`：
     ```json
     "enable_status": {
       "description": "注册环境自检工具（bsk_status）",
       "type": "bool",
       "default": true,
       "hint": "默认开启。向模型注册 bsk_status 工具，用于检查 bsk 命令行、浏览器扩展连接及会话状态。若不需要可关闭以节省模型提示词。"
     }
     ```
   - 保持并微调 `enable_evaluate` 的描述，明确写明“开启后向模型注册 `bsk_evaluate` 工具（默认关闭且不注册）”。

### 4.2 插件核心与工具注册重构 (`main.py`)

1. **常量与清单清理**：
   - 移除 `LEGACY_CORE_TOOL_NAMES`、`LEGACY_FRINGE_TOOL_NAMES`、`LEGACY_TOOL_NAMES`。
   - 保留 `NEW_TOOL_NAMES`。
   - 定义独立工具列表常量：`OPTIONAL_STANDALONE_TOOLS: tuple[str, ...] = ("bsk_status", "bsk_evaluate")`。
2. **初始化生命周期改造 (`initialize`)**：
   - 移除 `_deactivate_legacy_tools` 方法。
   - 替换为精准的独立工具停用逻辑：
     ```python
     from astrbot.core.provider.register import llm_tools

     # 控制 bsk_status 注册
     if not self.settings.enable_status:
         status_tool = llm_tools.get_func("bsk_status")
         if status_tool is not None:
             status_tool.active = False
             astrbot_logger.debug("[bsk_browser] 已停用工具 bsk_status（配置项 enable_status=false）")

     # 控制 bsk_evaluate 注册
     if not self.settings.enable_evaluate:
         eval_tool = llm_tools.get_func("bsk_evaluate")
         if eval_tool is not None:
             eval_tool.active = False
             astrbot_logger.debug("[bsk_browser] 已停用工具 bsk_evaluate（配置项 enable_evaluate=false）")
     ```
3. **函数工具下线**：
   - 彻底删除以下 5 个方法定义及其装饰器：
     - `bsk_open`
     - `bsk_read`
     - `bsk_act`
     - `bsk_close`
     - `bsk_logs`
   - 保留并维护：
     - `bsk_status`（及其静态辅助方法 `_render_status`）
     - `bsk_evaluate`（及其权限检查方法 `_evaluate_denied`）
4. **日志要求遵循 (`AGENTS.md`)**：
   - 严格保留并遵循以 DEBUG 等级输出工具被调用日志（`_trace_tool_call` 装饰器）与 bsk 指令调用日志。

### 4.3 技能文档更新 (`skill/bsk-browser/SKILL.md`)

1. **会话释放说明精简**：
   - 将原 `bsk_session(action="stop") 或 bsk_close()` 改为纯粹的 `bsk_session(action="stop")`，消除对已下线工具的引导。
2. **工具箱清单更新**：
   - 移除原第 9 节“兼容旧工具”（曾列出 `bsk_close`、`bsk_status`、`bsk_logs`）。
   - 将其重构为“独立自检与扩展工具”：
     - `bsk_status`：检查环境与连接状态（需 `enable_status=true`，默认开启）。
     - `bsk_evaluate`：执行自定义 JavaScript 表达式（高危工具，需 `enable_evaluate=true`，默认关闭）。

### 4.4 项目元数据与文档同步

1. **`metadata.yaml`**：
   - 更新工具数量描述：默认注册 8 个标准工具（其中 `bsk_debug` 默认按需加载）+ 1 个自检工具（`bsk_status`），共 9 个常驻/按需工具；`bsk_evaluate` 默认关闭。
   - 移除 `legacy_tools` / `legacy_fringe_tools` 的提及。
2. **`README.md` & `ARCHITECTURE.md`**：
   - 更新工具架构图与工具列表表格，彻底抹除 5 个旧工具。
   - 更新配置项说明表格，反映 `enable_status` 与 `enable_evaluate` 的注册行为。
3. **`CHANGELOG.md`**：
   - 记录本次重大清理：下线 5 个废弃旧工具，重构独立配置控制注册体系。

### 4.5 测试套件重构 (`tests/`)

1. **删除废弃测试文件**：
   - `tests/verify_legacy_groups.py`（针对旧分层停用逻辑的校验）。
   - `tests/verify_logs_tool.py`（针对已下线的独立 `bsk_logs` 工具）。
2. **更新现有测试用例**：
   - `tests/test_config.py`：测试 `enable_status` 的默认值、显式布尔解析，移除 `legacy_tools`/`legacy_fringe_tools` 的测试。
   - `tests/test_tool_logging.py`：移除对 `bsk_open`、`bsk_read`、`bsk_act`、`bsk_close`、`bsk_logs` 的追踪测试，保留 8 个新工具及 `bsk_status`、`bsk_evaluate`。
   - `tests/verify_evaluate_gate.py`：验证 `enable_evaluate` 对注册与运行时的拦截效果。
   - `tests/verify_compliance.py`、`tests/verify_astrbot_contract.py`：更新工具数量断言与契约检查。

---

## 5. 交付物与验证规范 (Deliverables & Verification)

1. **代码与配置一致性**：`pytest astrbot_plugin_bsk_browser/tests` 全部通过，无断言失败与未捕获异常。
2. **无残留引用**：全项目 grep 确认无任何悬空的 `bsk_open`、`bsk_read`、`bsk_act`、`bsk_close`、`bsk_logs` 工具调用或注册逻辑。
3. **Git 提交**：遵循 `AGENTS.md` 规范，任务完成后以规范的 conventional commit 提交所有变更。
