# Session 文本注释精炼与彻底移除 Uncertain 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 彻底剥离全插件中的 `uncertain` 状态机制与 `allow_uncertain` 死参数，并将 `bsk/session.py` 中的所有原作者文本注释按照 AGENTS.md 规范进行精炼简化。

**Architecture:** 
1. **模型与管理层解耦**：从 `BskSession` 和 `SessionManager` 中移除 `uncertain` 标记、闭锁阻断和计数器；遇到未知执行结果（`BskOutcomeUnknown` / `OUTCOME_UNKNOWN_REASONS`）时依然保持不可自动重试的语义直接上抛，将自愈权还给 LLM Agent；
2. **服务调用与展示清理**：全面清理 `BskService` 中 20+ 处 `allow_uncertain` 传参及 `/bskstatus` 的展示；
3. **注释精练工程**：对 `session.py` 全文重构，剔除日记式、辩论文风和情绪化废话，保留清晰精炼的技术与边界说明。

**Tech Stack:** Python 3.10+, asyncio, pytest, bsk CLI

**Spec:** `astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-16-session-simplify-and-remove-uncertain-design.md`

## Global Constraints

- **Single Repository**: 仅修改 `astrbot_plugin_bsk_browser` 仓库；
- **Concise Text**: 所有注释与文案严格遵循 AGENTS.md“在正确表义基础上做到精炼简洁不啰嗦”；
- **Logging**: 日志输出维持 AstrBot 规范；
- **Attribution**: 保留原仓库原作者署名，增加 `SmileYik`；
- **Skill Docs**: 修改后检查维护 `astrbot_plugin_bsk_browser/skills/` 中的 SKILL 文档并保持一致；
- **Zero Dead Parameters**: 签名中彻底删除 `allow_uncertain`，不留死参数兼容层。

## Review Focus

1. **Outcome Unknown Direct Propagation**: `execute_action` 遇到 `BskOutcomeUnknown` 时直接向外抛出异常，不进行多次盲目重试；
2. **No Sticky Blocking on Subsequent Actions**: 在一次动作因 outcome unknown 抛出异常后，同一会话的下一次操作（如 `observe` 或再次交互）能够正常执行，绝不被任何死锁状态拦截；
3. **Reason-based Non-Retry Verification**: 当底层抛出携带 `OUTCOME_UNKNOWN_REASONS`（如 `input_outcome_unknown`）的异常时，确保不进入重试循环直接上抛；
4. **Stats Structure Cleanliness**: `SessionManager.stats()` 返回的字典顶层不再出现 `uncertain_count`，`details` 列表元素也不再包含 `uncertain` 字段；
5. **Full Service Suite Signature Alignment**: `BskService` 中所有包装动作均在不传递 `allow_uncertain` 的情况下平稳执行。

---

### Task 1: 数据模型与 SessionManager 彻底移除 uncertain 机制

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/models.py:145-155`
- Modify: `astrbot_plugin_bsk_browser/bsk/session.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_session.py`

**Interfaces:**
- Consumes: `BskSession`, `BskOutcomeUnknown`, `OUTCOME_UNKNOWN_REASONS`
- Produces: 
  - `BskSession`（无 `uncertain` 字段）
  - `SessionManager.execute_action(self, key: str, action: Any, *, timeout: float | None = None) -> BskResult`（移除 `allow_uncertain`）
  - `SessionManager.execute(self, key: str, args_builder: ArgsBuilder, *, timeout: float | None = None) -> BskResult`（移除 `allow_uncertain`）
  - `SessionManager.stats(self) -> dict`（无 `uncertain` 及 `uncertain_count`）

- [ ] **Step 1: 编写/更新测试验证 outcome unknown 不重试且不给会话打闭锁标记**

在 `tests/test_session.py` 中更新相关测试用例：
```python
async def test_outcome_unknown_does_not_retry_and_raises(self) -> None:
    """动作结果未知绝不重试，直接抛出异常；不设粘性不确定态，后续操作不被阻断。"""
    manager = self.make_manager()
    session = await manager.acquire("umo-1")
    self.runner.queue(
        "observe",
        fail(reason="extension_reconnected", exit_code=errors.EXIT_BROWSER),
        ok(),
    )

    with self.assertRaises(BskOutcomeUnknown):
        await manager.execute("umo-1", observe_builder)

    self.assertEqual(len(self.runner.calls_for("observe")), 1)

    # 验证后续动作正常执行，不会被阻断
    result = await manager.execute("umo-1", observe_builder)
    self.assertTrue(result.ok)
    self.assertEqual(len(self.runner.calls_for("observe")), 2)
```
删除 `test_allow_uncertain_permits_readonly_command`、`test_release_clears_uncertain_state`，并更新 `test_outcome_unknown_with_custom_code_is_still_blocked` 以及 `test_stats_contains_expected_keys` 中对 `uncertain` 字段的断言。

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_session.py -k "test_outcome_unknown_does_not_retry_and_raises" -v`
Expected: FAIL (因为当前逻辑依然会阻断后续调用)

- [ ] **Step 3: 修改 `models.py` 与 `session.py` 移除 uncertain 逻辑**

1. `bsk/models.py`:
   - 从 `BskSession` 中删除 `uncertain: bool = False`。
2. `bsk/session.py`:
   - `_adopt`: 删除 `target.uncertain = False`；
   - `_counters`: 删除 `"uncertain_blocks"`；
   - `execute_action`: 移除 `allow_uncertain: bool = False` 形参；移除 `if entry.session.uncertain...` 检查；在 `except BskOutcomeUnknown` 与 `if exc.reason in OUTCOME_UNKNOWN_REASONS:` 分支中仅执行 `raise`，移除 `_mark_uncertain`；
   - `execute`: 移除 `allow_uncertain: bool = False` 形参；
   - `stats`: 移除 `uncertain` 与 `uncertain_count`；
   - 删除 `_mark_uncertain` 和 `_uncertain_error` 方法定义。

- [ ] **Step 4: 运行 `test_session.py` 验证通过**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_session.py -v`
Expected: PASS

- [ ] **Step 5: Git commit**

```bash
git -C astrbot_plugin_bsk_browser commit -am "refactor(session): completely remove uncertain state and allow_uncertain parameter"
```

---

### Task 2: Service 层与 Main 层全面清理 allow_uncertain 传参与展示

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py`
- Modify: `astrbot_plugin_bsk_browser/main.py:2290-2305`
- Test: `astrbot_plugin_bsk_browser/tests/test_service.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_session_execute_action.py`

**Interfaces:**
- Consumes: `SessionManager.execute_action`, `SessionManager.execute`
- Produces: `BskService` 所有方法统一调用无 `allow_uncertain` 接口

- [ ] **Step 1: 编写/更新针对 Service 调用的单元测试**

检查 `tests/test_service.py` 和 `tests/test_session_execute_action.py`：
- 清理或重写 `test_console_works_while_session_is_uncertain` 与 `test_network_works_while_session_is_uncertain`（验证在单次未知错误发生后，console 与 network 操作仍可照常读取）；
- 清除测试代码中传递 `allow_uncertain` 的地方。

- [ ] **Step 2: 运行测试查看报错**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_service.py -k "uncertain" -v`
Expected: FAIL 或测试过时

- [ ] **Step 3: 清理 `service.py` 与 `main.py`**

1. `bsk/service.py`:
   - 检索并移除所有 `allow_uncertain=True` / `allow_uncertain=False` / `allow_uncertain=readonly` 传参（约 20+ 处）；
   - 清理相关 docstring 中对 `allow_uncertain` 的历史注释。
2. `main.py`:
   - 在状态信息展示中删除 `if cur.get("uncertain"): flags.append("上一步结果不确定")`。

- [ ] **Step 4: 运行全部 Service 与 Main 相关测试验证通过**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_service.py astrbot_plugin_bsk_browser/tests/test_session_execute_action.py astrbot_plugin_bsk_browser/tests/test_main_sync.py -v`
Expected: PASS

- [ ] **Step 5: Git commit**

```bash
git -C astrbot_plugin_bsk_browser commit -am "refactor(service): clean up all allow_uncertain call sites and status display"
```

---

### Task 3: 重构并精炼 session.py 所有文本注释 (AGENTS.md 规范)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/session.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_session.py`

**Interfaces:**
- Consumes: None (注释重构，行为不变)
- Produces: 符合 AGENTS.md 风格、精炼简洁无冗余的 `session.py`

- [ ] **Step 1: 精炼模块级 docstring (Lines 1-50)**

将原本 50 行包含 10 条长篇大论、背景宣泄和与上层扯皮的话术，替换为简洁精炼的模块定位与核心机制概括（控制在 15-20 行以内）：
- 说明会话生命周期按 key 隔离、并发安全对象池；
- 概括核心职责：同 key 串行加锁、失效重建重试、空闲定时回收、有界停止重试、可恢复启动协议与崩溃孤儿恢复；
- 保留核心设计约束（零第三方依赖、不自启长任务、单调时钟、清理路径不抛异常、journal 尽力而为）。

- [ ] **Step 2: 精炼常量注释 (Lines 118-250, 308-370)**

- 移除反问式自我辩解段落（如“全部有实测依据，改动前请先想清楚”、“为什么是 3 而不是 2”、“为什么这 5 秒给得起”、“为什么按文本而不是按异常类型判定”、“为什么宁大勿小”等）；
- 每个常量保留清晰、紧凑的技术定义与取值意义（如 `STOP_MAX_ATTEMPTS`、`STOP_TOTAL_BUDGET_SEC`、`STOP_TRANSIENT_ERROR_MARKERS`、`REQUEST_TOKEN_TTL_SEC` 等）。

- [ ] **Step 3: 精炼核心算法流程中的方法 docstring 与行内注释**

- `_is_transient_stop_error`: 保留 5 档判定逻辑的紧凑描述，删除抒情和心理活动；
- `_start_into`: 精简 request_id 协议流程（落盘 -> prepare -> start -> claim -> adopt），删除“裁决（见 DECISION-...）”等历史包袱文本；
- `_stop_session_id`: 精炼截止时刻、单次超时与重试预算的反推逻辑，保留关键数学约束，删除重复赘述的日记；
- `acquire`, `execute_action`, `execute`, `release`, `release_all`, `reap_idle`, `recover_orphans`, `_recover_by_request`, `_stop_once`, `_evict_for_capacity`, `_wait_idle`, `_journal_add_pending`:
  全面清理注释，确保每条注释准确表意且精炼不啰嗦。

- [ ] **Step 4: 运行单元测试验证代码逻辑未受任何破坏**

Run: `pytest astrbot_plugin_bsk_browser/tests/test_session.py -v`
Expected: PASS

- [ ] **Step 5: Git commit**

```bash
git -C astrbot_plugin_bsk_browser commit -am "docs(session): simplify comments and docstrings per AGENTS.md guidelines"
```

---

### Task 4: 署名更新、SKILL 文档审查与全套回归测试

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/session.py` (署名补充)
- Modify: `astrbot_plugin_bsk_browser/skills/` (如需)
- Test: 全体测试套件

**Interfaces:**
- 署名：保留原作者，增补 `SmileYik`
- 技能：`bsk-browser`、`bsk-browse-baidu`、`bsk-browse-bingcn`

- [ ] **Step 1: 检查并更新署名**

在 `bsk/session.py`（以及如有作者声明的文件头部）确保保留原作者署名，并添加 `SmileYik`。

- [ ] **Step 2: 审查 skills 文档**

检查 `astrbot_plugin_bsk_browser/skills/` 下的 SKILL 文档，确认未残留任何 `uncertain` 概念，保持内容简洁准确。

- [ ] **Step 3: 运行全套测试套件做全量回归测试**

Run: `pytest astrbot_plugin_bsk_browser/tests -v`
Expected: 1000+ tests 全部 PASS。

- [ ] **Step 4: Git commit**

```bash
git -C astrbot_plugin_bsk_browser commit -am "chore: add author attribution SmileYik and verify skill docs"
```
