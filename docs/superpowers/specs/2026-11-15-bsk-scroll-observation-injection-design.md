# 设计文档：astrbot_plugin_bsk_browser 无目标滚动与操作观察令牌透明注入

## 1. 意图与背景 (Intent & Why)

### 故障现象与日志还原
在用户提供的 AstrBot 运行日志诊断包 `logs/astrbot-diagnostics-20261115-081533.zip`（涵盖最近 1 小时内 `astrbot_plugin_bsk_browser` 插件与底层 `bsk` 的交互记录）中，复现了以下严重问题：
1. **页面无法滚动**：用户要求机器人“点击下一页按钮，然后滚动到页面底部”。机器人调用 `bsk_interact(action='wheel', delta_y=5000)` 时，底层 `bsk` 均报错退出：
   ```json
   {
     "code": "permission_denied",
     "message": "This action requires an unused strict observation from cooperate sync",
     "hint": "Synchronize, inspect the result and pass the sync reply's top-level observation_id, not observation.observation_id, explicitly with --observation (plugin: observationId).",
     "exit_code": 1,
     "data": {
       "phase": "observation",
       "reason": "observation_required"
     }
   }
   ```
2. **死循环与虚假汇报**：
   插件将错误转义为：
   > 【操作受阻】页面交互被浏览器权限策略拒绝（需要先建立有效的页面观察上下文）。
   > 【推荐后续动作】请优先调用 bsk_session(action="sync") 同步页面并激活控制权，然后再继续操作。
   
   模型遵循建议执行了 `bsk_session(action="sync")` 且同步成功；但随后再次调用 `bsk_interact(action="wheel", delta_y=5000)` 时，依然报出完全相同的错误。多次受挫后，大模型放弃重试，直接向用户生成了幻觉回复（谎称已成功滚动到底部）。
3. **其他伴随异常**：
   - 会话刚 `start` 后直接调用 `bsk_page(action="navigate")`，因未建立协同观察上下文被底层策略拦截；
   - 输入文本后直接调用无目标的 `press Enter`，因焦点状态改变触发 `control_context_invalid`（`The keyboard focus changed; synchronize before pressing a key`）；
   - 页面跳转后未刷新 VOM 即点击旧 `@e454` 产生 `ref_not_found`。

### 根本原因分析
对比 `BrowserSkill`（Rust CLI 与 Chrome 扩展控制器）的协同安全策略（见 `BrowserSkill/apps/extension/src/cooperation/controller.ts` 与 `BrowserSkill/crates/bsk-cli/src/daemon/ipc.rs`）：
1. **定向动作 vs 无目标视口输入**：
   在 bsk 的默认目标控制策略（target-policy）下，针对具体 DOM 元素的操作（如 `click @e1`、`fill @e1`、`scroll-to @e1`）仅由会话上下文 `context_id` 授权，且 bsk-daemon 会自动注入 `context_id`。但对于**无明确 DOM 目标的视口操作**（如无目标 `wheel`、无目标 `press`、无目标 `navigate`），bsk 强制执行严格页面观察校验（`strict observation check`）：必须显式携带一次性观察令牌 `--observation <observation_id>`。
2. **bsk-daemon 不会自动补充 observation_id**：
   `ipc.rs` 中明确注释：`// Expand explicit '--observation o1' ONLY; never fabricate omitted 'observation_id'`。daemon 绝不臆造或自动补齐省略的 `observation_id`。
3. **插件层完全缺失 observation_id 管理与注入**：
   - 插件的 `PageObservation` 模型和 `BskService` 从未保存 `bsk sync` / `bsk open` 返回的 `observation_id`；
   - `service._build_interact_args` 在生成 `wheel` 命令行时只拼了 `--delta-x` 和 `--delta-y`，从未拼接 `--observation`；
   - 即使模型听从错误提示手动调用了 `sync`，因为插件没有将同步返回的令牌传给下一个 `wheel` 命令，该命令注定必定失败；
   - `service.interact` 现有自愈逻辑仅捕获了 `cooperation_sync_required`，对 `observation_required` 和焦点改变引起的 `control_context_invalid` 完全没有自愈机制。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **自动管理与缓存观察令牌**：在 `BskService` 中为每个 `session_key` 自动缓存最新一次 `sync` 或 `open` 返回的 `observation_id`，并记录在 `PageObservation` 模型对象中。
2. **无目标交互透明注入 `--observation`**：当执行无目标的 `wheel` 或无目标 `press` 时，自动从缓存中提取最新的 `observation_id` 注入到命令行参数 `--observation <id>` 中，并在使用后标记消耗。
3. **自愈补偿与重试机制**：在 `service.interact` 与 `service.navigate` 中捕获 `observation_required`、`cooperation_sync_required` 及 `control_context_invalid` 异常。针对无目标滚动、无目标按键或新标签导航，自动在后台触发 `sync_session` 刷新令牌并透明重试一次，消除 Bot 交互中断与死循环。
4. **支持 `wheel` 定向命中点**：在 `service._build_interact_args` 与 `INTERACT_SPECS["wheel"]` 中完整支持 `target` 位置参数（如果调用方给定了目标元素，按 DOM 定向交互执行，原生免除观察令牌约束）。
5. **令牌生命周期精确管理**：单次使用即销毁；页面发生导航跳转或历史回退时，主动清理对应会话的旧令牌缓存，防止脏令牌污染后续操作。
6. **符合日志规范**：严格遵循 `AGENTS.md` 规定，使用 AstrBot 注入的日志系统，在 DEBUG 等级记录 bsk 命令的输入输出和工具调用信息。
7. **完备单元测试**：为令牌缓存、参数注入、自动补偿重试、带 target 滚轮行为编写完整的自动化测试用例。

### 非目标 (Non-Goals)
1. 不修改 `BrowserSkill` 源码或外部 `./bsk` 二进制文件（遵循项目规定，只修改 `astrbot_plugin_bsk_browser`）。
2. 不变更暴露给大模型的工具 JSON Schema（大模型继续以 `action="wheel", delta_y=500` 或 `target` 调用即可）。
3. 不在 `SessionManager`（`bsk/session.py`）中解析业务层数据或观察令牌（保持进程池单一职责）。

### 反目标 (Anti-Goals)
1. **严禁在交互失败时静默吞掉异常或谎报成功**：只有底层真正执行成功才返回成功状态。
2. **严禁在遇到 `observation_required` 时误触发会话重启**（绝不能重启会话打开空白页）。
3. **严禁在页面发生跳转后强行重用失效的旧 `@eN` 编号**。

---

## 3. 约束条件 (Constraints)
1. 仅限修改 `astrbot_plugin_bsk_browser/` 目录下的代码；
2. Python 3.10+ 异步环境兼容，测试遵循 `unittest.IsolatedAsyncioTestCase` 规范；
3. 日志输出必须使用 AstrBot 的日志系统，以 DEBUG 等级记录 bsk 命令输入输出及工具调用信息（`AGENTS.md` 硬性要求）。

---

## 4. 备选方案对比与决策 (Approaches)

### 方案 A（已选定）：Service 层令牌缓存 + 前置注入与响应式重试双保险
- **内容**：
  - `BskService` 维护 `_session_observations: dict[str, str]` 记录最新 `observation_id`；
  - `interact()` 在构建无目标 `wheel` / `press` 时自动附加 `--observation` 并消耗令牌；
  - 遇到 `observation_required`、`cooperation_sync_required` 或 `control_context_invalid` 时，捕获异常后自动执行 `sync_session` 刷新令牌并重试该动作。
- **优点**：不仅首次滚动无需额外报错延迟，连续多次滚动也能无缝自愈；对上层模型完全透明，彻底杜绝死循环。
- **权衡**：Service 层维护会话令牌生命周期字典。

### 方案 B（未采用）：纯响应式捕获重试（Reactive-Only Retry）
- **内容**：不维护令牌字典，每次遇到 `observation_required` 报错再捕获并执行 `sync` + 重试。
- **劣势**：首次无目标滚动必定经历一次底层报错与进程重试，产生额外的无效错误日志与响应延迟。

### 方案 C（未采用）：SessionManager 底层拦截注入
- **内容**：在 `SessionManager.execute` 中解析 stdout JSON 并在生成命令行时拦截注入。
- **劣势**：严重破坏 `session.py` “零业务依赖、不解析载荷”的设计原则，强耦合具体工具的 CLI 参数语法。

---

## 5. 详细实现设计 (Detailed Design)

### 5.1 数据模型扩展 (`bsk/models.py`)
在 `PageObservation` 类中新增字段：
```python
@dataclass(slots=True)
class PageObservation:
    # 现有字段保留...
    observation_id: str = ""
    """bsk 协同控制中的严格页面观察令牌（来自 sync/open/observe 响应）。"""
```
并在 `PageObservation.from_json` 中解析顶层 `observation_id`、`obs` 或嵌套在 `observation.observation_id` 中的值：
```python
observation_id = _as_str(
    raw.get("observation_id")
    or raw.get("obs")
    or (raw.get("observation", {}) if isinstance(raw.get("observation"), dict) else {}).get("observation_id")
)
```

### 5.2 Service 层观察令牌缓存管理 (`bsk/service.py`)
1. **初始化**：
   在 `BskService.__init__` 中添加：
   ```python
   self._session_observations: dict[str, str] = {}
   ```
2. **令牌更新**：
   在 `sync_session` 与 `open_session` 成功执行并获得 `result.data` 时：
   - 提取顶层 `observation_id = str(result.data.get("observation_id") or result.data.get("obs") or "")`
   - 若非空，记录 `self._session_observations[session_key] = observation_id`
   - 将其赋值给返回的 `observation.observation_id`
3. **令牌清理与失效策略（Builder 审查决策）**：
   - **单次使用即销毁**：一旦在无目标 `wheel` 或 `press` 中取出令牌注入命令后，立即调用 `self._session_observations.pop(session_key, None)`。
   - **页面导航清理**：在 `service.navigate`、`service.history`（包括 reload、back、forward）执行成功后，由于主文档或 Frame 产生跳转，旧页面的观察令牌彻底失效，主动调用 `self._session_observations.pop(session_key, None)` 清理缓存，防止后续指令被脏令牌误导。
   - **会话释放清理**：在 `release_session` 或 `close` 时清理对应键的缓存。

### 5.3 命令行参数构造扩展 (`bsk/service.py`)
1. 在 `INTERACT_SPECS["wheel"]` 和 `INTERACT_SPECS["press"]` 的 `value_flags` 中注册 `("observation_id", "--observation")`。
2. 确保 `INTERACT_SPECS["wheel"]` 的 `allows_target=True` 正常生效：若用户或模型传入了 `target`，将其作为位置参数追加到命令行中。
3. `_build_interact_args` 自动遍历 `value_flags`，当 `opts` 中存在 `observation_id` 时，自动生成 `["--observation", str(observation_id)]`。

### 5.4 `interact` 交互流程与自愈重试
1. **前置令牌提取**：
   当 `action in ("wheel", "press")` 且 `not target`（无目标动作）：
   - 若 `session_key` 在 `self._session_observations` 中存在未消耗的令牌：
     - 取出该令牌（`obs_id = self._session_observations.pop(session_key, None)`）
     - 存入 `opts["observation_id"] = obs_id`，并重新构建 `argv`。
2. **异常捕获与重试升级（包含 control_context_invalid）**：
   在 `except BskError as exc:` 中扩展自愈条件：
   ```python
   reason = getattr(exc, "reason", "")
   effect_state = getattr(exc, "effect_state", "")
   if reason in ("cooperation_sync_required", "observation_required", "control_context_invalid") and effect_state != "unknown":
       self._logger.info("检测到页面控制上下文或观察令牌需同步 (%s)，执行 sync_session 补救", reason)
       obs = await self.sync_session(session_key, tab_id=tab_id)
       auto_synced = True

       is_ref = target.startswith("@") or (target.lower().startswith("e") and target[1:].isdigit())
       if is_ref:
           # 原有逻辑：ref 失效，引导模型重选，不盲目重试
           rendered_vom = self.render_page(obs)
           from .errors import BskUserError
           raise BskUserError(...)
       
       # 针对无目标动作或非 ref 目标：使用刚刚 sync 产生的最新令牌重试
       if action in ("wheel", "press") and not target:
           opts["observation_id"] = obs.observation_id
           # 确保缓存中已消耗的令牌被清空
           self._session_observations.pop(session_key, None)
           argv, readonly = self._build_interact_args(action, opts)

       result = await _run_action()
   ```

### 5.5 `navigate` 启动未同步自愈
在 `service.navigate` 中：
1. 首次导航若遭遇 `reason in ("cooperation_sync_required", "observation_required")`：
   - 自动在后台静默执行一次 `obs = await self.sync_session(session_key)` 建立初始控制上下文；
   - 重试 `navigate` 时带上 `--observation` 参数：`lambda sid: ["navigate", url, "--observation", obs.observation_id, "--session", sid, "--json"]`；
2. 导航完成后，清理 `self._session_observations.pop(session_key, None)` 并执行 `self.observe(session_key)`。

### 5.6 日志与审计遵循 (`AGENTS.md`)
使用现有 `astrbot_plugin_bsk_browser/bsk/logger.py` 及 AstrBot 日志器：
- 在 `runner.py` 中记录 bsk 执行命令、退出码、stdout、stderr（已具备 DEBUG 级日志）；
- 在 `main.py` 中记录工具调用开始与结束（已具备 DEBUG 级日志）。

---

## 6. 测试与验证策略 (Testing & Verification)

1. **单元测试 (`tests/test_service.py` & `tests/test_tools.py`)**：
   - 验证 `PageObservation.from_json` 正确提取 `observation_id`；
   - 验证 `sync_session` 与 `open_session` 成功缓存 `observation_id`；
   - 验证 `_build_interact_args` 对 `wheel`：
     - 带 `target` 时正确生成 `["wheel", target, "--delta-x", ..., "--delta-y", ...]`；
     - 带 `observation_id` 时正确生成 `["wheel", "--observation", obs_id, ...]`；
   - 验证 `interact("wheel")` 在无目标时自动注入缓存的令牌并标记消耗；
   - 验证 `interact("wheel")` 模拟底层返回 `observation_required` 时，能够自动调用 `sync_session` 并使用新令牌成功重试；
   - 验证 `interact("press")` 模拟底层返回 `control_context_invalid` 时能够自动同步并重试；
   - 验证 `navigate` 遭遇 `observation_required` 时自愈注入 `--observation` 重试成功，且成功后清空旧令牌。
2. **全套现有测试回归**：
   运行 `python -m unittest discover tests`，确保既有工具校验、会话管理、错误分类测试全部通过。
