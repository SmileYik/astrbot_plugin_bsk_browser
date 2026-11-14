# 协同控制同步韧性增强与错误分类修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `astrbot_plugin_bsk_browser` 在复杂网页自动化场景下的协同控制失败、`not_found` 错误误判导致的空白页（`about:blank`）死循环，并对齐官方 `bsk-cli/skill` 协同工作流。

**Architecture:** 在 `bsk/errors.py` 中精准将 `ref_not_found` 和 `selector_not_found` 分流为目标错误（`BskUserError`），杜绝会话误重启；在 `bsk/service.py:observe` 中透明复用 `sync_session` 并对 `about:blank` 平滑降级；在 `bsk/service.py:interact` 中对 `@ref` 目标在 `sync` 后提供携带裁剪 VOM 的错误引导而非盲目重试；在 `main.py` 中对齐导航后建议使用 `sync` 的官方流程提示。

**Tech Stack:** Python 3.10+, `unittest`, `unittest.mock`, `astrbot` plugin architecture, BrowserSkill CLI 0.5.0.

**Spec:** [`docs/superpowers/specs/2026-11-15-bsk-cooperation-sync-resilience-design.md`](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-bsk-cooperation-sync-resilience-design.md)

## Global Constraints

- 保持现有工具 Schema 定义完全不变；
- 严禁将元素级未找到（`ref_not_found` / `selector_not_found`）作为会话崩溃处理并触发 `_restart`；
- 严禁在 `sync` 重新编号之后盲目重试旧 `@ref`；
- 兼容 Python 3.10+ 标准库与 AstrBot 插件运行环境；
- 所有单测必须遵循 `unittest.IsolatedAsyncioTestCase` 规范，不破坏现有 876 个已有测试。

## Review Focus

1. **`not_found` 错误无 reason 字段时**：合理预期为继续归类为 `BskSessionGone`（保留会话断开恢复机制），不能漏判。
2. **`observe()` 在初始空白页（`about:blank`）上读取时**：`bsk sync` 会返回 `frame_unobservable`，合理预期为无感降级为只读 `bsk observe` 成功返回空 VOM。
3. **`observe()` 传入 `max_depth` 或 `cursor` 时**：因 `bsk sync` 不支持深度限制或续读，合理预期为回退走 `bsk observe`。
4. **`interact` 遇到 `cooperation_sync_required` 且目标是 CSS 选择器时**：合理预期为自动 `sync` 后安全重试选择器并成功执行。
5. **`interact` 遇到 `cooperation_sync_required` 且目标是 `@e1` 时**：合理预期为自动 `sync` 后不向底头发起失效的 `@e1` 重试，而是抛出携带格式化 VOM 的友好引导。

---

### Task 1: 精准分类 `code="not_found"` 错误 (`bsk/errors.py`)

**Files:**
- Modify: `bsk/errors.py:316-326`
- Test: `tests/test_errors.py`

**Interfaces:**
- Consumes: `classify(exit_code, code, message, hint, reason, stderr, effect_state)`
- Produces: `BskUserError` when `code == "not_found"` and `reason in ("ref_not_found", "selector_not_found")`; `BskSessionGone` when `code == "not_found"` and not target error.

- [ ] **Step 1: 编写测试用例**

在 `tests/test_errors.py` 中添加针对 `ref_not_found`、`selector_not_found` 以及通用 `not_found` 的分类单测：

```python
    def test_not_found_with_ref_not_found_returns_user_error(self) -> None:
        err = classify(
            exit_code=1,
            code="not_found",
            message="ref @e15 unknown for tab 1",
            hint="Observe the current page",
            reason="ref_not_found",
        )
        self.assertIsInstance(err, BskUserError)
        self.assertNotIsInstance(err, BskSessionGone)
        self.assertIn("目标元素不存在或已失效", err.friendly)

    def test_not_found_with_selector_not_found_returns_user_error(self) -> None:
        err = classify(
            exit_code=1,
            code="not_found",
            message="selector did not match",
            hint="check selector",
            reason="selector_not_found",
        )
        self.assertIsInstance(err, BskUserError)
        self.assertNotIsInstance(err, BskSessionGone)

    def test_not_found_generic_session_returns_session_gone(self) -> None:
        err = classify(
            exit_code=1,
            code="not_found",
            message="session not registered or already stopped",
            hint="the session may have stopped",
            reason="",
        )
        self.assertIsInstance(err, BskSessionGone)
```

- [ ] **Step 2: 运行测试验证失败**

运行：`python3 -m unittest tests/test_errors.py`
预期：FAIL（`test_not_found_with_ref_not_found_returns_user_error` 与 `test_not_found_with_selector_not_found_returns_user_error` 断言失败，返回了 `BskSessionGone`）。

- [ ] **Step 3: 实现 `bsk/errors.py` 中的分类修正**

在 `bsk/errors.py` 的 `classify` 函数中，对 `code == CODE_NOT_FOUND` 增加 `reason` 判断：
```python
    if code == CODE_NOT_FOUND:
        if reason in ("ref_not_found", "selector_not_found"):
            return BskUserError(
                detail,
                friendly="目标元素不存在或已失效（页面可能已刷新或发生跳转）。请重新查看页面并使用最新元素编号。",
                code=code,
                exit_code=exit_code,
                reason=reason,
                effect_state=effect_state,
            )
        return BskSessionGone(
            detail,
            friendly="浏览器会话已失效（可能空闲太久被回收），正在重新建立。",
            code=code,
            exit_code=exit_code,
            reason=reason,
            effect_state=effect_state,
        )
```

- [ ] **Step 4: 运行测试验证通过**

运行：`python3 -m unittest tests/test_errors.py`
预期：PASS。

- [ ] **Step 5: 提交更改**

```bash
git add bsk/errors.py tests/test_errors.py
git commit -m "fix(errors): classify ref_not_found and selector_not_found as user error instead of session gone"
```

---

### Task 2: `observe()` 透明同步转发与空白页平滑降级 (`bsk/service.py`)

**Files:**
- Modify: `bsk/service.py:590-645`
- Test: `tests/test_service_sync.py`

**Interfaces:**
- Consumes: `BskService.observe`, `BskService.sync_session`, `BskError`
- Produces: `observe(key, ...)` transparently calling `sync_session` on standard reads, falling back to original `observe` on `frame_unobservable` or when explicit probe/depth/cursor options are provided.

- [ ] **Step 1: 编写测试用例**

在 `tests/test_service_sync.py` 中添加 `observe()` 透明同步与降级测试：

```python
    async def test_observe_transparently_calls_sync_session(self) -> None:
        service = BskService.__new__(BskService)
        service.sync_session = AsyncMock(
            return_value=PageObservation(text="@vom 1\nRootWebArea \"Test\"\n@e1 link \"A\"", ref_count=1)
        )
        service._run_observe = AsyncMock()

        obs = await service.observe("s1", tab_id=2, max_tokens=1000)
        self.assertEqual(obs.ref_count, 1)
        service.sync_session.assert_called_once_with("s1", tab_id=2, max_tokens=1000)
        service._run_observe.assert_not_called()

    async def test_observe_sync_session_fallback_on_frame_unobservable(self) -> None:
        service = BskService.__new__(BskService)
        from bsk.errors import BskError
        service.sync_session = AsyncMock(side_effect=BskError("blank page", reason="frame_unobservable"))
        service._run_observe = AsyncMock(
            return_value=PageObservation(text="@vom 1\nRootWebArea \"about:blank\"", ref_count=0)
        )

        obs = await service.observe("s1")
        self.assertEqual(obs.ref_count, 0)
        service.sync_session.assert_called_once_with("s1", tab_id=None, max_tokens=None)
        service._run_observe.assert_called_once_with("s1", cursor="", max_depth=None, max_tokens=None, tab_id=None)

    async def test_observe_with_max_depth_or_cursor_bypasses_sync(self) -> None:
        service = BskService.__new__(BskService)
        service.sync_session = AsyncMock()
        service._run_observe = AsyncMock(return_value=PageObservation(text="vom", ref_count=1))

        await service.observe("s1", max_depth=3)
        service.sync_session.assert_not_called()
        service._run_observe.assert_called_once_with("s1", cursor="", max_depth=3, max_tokens=None, tab_id=None)
```

- [ ] **Step 2: 运行测试验证失败**

运行：`python3 -m unittest tests/test_service_sync.py`
预期：FAIL（`observe` 尚未支持 `sync_session` 转发）。

- [ ] **Step 3: 重构 `observe` 实现透明转发与降级**

在 `bsk/service.py` 中：
1. 将原本直接调用 `bsk observe` 的核心逻辑提取为私有方法 `_run_observe(self, key, cursor, max_depth, max_tokens, tab_id, probe_hover=False, debug_surfaces=False)`；
2. 在 `observe` 中判断：
```python
        if not cursor and max_depth is None and not probe_hover and not debug_surfaces:
            try:
                return await self.sync_session(key, tab_id=tab_id, max_tokens=max_tokens)
            except BskError as exc:
                if getattr(exc, "reason", "") == "frame_unobservable":
                    self._logger.info("sync 在当前页面遇到 frame_unobservable（通常为初始空白页），平滑降级为只读 observe")
                else:
                    raise
        return await self._run_observe(
            key,
            cursor=cursor,
            max_depth=max_depth,
            max_tokens=max_tokens,
            tab_id=tab_id,
            probe_hover=probe_hover,
            debug_surfaces=debug_surfaces,
        )
```

- [ ] **Step 4: 运行测试验证通过**

运行：`python3 -m unittest tests/test_service_sync.py`
预期：PASS。

- [ ] **Step 5: 提交更改**

```bash
git add bsk/service.py tests/test_service_sync.py
git commit -m "feat(service): transparently forward standard observe to sync_session with blank-page fallback"
```

---

### Task 3: 交互层防御式自愈与失效 ref 引导 (`bsk/service.py`)

**Files:**
- Modify: `bsk/service.py:2636-2670`
- Test: `tests/test_service_sync.py`

**Interfaces:**
- Consumes: `BskService.interact`, `BskService.render_page`, `BskUserError`
- Produces: `interact` auto-sync and retry for selector targets; raise `BskUserError(code="ref_stale_after_sync")` with formatted VOM for ref targets.

- [ ] **Step 1: 编写测试用例**

在 `tests/test_service_sync.py` 中添加针对 selector 重试与 ref 防盲目重试的单测：

```python
    async def test_interact_auto_sync_retries_css_selector(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._build_interact_args = MagicMock(return_value=(["click", "button.submit"], False))
        service._interact_timeout_builtin = MagicMock(return_value=30.0)
        service._timeout = lambda b: b
        service._logger = MagicMock()
        service._with_tab_id = lambda args, tid: args
        service._session_field = lambda k: "s1"
        service._payload_tab_id = lambda d: None
        service._interact_result = MagicMock(return_value={})
        service.sync_session = AsyncMock(return_value=PageObservation(text="ok"))

        from bsk.errors import BskError
        err = BskError("sync required", reason="cooperation_sync_required")
        success_res = MagicMock(data={"status": "ok"})
        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(side_effect=[err, success_res])

        res = await service.interact("s1", "click", target="button.submit")
        self.assertTrue(res["auto_synced"])
        self.assertEqual(service.sessions.execute.call_count, 2)

    async def test_interact_auto_sync_ref_target_raises_stale_ref_guidance(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._build_interact_args = MagicMock(return_value=(["fill", "@e15", "gtnh"], False))
        service._interact_timeout_builtin = MagicMock(return_value=30.0)
        service._timeout = lambda b: b
        service._logger = MagicMock()
        service._with_tab_id = lambda args, tid: args
        service.sync_session = AsyncMock(return_value=PageObservation(text="new page", title="Search"))
        service.render_page = MagicMock(return_value="标题：Search\n可交互元素：\n  @e56 textbox")

        from bsk.errors import BskError, BskUserError
        err = BskError("sync required", reason="cooperation_sync_required")
        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(side_effect=err)

        with self.assertRaises(BskUserError) as cm:
            await service.interact("s1", "fill", target="@e15", value="gtnh")

        self.assertEqual(cm.exception.code, "ref_stale_after_sync")
        self.assertIn("@e15", cm.exception.friendly)
        self.assertIn("@e56 textbox", cm.exception.friendly)
        # 绝不能发起第二次 execute 重试无效 ref！
        self.assertEqual(service.sessions.execute.call_count, 1)
```

- [ ] **Step 2: 运行测试验证失败**

运行：`python3 -m unittest tests/test_service_sync.py`
预期：FAIL（原有的 `interact` 依然盲目对 `@e15` 发起重试）。

- [ ] **Step 3: 更新 `interact` 自愈与重试逻辑**

在 `bsk/service.py` 的 `interact` 中：
```python
        except BskError as exc:
            if getattr(exc, "reason", "") == "cooperation_sync_required" and getattr(exc, "effect_state", "") != "unknown":
                self._logger.info("检测到页面控制上下文未同步 (cooperation_sync_required)，执行 sync_session 补救")
                obs = await self.sync_session(session_key, tab_id=tab_id)
                auto_synced = True

                is_ref = target.startswith("@") or (target.lower().startswith("e") and target[1:].isdigit())
                if is_ref:
                    rendered_vom = self.render_page(obs)
                    from .errors import BskUserError

                    raise BskUserError(
                        f"目标 {target} 在控制权同步后已失效",
                        friendly=(
                            f"操作前检测到页面控制权未同步，已在后台自动执行 sync 完成同步。"
                            f"由于页面状态已刷新，原元素编号「{target}」已失效。\n"
                            f"当前页面最新元素如下，请直接使用新编号执行操作：\n{rendered_vom}"
                        ),
                        code="ref_stale_after_sync",
                        reason="ref_not_found",
                    )

                try:
                    result = await _run_action()
                except BskError as retry_exc:
                    if getattr(retry_exc, "reason", "") == "element_not_visible" and target and action != "scroll-to":
                        self._logger.info("目标 %s 不在视口内，尝试自动 scroll-to 后重试 %s", target, action)
                        await _run_scroll()
                        result = await _run_action()
                        auto_scrolled = True
                    else:
                        raise
```

- [ ] **Step 4: 运行测试验证通过**

运行：`python3 -m unittest tests/test_service_sync.py`
预期：PASS。

- [ ] **Step 5: 提交更改**

```bash
git add bsk/service.py tests/test_service_sync.py
git commit -m "fix(service): prevent blind retry on stale refs after cooperation sync and provide fresh rendered vom"
```

---

### Task 4: 引导文案对齐与全链路集成验证 (`main.py` & `tests/test_integration_sync.py`)

**Files:**
- Modify: `main.py:1170-1176`
- Modify: `tests/test_integration_sync.py`

**Interfaces:**
- Consumes: Task 1, Task 2, Task 3
- Produces: Aligned prompt guidance in `main.py`, integration test suite passing for the whole cooperation sync lifecycle.

- [ ] **Step 1: 编写/更新集成测试**

在 `tests/test_integration_sync.py` 中更新或新增场景用例：
1. 验证模型使用 `navigate -> observe -> interact` 流程时，由于 `observe` 透明同步，`interact` 一次成功，无需补救；
2. 验证若发生 `cooperation_sync_required` 且目标为 `@ref` 时，优雅返回提示及新 VOM，会话保持活跃，绝不触发 `BskSessionGone` 或 `_restart`。

- [ ] **Step 2: 运行测试验证**

运行：`python3 -m unittest tests/test_integration_sync.py`
预期：根据修改调整 mock 响应后通过。

- [ ] **Step 3: 更新 `main.py` 提示文案**

在 `main.py` 的 `_run_page` 中：
将 `lines.append("页面内容可能已经变化，元素编号也会变；接着请用 bsk_inspect(action=\"observe\") 重新读一次页面。")`
更新为：
`lines.append("页面内容与元素编号已更新；接着请用 bsk_session(action=\"sync\") 同步页面并获取最新元素编号。")`

- [ ] **Step 4: 运行全部测试套件确保无回归**

运行：`python3 -m unittest discover -s tests -t .`
预期：870+ 测试全部 PASS。

- [ ] **Step 5: 提交更改**

```bash
git add main.py tests/test_integration_sync.py
git commit -m "feat(main): align navigation guidance prompt with bsk sync and update integration tests"
```
