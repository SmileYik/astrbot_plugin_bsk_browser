# BskCli 语义化包装层下沉与 Service 层解耦重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `./bsk` CLI 的所有基础原子命令全面封装进 `BskCli` (`bsk/cli.py`)，将复合生命周期逻辑 `close_tab_safe` 收拢至 `SessionManager` (`bsk/session.py`) 并提供 `execute_action` 调度能力，彻底消灭 `BskService` (`bsk/service.py`) 中的 CLI 命令行字符串手动拼装。

**Architecture:** 
1. `BskCli` 作为对 `./bsk` 可执行文件纯粹的强类型 Python SDK 封装层，1:1 映射并承载所有原子子命令的参数装配与底层执行；
2. `SessionManager` 负责管理会话池生命周期、按 Key 互斥锁、失效自动重建与重试保障，提供 `close_tab_safe` 复合清理与 `execute_action` 异步派发机制；
3. `BskService` 彻底剥离参数拼接逻辑，纯粹专注于上层业务编排、面向模型的文案组织与上下文截断控制。

**Tech Stack:** Python 3.10+, asyncio, pytest, bsk CLI

**Spec:** `astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-16-bsk-cli-refactor-design.md`

## Global Constraints

- **Single Repository**: 仅修改 `astrbot_plugin_bsk_browser` 仓库；
- **Logging**: bsk 调用与工具执行维持 AstrBot 日志系统的 DEBUG 级别输出；
- **Attribution**: 保留原仓库原作者署名，增加 `SmileYik`；
- **Skill Docs**: 修改后维护 `astrbot_plugin_bsk_browser/skills/` 中的 SKILL 文档并保持一致；
- **Zero Raw CLI String in Service**: `service.py` 内部不得再保留任何原始子命令名称与选项字符串的列表拼装。

## Review Focus

1. **Session Rebuild Retry with New ID**: `execute_action` 在遭遇 `BskSessionGone` 重启会话后，必须确保重试传入的是全新创建的 `session.session_id`，而非失效的旧 ID；
2. **Uncertain State Write-Blocking**: `execute_action` 必须严格遵循 `allow_uncertain` 标志，在不确定态下坚决阻断写操作；
3. **Fill Empty String Preservation**: `cli.fill(..., value="")` 必须正确输出 `--value ""` 以支持清空输入框，不得被过滤丢失；
4. **Close Tab Safe Sequence Integrity**: `SessionManager.close_tab_safe` 必须先尝试 `select_tab` 激活聚焦，再通过 `sync_tab` 换取有效 `observation_id`，最终带凭证调用 `close_tab`；
5. **Backwards Compatibility of `sessions.execute`**: 原有 `sessions.execute(key, args_builder)` 必须继续可用且委托至 `execute_action`，防止破坏外部调用。

---

### Task 1: BskCli 封装导航、观察与页面读取原子命令

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/cli.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_cli_wrapper.py`

**Interfaces:**
- Consumes: `BskCli._execute(args, timeout, raise_on_error, expect_json)`
- Produces: 
  - `BskCli.navigate(self, session: str, target: str, *, observation: str | None = None, wait_until: str = "load", timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 45.0, raise_on_error: bool = False) -> BskResult`
  - `BskCli.reload(self, session: str, *, hard: bool = False, wait_until: str = "load", timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 15.0, raise_on_error: bool = False) -> BskResult`
  - `BskCli.wait_for_navigation(self, session: str, *, wait_until: str = "load", timeout_ms: int = 30000, tab_id: int | None = None, timeout: float = 35.0, raise_on_error: bool = False) -> BskResult`
  - `BskCli.observe(self, session: str, *, cursor: str = "", max_depth: int | None = None, max_tokens: int | None = None, probe_hover: bool = False, debug_surfaces: bool = False, tab_id: int | None = None, timeout: float = 15.0, raise_on_error: bool = False) -> BskResult`
  - `BskCli.snapshot(self, session: str, *, max_depth: int | None = None, max_tokens: int | None = None, tab_id: int | None = None, timeout: float = 15.0, raise_on_error: bool = False) -> BskResult`
  - `BskCli.get_html(self, session: str, *, ref: str = "", max_bytes: int = 524288, out: str | None = None, tab_id: int | None = None, timeout: float = 15.0, raise_on_error: bool = False) -> BskResult`
  - `BskCli.evaluate(self, session: str, expression: str, *, timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 45.0, raise_on_error: bool = False) -> BskResult`

- [ ] **Step 1: 编写导航与观察类命令的单元测试**

在 `tests/test_cli_wrapper.py` 中新增针对 `navigate`、`reload`、`wait_for_navigation`、`observe`、`snapshot`、`get_html`、`evaluate` 的参数拼装测试用例。

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_cli_wrapper.py -k "test_cli_navigate or test_cli_observe or test_cli_evaluate" -v`
Expected: FAIL (AttributeError: 'BskCli' object has no attribute 'navigate')

- [ ] **Step 3: 在 `bsk/cli.py` 中实现上述方法**

为每个方法编写严格的参数拼装逻辑，支持 `--tab-id`、`--session`、`--json` 及特定子命令选项，统一调用 `self._execute`。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_cli_wrapper.py -k "test_cli_navigate or test_cli_observe or test_cli_evaluate" -v`
Expected: PASS

- [ ] **Step 5: Git commit**

```bash
git -C astrbot_plugin_bsk_browser commit -am "feat(cli): add navigate, observe, snapshot, get_html, and evaluate atomic methods"
```

---

### Task 2: BskCli 封装交互、诊断与环境原子命令

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/cli.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_cli_wrapper.py`

**Interfaces:**
- Consumes: `BskCli._execute(args, timeout, raise_on_error, expect_json)`
- Produces:
  - `BskCli.click`, `BskCli.hover`, `BskCli.wheel`, `BskCli.scroll_to`, `BskCli.focus`, `BskCli.blur`, `BskCli.fill`, `BskCli.press`, `BskCli.select`, `BskCli.drag`, `BskCli.upload`, `BskCli.download`, `BskCli.wait_for_element`, `BskCli.wait_ms`, `BskCli.interact`
  - `BskCli.read_console`, `BskCli.read_network`, `BskCli.debug`
  - `BskCli.screenshot`, `BskCli.emulate`, `BskCli.resize_window`, `BskCli.request_help`

- [ ] **Step 1: 编写交互、诊断与视口命令的单元测试**

在 `tests/test_cli_wrapper.py` 中编写 `click`、`fill`（含空值测试）、`press`、`wheel`、`drag`、`screenshot`、`read_console`、`interact` 等各方法的断言测试。

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_cli_wrapper.py -k "test_cli_click or test_cli_fill or test_cli_screenshot" -v`
Expected: FAIL (AttributeError: 'BskCli' object has no attribute 'click')

- [ ] **Step 3: 在 `bsk/cli.py` 中实现全部交互、诊断与视口方法**

包括：
- `click`, `hover`, `wheel`, `scroll_to`, `focus`, `blur`, `fill`, `press`, `select`, `drag`, `upload`, `download`, `wait_for_element`, `wait_ms`
- `interact(session, action, **opts)` 分发器
- `read_console`, `read_network`, `debug`
- `screenshot`, `emulate`, `resize_window`, `request_help`

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_cli_wrapper.py -v`
Expected: PASS

- [ ] **Step 5: Git commit**

```bash
git -C astrbot_plugin_bsk_browser commit -am "feat(cli): add interactive, diagnostic, and viewport atomic wrapper methods"
```

---

### Task 3: SessionManager 实现 execute_action 并收拢 close_tab_safe

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/session.py`
- Modify: `astrbot_plugin_bsk_browser/bsk/cli.py` (移除 BskCli.close_tab_safe)
- Test: `astrbot_plugin_bsk_browser/tests/test_session_execute_action.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py`

**Interfaces:**
- Consumes: `BskCli.select_tab`, `BskCli.sync_tab`, `BskCli.close_tab`
- Produces:
  - `SessionManager.execute_action(self, key: str, action: Callable[[str], Awaitable[BskResult]], *, timeout: float | None = None, allow_uncertain: bool = False) -> BskResult`
  - `SessionManager.close_tab_safe(self, key_or_session_id: str, tab_id: int | str, *, timeout: float = 5.0, raise_on_error: bool = False) -> BskResult`
  - 维持 `SessionManager.execute` 签名并内部委托给 `execute_action`

- [ ] **Step 1: 编写 `execute_action` 与 `close_tab_safe` 单元测试**

在 `tests/test_session_execute_action.py` 中测试：
- 正常调度 action(sid) 并返回结果；
- `BskSessionGone` 触发会话重启后，使用新 `session_id` 成功重试；
- 不确定态下写操作被拦截，只读操作正常放行；
- `close_tab_safe` 的 select -> sync -> close 调用序列及容错。

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_session_execute_action.py -v`
Expected: FAIL (AttributeError: 'SessionManager' object has no attribute 'execute_action')

- [ ] **Step 3: 在 `bsk/session.py` 中实现 `execute_action` 和 `close_tab_safe` 并更新内部调用**

- 在 `SessionManager` 中新增 `execute_action`，实现加锁、重试和校验；
- 将 `execute` 转为调用 `execute_action`；
- 在 `SessionManager` 中新增 `close_tab_safe`，并使 `_stop_entry` 调用 `self.close_tab_safe`；
- 从 `bsk/cli.py` 中安全移除 `close_tab_safe`。

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_session_execute_action.py astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py -v`
Expected: PASS

- [ ] **Step 5: Git commit**

```bash
git -C astrbot_plugin_bsk_browser commit -am "feat(session): add execute_action and migrate close_tab_safe to SessionManager"
```

---

### Task 4: Service 层解耦：导航、观察、DOM 与评估操作改造

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_service.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_service_sync.py`

**Interfaces:**
- Consumes: `SessionManager.execute_action`, `BskCli.navigate`, `BskCli.reload`, `BskCli.wait_for_navigation`, `BskCli.observe`, `BskCli.snapshot`, `BskCli.get_html`, `BskCli.evaluate`
- Produces: `BskService.open_page`, `BskService.observe`, `BskService.evaluate`, `BskService.snapshot`, `BskService.get_html`, `BskService.history`, `BskService.reload_page`, `BskService.wait_for`

- [ ] **Step 1: 检查既有 Service 导航与观察测试**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_service.py -k "navigate or observe or evaluate" -v`
Expected: PASS (确认基准)

- [ ] **Step 2: 修改 `service.py` 中的导航、观察、快照、HTML 与评估方法**

将原先的手动组装 `args` 与 `lambda sid: [...]` 全部替换为：
`await self.sessions.execute_action(session_key, lambda sid: self.cli.<method>(sid, ...), ...)`。

- [ ] **Step 3: 运行测试验证通过**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_service.py -k "navigate or observe or evaluate" -v`
Expected: PASS

- [ ] **Step 4: Git commit**

```bash
git -C astrbot_plugin_bsk_browser commit -am "refactor(service): use BskCli and execute_action for navigation and observation"
```

---

### Task 5: Service 层解耦：交互、诊断、视口操作改造与冗余清理

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_service.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_interaction_resilience.py`

**Interfaces:**
- Consumes: `SessionManager.execute_action`, `SessionManager.close_tab_safe`, `BskCli.click`, `BskCli.fill`, `BskCli.screenshot`, `BskCli.read_console`, `BskCli.read_network`, `BskCli.debug`, `BskCli.emulate`, `BskCli.resize_window`, `BskCli.request_help`
- Produces: 清洁的 `BskService`，彻底无 `_build_action_args`、`_build_interact_args`、`_with_tab_id`、`INTERACT_SPECS` 等冗余拼装代码

- [ ] **Step 1: 检查既有交互与诊断测试**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_service.py -k "act or interact or screenshot or console" -v`
Expected: PASS (确认基准)

- [ ] **Step 2: 重构 `service.py` 的交互、诊断、视口、标签方法并清理冗余代码**

- 将 `act`、`interact` 改为委托 `self.cli.interact` 或具体 `self.cli.<method>`；
- 将 `read_console_ex`、`read_network_ex`、`debug` 改为委托 `self.cli`；
- 将 `screenshot`、`screenshot_ex`、`emulate`、`resize_window`、`request_help` 改为委托 `self.cli`；
- 将 `tabs(action="close")` 改为调用 `await self.sessions.close_tab_safe(session_key, tab_id, raise_on_error=True)`；
- 彻底移除 `service.py` 内部的 `_build_action_args`、`_build_interact_args`、`_with_tab_id`、`_tab_args`、`_size_args`、`INTERACT_SPECS`、`TABS_SPECS`。

- [ ] **Step 3: 运行相关 Service 测试验证通过**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_service.py -v`
Expected: PASS

- [ ] **Step 4: Git commit**

```bash
git -C astrbot_plugin_bsk_browser commit -am "refactor(service): use BskCli for interactions and remove legacy arg builders"
```

---

### Task 6: 迁移白盒测试用例并全量回归验证

**Files:**
- Modify/Migrate: `astrbot_plugin_bsk_browser/tests/test_interact_args.py` -> `astrbot_plugin_bsk_browser/tests/test_cli_wrapper.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_service_sync.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_observation_resilience.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_navigate_resilience.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_screenshot_resilience.py`

- [ ] **Step 1: 将直接断言 `_build_interact_args` 的测试平移为直接测试 `BskCli`**

更新 `test_interact_args.py`，改为断言 `BskCli.interact` / `BskCli.click` / `BskCli.fill` 等生成的 CLI 参数列表与行为。

- [ ] **Step 2: 适配弹性与 Mock 测试中的 `execute_action` / `cli` 调用**

更新 `test_tab_lifecycle_cleanup.py` 等测试，将原先断言 `service.cli.close_tab_safe` 改为断言 `session_mgr.close_tab_safe`；更新相关 mock 逻辑。

- [ ] **Step 3: 运行全量测试套件进行完整回归**

Run: `pytest astrbot_plugin_bsk_browser/tests`
Expected: 100% 全部通过 (1030+ passed, 0 failed)

- [ ] **Step 4: Git commit**

```bash
git -C astrbot_plugin_bsk_browser commit -am "test: migrate white-box tests to BskCli and adapt resilience tests"
```

---

### Task 7: 检查 SKILL 文档并验证交付一致性

**Files:**
- Modify: `astrbot_plugin_bsk_browser/skills/bsk-browser/SKILL.md` (如需)
- Check: `astrbot_plugin_bsk_browser/skills/`

- [ ] **Step 1: 检查 SKILL 文档是否需要更新**

核对 `skills/bsk-browser/SKILL.md`、`skills/bsk-browse-baidu/SKILL.md`、`skills/bsk-browse-bingcn/SKILL.md`，确认工具说明与使用指南依然准确无误，如有需要则更新。

- [ ] **Step 2: 运行 SKILL 文档测试**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_skills_doc.py -v`
Expected: PASS

- [ ] **Step 3: 检查代码署名与风格**

确认所有修改文件保留原有署名并包含 `SmileYik`。

- [ ] **Step 4: Git commit**

```bash
git -C astrbot_plugin_bsk_browser commit -am "docs(skill): verify SKILL documentation and attribution"
```
