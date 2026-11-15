# 冗余旧工具清理与独立配置注册控制实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底移除 `astrbot_plugin_bsk_browser` 中的 5 个冗余旧工具（`bsk_open`、`bsk_read`、`bsk_act`、`bsk_close`、`bsk_logs`）及废弃配置项，通过独立配置项 `enable_status` 和 `enable_evaluate` 控制保留工具的注册，并同步更新技能文档、元数据与测试套件。

**Architecture:** 从配置层（`bsk/config.py` 和 `_conf_schema.json`）删除旧分层开关并引入 `enable_status`；在插件核心层（`main.py`）清理冗余工具函数与常数列表，在 `initialize()` 中通过 `tool.active = False` 精确控制 `bsk_status` 和 `bsk_evaluate` 的模型注册；同步更新技能文档与测试用例，保证全链路 0 残留引用与 100% 测试通过。

**Tech Stack:** Python 3.12+, AstrBot 插件体系 (`@filter.llm_tool`, `llm_tools.get_func`), pytest.

**Spec:** [`astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-legacy-tools-cleanup-design.md`](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-legacy-tools-cleanup-design.md)

## Global Constraints

- 严禁修改 8 个标准多动作工具（`bsk_session`, `bsk_page`, `bsk_inspect`, `bsk_debug`, `bsk_load_tools`, `bsk_interact`, `bsk_tabs`, `bsk_assist`）的接口与内部实现。
- 日志规范（`AGENTS.md`）：使用 AstrBot 日志系统以 DEBUG 等级输出 bsk 指令调用（含输入与输出）及工具调用日志（`_trace_tool_call`）。
- 技能文档规范（`AGENTS.md`）：在精炼准确的前提下，维护 `skill/bsk-browser/SKILL.md`。
- 版本管理（`AGENTS.md`）：每个 task 完成后都需要 commit `astrbot_plugin_bsk_browser` 仓库内容。

## Review Focus

1. **配置默认值与解析兼容**：旧配置中若仍存留 `legacy_tools` 键，不应导致 `parse_settings` 报错崩溃。
2. **`enable_status=False` 停用生效**：在 AstrBot 启动时，`enable_status=False` 必须确保 `bsk_status` 的 `tool.active` 被置为 `False`。
3. **`enable_evaluate=False` 停用生效**：默认情况下 `enable_evaluate=False`，必须确保 `bsk_evaluate` 的 `tool.active` 被置为 `False`，不向模型暴露且不占 token。
4. **全项目无悬空引用**：代码、文档、测试中不得遗留对 `bsk_open`、`bsk_read`、`bsk_act`、`bsk_close`、`bsk_logs` 的引用。
5. **测试覆盖与断言完整**：原有工具数量契约测试（如 15 工具）必须更新为对应新状态，全量 pytest 必须全绿。

---

### Task 1: 配置模块与 Schema 重构 (`bsk/config.py` & `_conf_schema.json`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/config.py:95-135,670-785,830-900`
- Modify: `astrbot_plugin_bsk_browser/_conf_schema.json:110-140`
- Modify: `astrbot_plugin_bsk_browser/tests/test_config.py`

**Interfaces:**
- Consumes: `Settings` 数据类与 `parse_settings(raw: dict | None, *, data_dir: str = "") -> Settings`
- Produces: `Settings.enable_status: bool = True`，移除 `Settings.legacy_tools` 与 `Settings.legacy_fringe_tools`

- [x] **Step 1: 在 `tests/test_config.py` 中编写 `enable_status` 的失败测试并移除已废弃字段测试**

```python
# tests/test_config.py
def test_enable_status_default():
    s = parse_settings({})
    assert s.enable_status is True

def test_enable_status_explicit_false():
    s = parse_settings({"enable_status": False})
    assert s.enable_status is False

def test_enable_status_from_string():
    s = parse_settings({"enable_status": "false"})
    assert s.enable_status is False
```

- [x] **Step 2: 运行测试验证失败**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_config.py -k "test_enable_status" -v`  
Expected: FAIL (`AttributeError: 'Settings' object has no attribute 'enable_status'`)

- [x] **Step 3: 更新 `bsk/config.py` 与 `_conf_schema.json`**

1. 在 `bsk/config.py` 中：
   - 增加常量 `DEFAULT_ENABLE_STATUS: bool = True`；
   - 移除 `DEFAULT_LEGACY_TOOLS`、`DEFAULT_LEGACY_FRINGE_TOOLS` 常量与相关注释；
   - 在 `Settings` 类中移除 `legacy_tools: bool`、`legacy_fringe_tools: bool` 字段，新增 `enable_status: bool = True`；
   - 在 `parse_settings` 中移除 `legacy_tools` 与 `legacy_fringe_tools` 的读取，增加：
     ```python
     enable_status=_as_bool(raw.get("enable_status"), DEFAULT_ENABLE_STATUS)
     ```
2. 在 `_conf_schema.json` 中：
   - 删除 `legacy_tools` 与 `legacy_fringe_tools` 定义；
   - 新增 `enable_status`：
     ```json
     "enable_status": {
       "description": "注册环境自检工具（bsk_status）",
       "type": "bool",
       "default": true,
       "hint": "默认开启。向模型注册 bsk_status 工具，用于检查 bsk 命令行、浏览器扩展连接及会话状态。若不需要可关闭以节省模型提示词。"
     }
     ```
   - 调整 `enable_evaluate` 的提示文本，明确指明“开启后向模型注册并允许使用 `bsk_evaluate` 工具”。

- [x] **Step 4: 运行 `test_config.py` 验证通过**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_config.py -v`  
Expected: PASS

- [x] **Step 5: 提交配置层变更**

```bash
git add astrbot_plugin_bsk_browser/bsk/config.py astrbot_plugin_bsk_browser/_conf_schema.json astrbot_plugin_bsk_browser/tests/test_config.py
git commit -m "refactor(config): add enable_status and remove legacy_tools/legacy_fringe_tools"
```

---

### Task 2: 移除 5 个冗余旧工具并重构注册控制 (`main.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/main.py:75-145,630-660,740-785,2130-2480`
- Modify: `astrbot_plugin_bsk_browser/tests/verify_evaluate_gate.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_tool_logging.py`

**Interfaces:**
- Consumes: `Settings.enable_status`, `Settings.enable_evaluate`
- Produces: 彻底移除 `bsk_open`, `bsk_read`, `bsk_act`, `bsk_close`, `bsk_logs` 方法；`initialize()` 精准控制 `bsk_status` 与 `bsk_evaluate` 的 `tool.active`

- [x] **Step 1: 编写工具注册与停用的单元测试**

在 `tests/test_tool_registration.py`（或在 `test_tool_logging.py` 中）：
验证：
1. 默认配置下：`bsk_status` 的 `active` 为 `True`，`bsk_evaluate` 的 `active` 为 `False`；
2. 当 `enable_status=False` 时：`bsk_status` 的 `active` 为 `False`；
3. 当 `enable_evaluate=True` 时：`bsk_evaluate` 的 `active` 为 `True`；
4. `main.py` 类中不存在 `bsk_open`、`bsk_read`、`bsk_act`、`bsk_close`、`bsk_logs` 属性。

- [x] **Step 2: 运行测试验证失败**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_tool_registration.py -v`  
Expected: FAIL（属性仍存在或停用逻辑未触发）

- [x] **Step 3: 修改 `main.py` 实施清理与注册控制**

1. 移除 `LEGACY_CORE_TOOL_NAMES`、`LEGACY_FRINGE_TOOL_NAMES`、`LEGACY_TOOL_NAMES` 常量定义；
2. 定义 `OPTIONAL_STANDALONE_TOOLS: tuple[str, ...] = ("bsk_status", "bsk_evaluate")`；
3. 移除 `_deactivate_legacy_tools` 方法；
4. 在 `initialize()` 中替换为独立工具开关逻辑：
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
5. 从 `main.py` 中彻底删除以下 5 个方法定义及其装饰器：
   - `bsk_open`
   - `bsk_read`
   - `bsk_act`
   - `bsk_close`
   - `bsk_logs`
6. 更新 `test_tool_logging.py`，移除对这 5 个已删除工具的追踪断言，仅保留 8 个新工具及 `bsk_status`、`bsk_evaluate`。

- [x] **Step 4: 运行测试验证通过**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_tool_registration.py astrbot_plugin_bsk_browser/tests/test_tool_logging.py -v`  
Expected: PASS

- [x] **Step 5: 提交插件核心变更**

```bash
git add astrbot_plugin_bsk_browser/main.py astrbot_plugin_bsk_browser/tests/test_tool_logging.py astrbot_plugin_bsk_browser/tests/test_tool_registration.py
git commit -m "refactor(main): remove 5 legacy tools and manage status/evaluate registration via settings"
```

---

### Task 3: 清理废弃测试与更新测试契约 (`tests/`)

**Files:**
- Delete: `astrbot_plugin_bsk_browser/tests/verify_legacy_groups.py`
- Delete: `astrbot_plugin_bsk_browser/tests/verify_logs_tool.py`
- Modify: `astrbot_plugin_bsk_browser/tests/verify_compliance.py`
- Modify: `astrbot_plugin_bsk_browser/tests/verify_astrbot_contract.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_service_sync.py`
- Modify: `astrbot_plugin_bsk_browser/tests/verify_evaluate_gate.py`

**Interfaces:**
- Consumes: 更新后的 `main.py` 与 `bsk/config.py`
- Produces: 干净的测试套件，无废弃测试文件，契约检查全绿

- [x] **Step 1: 删除废弃测试文件**

Run: `git rm astrbot_plugin_bsk_browser/tests/verify_legacy_groups.py astrbot_plugin_bsk_browser/tests/verify_logs_tool.py`

- [x] **Step 2: 更新引用了旧工具的测试文件**

1. 在 `verify_compliance.py` / `verify_astrbot_contract.py` 中：
   - 更新工具总数校验（原 15 个工具已改为：8 个标准工具 + 2 个独立工具 = 10 个定义工具）；
   - 移除对 `bsk_open`、`bsk_read`、`bsk_act`、`bsk_close`、`bsk_logs` 的声明检查；
2. 在 `test_service_sync.py` 中：
   - 检查是否有对旧工具调用的 mock，若有则更新为对新工具（`observe` / `act` / `close_session`）的测试或直接移除；
3. 在 `verify_evaluate_gate.py` 中：
   - 验证 `enable_evaluate=False` 时 `active=False`；`enable_evaluate=True` 时 `active=True` 且运行时权限门禁正常工作。

- [x] **Step 3: 运行完整测试套件**

Run: `pytest astrbot_plugin_bsk_browser/tests -v`  
Expected: 全量 PASS，无断言失败

- [x] **Step 4: 提交测试套件清理与更新**

```bash
git add astrbot_plugin_bsk_browser/tests/
git commit -m "test: remove obsolete legacy tests and update tool contract tests"
```

---

### Task 4: 技能文档与元数据文档全面同步

**Files:**
- Modify: `astrbot_plugin_bsk_browser/skill/bsk-browser/SKILL.md`
- Modify: `astrbot_plugin_bsk_browser/metadata.yaml`
- Modify: `astrbot_plugin_bsk_browser/README.md`
- Modify: `astrbot_plugin_bsk_browser/ARCHITECTURE.md`
- Modify: `astrbot_plugin_bsk_browser/CHANGELOG.md`
- Modify: `astrbot_plugin_bsk_browser/tests/test_skills_doc.py`

**Interfaces:**
- Consumes: 设计文档与最终保留的 8+2 工具体系
- Produces: 符合 `AGENTS.md` 规范的精炼准确的技能文档与项目说明文档

- [x] **Step 1: 编写技能文档测试验证**

在 `tests/test_skills_doc.py` 中：
验证 `skill/bsk-browser/SKILL.md` 中不再出现 `bsk_close`、`bsk_logs`、`bsk_open`、`bsk_read`、`bsk_act`，且包含 `bsk_status`。

- [x] **Step 2: 运行测试验证当前状态**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_skills_doc.py -v`

- [x] **Step 3: 更新 `skill/bsk-browser/SKILL.md`**

1. 修改第 3 节核心准则中的“及时释放资源”：
   - 将 `- 停止整个会话：bsk_session(action="stop") 或 bsk_close()` 改为纯粹的 `- 停止整个会话：bsk_session(action="stop")（底层会自动清扫全部残留标签页，确保宿主机零孤儿窗口残留）。`
2. 移除原第 9 节“兼容旧工具”（`bsk_close`, `bsk_status`, `bsk_logs`）；
3. 替换为独立扩展工具说明：
   ```markdown
   9. **独立扩展与诊断工具**：
      - `bsk_status`：检查环境与连接状态（需配置 `enable_status=true`，默认开启；在环境异常或排查故障时调用）。
      - `bsk_evaluate`：执行自定义 JavaScript 表达式（高危工具，需配置 `enable_evaluate=true` 并经管理员授权，默认关闭）。
   ```
4. 确保语言精炼准确，满足 `AGENTS.md` 要求。

- [x] **Step 4: 更新 `metadata.yaml`、`README.md`、`ARCHITECTURE.md`、`CHANGELOG.md`**

1. `metadata.yaml`：
   - 更新工具数量与工具描述（8 个标准工具 + 1 个默认自检工具 `bsk_status` = 9 个默认注册工具；`bsk_debug` 按需，`bsk_evaluate` 独立高危）；
   - 彻底删除 `legacy_tools` / `legacy_fringe_tools` 的描述；
2. `README.md` & `ARCHITECTURE.md`：
   - 更新工具结构图与说明表格，抹去 5 个废弃旧工具；
   - 更新配置项表格，增加 `enable_status`，更新 `enable_evaluate` 说明；
3. `CHANGELOG.md`：
   - 记录新版本变更：彻底移除 5 个冗余旧工具，将 `bsk_status` 与 `bsk_evaluate` 改为独立配置控制注册。

- [x] **Step 5: 运行技能文档测试验证**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_skills_doc.py -v`  
Expected: PASS

- [x] **Step 6: 提交文档同步变更**

```bash
git add astrbot_plugin_bsk_browser/skill/ astrbot_plugin_bsk_browser/metadata.yaml astrbot_plugin_bsk_browser/README.md astrbot_plugin_bsk_browser/ARCHITECTURE.md astrbot_plugin_bsk_browser/CHANGELOG.md astrbot_plugin_bsk_browser/tests/test_skills_doc.py
git commit -m "docs: sync skills, metadata, architecture and changelog for legacy tools cleanup"
```

---

### Task 5: 全局无残留扫描与全量验收验证

**Files:**
- Whole repository inspection

- [x] **Step 1: 全局扫描废弃工具名残留**

在项目根目录运行 grep 检查是否有任何无意保留的代码或调用：
```bash
git -C astrbot_plugin_bsk_browser grep -E "bsk_open|bsk_read|bsk_act|bsk_close|bsk_logs|legacy_tools|legacy_fringe_tools"
```
（除 CHANGELOG 历史记录外，代码、当前文档、测试中应为 0 匹配）

- [x] **Step 2: 运行全量单元测试与集成测试**

Run: `pytest astrbot_plugin_bsk_browser/tests -v`  
Expected: 全部测试 PASS（预计 900+ 个用例全绿），0 failed，0 warning（除不可避免的 pytest cache warning 外）。

- [x] **Step 3: 运行 git status 确认工作区完全干净**

Run: `git -C astrbot_plugin_bsk_browser status`  
Expected: 工作树干净，所有 commit 已完成。
