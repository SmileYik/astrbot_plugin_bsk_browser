# 设计文档：astrbot_plugin_bsk_browser 协同控制同步韧性增强与错误分类修复

## 1. 意图与背景 (Intent & Why)

### 故障现象
在使用最新 `astrbot_plugin_bsk_browser` 插件对机器人下发复合浏览器指令（例如：“先打开百度，在搜索框内输入gtnh，然后按下回车，等待界面加载完毕后找到下一页按钮，点击下一页按钮，然后点击第一个搜索结果。”）时，出现以下严重问题：
1. 打开百度后，机器人无法输入文本，也无法点击任何按钮；
2. 机器人陷入死循环，频繁启动全新浏览器会话并不断打开 `about:blank` 空白页；
3. 后续针对空白页的操作全部抛出 `frame_unobservable: Page frames cannot be observed: 0 (about:)` 错误。

### 根本原因排查与调用链还原
结合 `astrbot.2026-11.15.2.txt` 实际运行日志与 BrowserSkill 核心机制，根本原因包含三个连锁缺陷：

1. **错误分类缺陷（致命连锁起因）**：
   在 [`bsk/errors.py`](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/bsk/errors.py#L316-L325) 中，`classify` 只要遇到底层返回 `code == "not_found"`，就一律返回 `BskSessionGone`（会话已失效）。
   然而在 BrowserSkill 中，元素编号失效时返回的也是 `code: "not_found"`（伴随 `reason: "ref_not_found"`）。
   会话管理器 [`SessionManager.execute`](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/bsk/session.py#L811-L825) 捕获到 `BskSessionGone` 后，误判为浏览器会话断开崩溃，自动触发 `_restart()`。`_restart()` 执行 `bsk session start` 打开了全新的空标签页（`about:blank`），并将内部会话指针偷换为新会话，导致后续的所有操作（`reload`、`interact`、`observe`）全部作用在空白页上并崩溃。

2. **交互自愈盲目重试失效 ref**：
   在 [`bsk/service.py`](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/bsk/service.py#L2636-L2650) 中，`interact` 捕获到 `cooperation_sync_required` 后，自动执行了 `sync_session`。
   然而，`bsk sync` 会对页面重新生成 VOM，并赋予全新的元素编号（例如输入框从 `@e15` 变更为 `@e56`），原本的旧编号立即作废。
   `interact` 在 `sync_session` 后依然盲目使用旧参数（`@e15`）重试，必然触发 `ref_not_found`，直接引爆了上述第 1 点的会话重启空白页死循环。

3. **工作流提示与模型操作脱节**：
   官方规范（`BrowserSkill/crates/bsk-cli/skill/SKILL.md`）明确指出：页面跳转/导航后必须使用 `bsk sync` 同步控制权与新元素；而插件的 `bsk_page(action="navigate")` 返回消息却依然引导模型去调用只读的 `bsk_inspect(action="observe")`。只读的 `observe` 无法签发控制上下文（`context_id`），导致模型随后的交互首发必撞 `cooperation_sync_required`。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **精准分类 `not_found` 错误**：在 `bsk/errors.py` 中，区分会话级别缺失与目标级别缺失。当 `reason in ("ref_not_found", "selector_not_found")` 时归类为 `BskUserError`，绝不抛出 `BskSessionGone`，彻底杜绝元素失效误触会话重建。
2. **底层透明同步兼容与平滑降级**：在 `bsk_inspect(action="observe")` 路径上，当未指定只读专属感知参数（如 `probe_hover`、`max_depth`）且无 `cursor` 时，底层透明通过 `bsk sync` 获取页面 VOM 并激活 target 控制策略。使遵循传统习惯的模型调用 `observe` 后也能立即拥有控制权与对应的 `@ref`，不再触发 `cooperation_sync_required`。同时若在 `about:blank` 页面遇到 `frame_unobservable`，自动静默降级回原始 `observe`。
3. **强化交互自愈防御**：在 `service.interact` 中捕获 `cooperation_sync_required` 时：
   - 若目标为 CSS 选择器（非 `@ref`），自动 `sync` 后安全重试；
   - 若目标为 `@ref`，因旧编号已失效，执行 `sync` 后不再盲目重试旧编号，而是通过经过 `render_page` 裁剪的最新页面 VOM 引导模型重选。
4. **对齐官方 skill 流程提示**：修改 `bsk_page` 等返回提示，将跳转后的操作引导对齐为 `bsk_session(action="sync")` 或 `open`。
5. **单元测试与回归防护**：补全针对 `ref_not_found` 分类、`observe` 透明同步与降级、`interact` 针对 ref/选择器自愈分支的单测。

### 非目标 (Non-Goals)
1. 不通过启发式算法猜测作废的旧 ref 对应哪一个新 ref（避免错点误操作）。
2. 不剥离 `bsk_inspect` 原有功能与向后兼容性。
3. 不变更大模型可见的工具 Schema（保持 Schema 稳定）。

### 反目标 (Anti-Goals)
1. **严禁将元素级未找到作为会话崩溃处理**：任何 DOM 目标未找到都不得触发 `_restart`。
2. **严禁在 `sync` 之后盲目重试旧 `@ref`**。

---

## 3. 约束条件 (Constraints)
1. 保持现有工具 Schema 定义完全不变；
2. 兼容 Python 3.10+ 及 AstrBot 插件运行环境；
3. 严格遵循现有项目单测规范（`unittest.IsolatedAsyncioTestCase`）。

---

## 4. 备选方案对比与决策 (Approaches)

### 方案 A：严格对齐官方规范方案
- 仅修复 `bsk/errors.py` 的分类错误，`observe` 保持纯只读，纯靠提示词引导模型主动调用 `bsk_session(action="sync")`。
- **缺点**：大模型往往存在习惯偏差，经常忽视提示依然调用 `observe`，导致每次跳转后的首次交互都要被迫中断一次走自愈流程。

### 方案 B：规范对齐 + 底层透明兼容方案（用户选定）
- 在方案 A 的基础上，让 `bsk_inspect(action="observe")` 在底层透明使用 `bsk sync`，模型即使使用旧习惯也自然获得控制权；配合 `interact` 针对 ref/选择器的智能防护和精准错误分类，达成最高容错率。

---

## 5. 详细实现设计 (Detailed Implementation)

### 5.1 错误分类精准化 (`bsk/errors.py`)
在 `classify` 函数中，对 `code == CODE_NOT_FOUND` 增加 `reason` 判断：
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

### 5.2 `bsk_inspect(action="observe")` 透明同步升级与降级 (`bsk/service.py`)
在 `BskService.observe` 中：
- 当满足标准普通读取条件时（`not cursor` 且 `max_depth is None` 且 `not probe_hover` 且 `not debug_surfaces`）：
  优先尝试 `self.sync_session(key, tab_id=tab_id, max_tokens=max_tokens)`。
  - 若执行成功：返回同步后的 `PageObservation`（既包含权威 VOM，又在 daemon 端激活 target 控制策略）；
  - 若捕获到 `BskError` 且 `reason == "frame_unobservable"`（典型如刚建立会话处于 `about:blank` 状态）：
    自动静默降级执行原有的 `bsk observe` 逻辑，确保初始空白页正常返回而不报错。
- 当传入 `cursor`、`max_depth` 或特殊探针参数时：
  直接执行原有的 `bsk observe` 逻辑，严格遵守原有参数契约。

### 5.3 交互层自愈与防御 (`bsk/service.py`)
在 `BskService.interact` 中处理 `cooperation_sync_required`：
```python
if getattr(exc, "reason", "") == "cooperation_sync_required" and getattr(exc, "effect_state", "") != "unknown":
    self._logger.info("检测到页面控制上下文未同步 (cooperation_sync_required)，执行 sync_session 补救")
    obs = await self.sync_session(session_key, tab_id=tab_id)
    auto_synced = True
    
    # 区分 target 类型：
    is_ref = target.startswith("@") or (target.lower().startswith("e") and target[1:].isdigit())
    if is_ref:
        # ref 在 sync 后必然失效，不能重试旧 ref，抛出带有格式化最新页面 VOM 的业务错误引导模型重选
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
    else:
        # CSS 选择器跨 sync 依然有效，执行安全重试
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

### 5.4 引导文案与规范对齐 (`main.py`)
- 更新 `bsk_page` 导航完成后的提示文案：
  将 `接着请用 bsk_inspect(action="observe") 重新读一次页面。` 更新为对齐规范的：
  `页面内容与元素编号已更新；接着请用 bsk_session(action="sync") 同步页面并获取最新元素编号。`
- 在 `_run_interact` / `_dispatch` 中确保 `ref_stale_after_sync` 抛出的 `friendly` 提示完整呈现给大模型。

---

## 6. 测试与验证策略 (Testing Strategy)

1. **错误分类单测 (`tests/test_errors.py`)**：
   - 验证 `code="not_found", reason="ref_not_found"` 归为 `BskUserError` 而非 `BskSessionGone`；
   - 验证 `code="not_found", reason="selector_not_found"` 归为 `BskUserError`；
   - 验证无 reason 的普通 `code="not_found"` 依然正确归为 `BskSessionGone`。
2. **观察透明同步与降级单测 (`tests/test_service_sync.py`)**：
   - 验证普通 `observe()` 调用在底层发出了 `bsk sync` 并返回 `PageObservation`；
   - 验证 `observe()` 在遇到 `frame_unobservable` 时自动降级发出 `bsk observe`；
   - 验证携带 `max_depth` 或 `probe_hover=True` 的 `observe()` 调用直接发出 `bsk observe`。
3. **交互自愈单测 (`tests/test_service_sync.py`)**：
   - 验证目标为 CSS 选择器时，`cooperation_sync_required` 触发一次 `sync` 后成功重试选择器；
   - 验证目标为 `@e1` 时，`cooperation_sync_required` 触发 `sync` 后抛出 `ref_stale_after_sync` 且提示中包含通过 `render_page` 裁剪的最新页面。
4. **全套集成与回归测试**：
   - 运行全部已有单测确保 100% 通过。
