# BskCli 语义化包装层下沉与 Service 层解耦重构设计

## 1. 背景与意图 (Intent and Why)

当前 `astrbot_plugin_bsk_browser/bsk/service.py` 承担了过多的底层细节职责（代码规模超过 4000 行）。在处理几乎所有浏览器操作（如 `navigate`、`observe`、各类鼠标与键盘交互动作、`screenshot`、`evaluate`、`console`、`network` 等）时，`service.py` 都在手工拼接 CLI 字符串参数数组（如 `["navigate", url, "--session", sid, "--json"]`），并通过 `lambda sid: ...` 回调委托给 `sessions.execute`，进而落到底层 `runner.run_or_raise`。

这种实现存在以下架构缺陷：
1. **职责倒置与边界不清**：`service.py` 本应是面向 AstrBot 和 LLM 的高层业务编排层（处理工具调用返回、截断控制、文案优化、提示引导），却充斥着大量命令行的选项名称、标志位组装、类型转换与字符串拼接逻辑；
2. **缺乏类型保障与重用性**：CLI 参数格式分散在各个方法和辅助函数（如 `_build_action_args`、`_build_interact_args`、`INTERACT_SPECS` 等）中，未沉淀为独立、强类型、易于测试的 CLI 客户端；
3. **复合逻辑位置倒挂**：此前引入的部分复合业务逻辑（如 `close_tab_safe`：`select` -> `sync` -> `close`）被放在了 `BskCli` 中，违背了 `BskCli` 作为 `./bsk` CLI 基础命令 1:1 包装层的纯粹性定位，且导致生命周期管理与基础包装耦合。

本设计的意图在于：
将 `./bsk` 可执行程序提供的所有基础原子操作全面封装到 `BskCli` (`bsk/cli.py`) 中，提供完整的强类型方法与文档注释；将 `close_tab_safe` 等跨多步的标签生命周期回收逻辑移入负责资源管理的 `SessionManager` (`bsk/session.py`)；同时对 `SessionManager` 进行扩展，支持直接调度异步 CLI 动作（`execute_action`），彻底消除 `service.py` 中的 CLI 原始字符串拼接。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals, and Anti-Goals)

### 目标 (Goals)
1. **G1 (完整覆盖原子 CLI 命令)**：在 `BskCli` 中实现 `bsk` 基础命令的强类型方法封装，包括但不限于：
   - 导航与生命周期：`navigate`、`reload`、`wait_for_navigation`；
   - 观察与提取：`observe`、`snapshot`、`get_html`、`evaluate`；
   - 页面交互：`click`、`hover`、`wheel`、`scroll_to`、`focus`、`blur`、`fill`、`press`、`select`、`drag`、`upload`、`download`、`wait_for_element`、`wait_ms`；
   - 诊断与日志：`read_console`、`read_network`、`debug`；
   - 视口与环境：`screenshot`、`emulate`、`resize_window`、`request_help`。
2. **G2 (参数规范与强类型)**：每个包装方法具备类型注解、合理的默认值（如 `json=True`、默认超时）、可选的 `raise_on_error`，以及详尽的 docstring 说明。
3. **G3 (生命周期与复合逻辑收拢)**：将复合编排逻辑 `close_tab_safe` 从 `BskCli` 迁移至 `SessionManager`，作为会话资源管理的原生能力；`BskCli` 只保留原子的 `select_tab`、`sync_tab`、`close_tab` 等操作。
4. **G4 (执行机制升级)**：在 `SessionManager` 中新增 `execute_action(key, action: Callable[[str], Awaitable[BskResult]], ...)`，保留按 key 加锁、会话失效自动重启重试、busy 退避与不确定态（uncertain）校验能力，兼容异步 CLI 调用。
5. **G5 (Service 层彻底去拼装化)**：重构 `service.py`，将内部所有的 `["cmd", ...]` 字符串拼接及 `_build_action_args`、`_build_interact_args`、`INTERACT_SPECS` 等参数组装表移至 `cli.py` 或消除，统一调用 `self.cli.<method>`。
6. **G6 (保持外部行为与测试完全兼容)**：插件对外暴露的 AstrBot 工具定义、面向模型的返回文案格式不变；保证已有测试套件及新增单元测试 100% 通过。

### 非目标 (Non-Goals)
- **改动 AstrBot 工具层接口**：不修改 `tools.py` 或 `main.py` 的对外工具签名和 Schema；
- **重构面向模型的文本生成逻辑**：`pages.py`、`shots.py`、`models.py` 以及 `service.py` 中对模型可见的文案组织保持既定行为；
- **改变底层进程调用机制**：底层依旧依托 `BskRunner` 管理子进程管道、超时与编码。

### 反目标 (Anti-Goals)
- **切忌在 BskCli 中掺入业务上下文状态**：`BskCli` 不得保存 AstrBot 会话 Key、用户映射关系或会话缓存；它只接受 `session: str`（对应 CLI 的 `--session <ID>`）并返回 `BskResult`；
- **切忌破坏自动重建重试机制**：会话失效重建（`not_found_rebuilds`）是系统的核心容灾特性，重构后在 `execute_action` 中必须确保重试时能以最新生成的 `session_id` 重新调度 CLI 方法；
- **切忌臆造 CLI 参数**：所有生成的 CLI 参数必须严格符合 `./bsk --help` 定义。

---

## 3. 约束条件 (Constraints)

1. **唯一修改仓库**：依照 AGENTS.md 规范，仅修改 `astrbot_plugin_bsk_browser` 仓库；
2. **日志规范**：涉及 bsk 调用的输入与输出必须维持 DEBUG 等级日志；
3. **SKILL 文档维护**：完成修改后检查并同步更新 `astrbot_plugin_bsk_browser/skills/` 下的 SKILL 文档；
4. **作者署名**：保留原作者，增补 `SmileYik`；
5. **测试保障**：重构前后功能行为完全对齐，测试用例全部通过。

---

## 4. 架构备选方案对比与抉择 (Approaches)

### 备选方案 1：BskCli 纯粹原子封装 + SessionManager 升级为 Action 调度器（选中）
- **描述**：
  - `BskCli` 定位为 `./bsk` 的强类型 Python SDK，负责原子参数拼装和执行；
  - `SessionManager` 扩展 `execute_action`，接受 `Callable[[str], Awaitable[BskResult]]`；在需要重试或会话重建时，传入新的 `session_id` 重新调用；
  - `close_tab_safe` 归入 `SessionManager`；
  - `BskService` 通过 `self.sessions.execute_action(key, lambda sid: self.cli.xxx(sid, ...))` 组织业务。
- **优点**：分层界限分明，`BskCli` 职责极为纯粹，单元测试编写简单独立；复用现有生命周期容灾机制且无缝过渡。
- **缺点**：Service 层调用需写 `lambda sid: self.cli.xxx(sid, ...)`。

### 备选方案 2：会话感知型客户端代理 (SessionProxy / BoundCli)
- **描述**：
  - 在 `SessionManager` 之上为每个会话包装一个动态代理对象，将 `session_id` 绑定并自动委托给 `BskCli`；
  - Service 层直接调用 `await session.navigate(url)`。
- **优点**：Service 层代码最简洁。
- **缺点**：增加了代理层抽象与故障追踪复杂度，对于少数不需要绑定会话或有特殊流程的命令不够直观。

### 抉择
采用 **方案 1**，契合用户“将基础操作在 cli.py 中包装、基于包装好的方法构建下一步业务，并将复合逻辑收拢至 SessionManager”的明确诉求。

---

## 5. 详细设计与实现细节 (Detailed Design)

### 5.1 BskCli 架构扩展 (`bsk/cli.py`)
`BskCli` 新增以下原子命令方法（统一接受可选 `timeout`、`raise_on_error`、`json=True` 等通用选项）：

1. **导航与页面控制**：
   - `navigate(self, session: str, target: str, *, observation: str | None = None, wait_until: str = "load", timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 45.0, raise_on_error: bool = False) -> BskResult`
   - `reload(self, session: str, *, hard: bool = False, wait_until: str = "load", timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 15.0, raise_on_error: bool = False) -> BskResult`
   - `wait_for_navigation(self, session: str, *, wait_until: str = "load", timeout_ms: int = 30000, tab_id: int | None = None, timeout: float = 35.0, raise_on_error: bool = False) -> BskResult`

2. **DOM 结构与内容获取**：
   - `observe(self, session: str, *, cursor: str = "", max_depth: int | None = None, max_tokens: int | None = None, probe_hover: bool = False, debug_surfaces: bool = False, tab_id: int | None = None, timeout: float = 15.0, raise_on_error: bool = False) -> BskResult`
   - `snapshot(self, session: str, *, max_depth: int | None = None, max_tokens: int | None = None, tab_id: int | None = None, timeout: float = 15.0, raise_on_error: bool = False) -> BskResult`
   - `get_html(self, session: str, *, ref: str = "", max_bytes: int = 524288, tab_id: int | None = None, timeout: float = 15.0, raise_on_error: bool = False) -> BskResult`
   - `evaluate(self, session: str, expression: str, *, timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 45.0, raise_on_error: bool = False) -> BskResult`

3. **交互操作 (Interact Commands)**：
   - `click(self, session: str, target: str, *, button: str | None = None, click_count: int | None = None, modifiers: list[str] | None = None, capture_id: str | None = None, image_x: int | None = None, image_y: int | None = None, timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 30.0, raise_on_error: bool = False) -> BskResult`
   - `hover(self, session: str, target: str, *, modifiers: list[str] | None = None, settle_ms: int | None = None, timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 30.0, raise_on_error: bool = False) -> BskResult`
   - `fill(self, session: str, target: str, value: str, *, no_clear: bool = False, timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 30.0, raise_on_error: bool = False) -> BskResult`
   - `press(self, session: str, key: str, *, target: str | None = None, modifiers: list[str] | None = None, observation_id: str | None = None, hold_ms: int | None = None, timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 30.0, raise_on_error: bool = False) -> BskResult`
   - `select(self, session: str, target: str, values: list[str] | str, *, timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 30.0, raise_on_error: bool = False) -> BskResult`
   - `scroll_to(self, session: str, target: str, *, timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 30.0, raise_on_error: bool = False) -> BskResult`
   - `focus(self, session: str, target: str, *, timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 30.0, raise_on_error: bool = False) -> BskResult`
   - `blur(self, session: str, target: str, *, timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 30.0, raise_on_error: bool = False) -> BskResult`
   - `wheel(self, session: str, *, delta_x: int = 0, delta_y: int = 0, target: str | None = None, modifiers: list[str] | None = None, observation_id: str | None = None, timeout_ms: int | None = None, tab_id: int | None = None, timeout: float = 30.0, raise_on_error: bool = False) -> BskResult`
   - `interact(self, session: str, action: str, **opts: Any) -> BskResult`：提供对动态动作名称的统一分发入口，内部校验动作合法性并组装对应子命令。

4. **日志诊断与辅助**：
   - `read_console(self, session: str, *, since: int = 0, limit: int | None = None, max_text_chars: int | None = None, include_stack: bool = False, tab_id: int | None = None, timeout: float = 5.0, raise_on_error: bool = False) -> BskResult`
   - `read_network(self, session: str, *, since: int = 0, limit: int | None = None, max_text_chars: int | None = None, tab_id: int | None = None, timeout: float = 5.0, raise_on_error: bool = False) -> BskResult`
   - `debug(self, session: str, debug_action: str, *, tab_id: int | None = None, timeout: float = 10.0, raise_on_error: bool = False, **extra_args: Any) -> BskResult`

5. **环境与视口**：
   - `screenshot(self, session: str, *, out: str | None = None, full_page: bool = False, ref: str | None = None, selector: str | None = None, format: str | None = None, quality: int | None = None, tab_id: int | None = None, timeout: float = 30.0, raise_on_error: bool = False) -> BskResult`
   - `emulate(self, session: str, *, device: str | None = None, width: int | None = None, height: int | None = None, user_agent: str | None = None, touch: bool | None = None, tab_id: int | None = None, timeout: float = 10.0, raise_on_error: bool = False) -> BskResult`
   - `resize_window(self, session: str, width: int, height: int, *, timeout: float = 10.0, raise_on_error: bool = False) -> BskResult`
   - `request_help(self, session: str, message: str, *, timeout_sec: int | None = None, tab_id: int | None = None, timeout: float = 60.0, raise_on_error: bool = False) -> BskResult`

### 5.2 SessionManager 调整 (`bsk/session.py`)

1. **`execute_action` 实现**：
   ```python
   async def execute_action(
       self,
       key: str,
       action: Callable[[str], Awaitable[BskResult]],
       *,
       allow_uncertain: bool = False,
   ) -> BskResult:
   ```
   - 维持锁机制 `self._locked_entry(key)`；
   - 维持不确定态拦截：若 `entry.session.uncertain and not allow_uncertain`，阻断写动作；
   - 重试循环：调用 `await action(entry.session.session_id)`；
   - 捕获 `BskSessionGone` 时，若未达最大重试次数，执行 `await self._restart(entry, stop_old=False)`，并使用新 `session_id` 再次调用 `action`；
   - 捕获 `BskSessionBusy` 时退避重试；
   - 捕获 `BskOutcomeUnknown` 时标记不确定态。
   - 保留原有的 `execute(key, args_builder, ...)` 作为兼容，其内部委托给 `execute_action`（将 `args_builder` 执行后调用 runner 包装为 action）。

2. **迁移 `close_tab_safe`**：
   在 `SessionManager` 中实现：
   ```python
   async def close_tab_safe(
       self,
       key_or_session_id: str,
       tab_id: int | str,
       *,
       timeout: float = 5.0,
   ) -> BskResult:
   ```
   - 获取有效的 `session_id`；
   - 顺序调度 `self._cli.select_tab` -> `self._cli.sync_tab` -> `self._cli.close_tab`；
   - 会话销毁时清理标签以及 Service 层的标签关闭操作均调用该方法。从 `BskCli` 中移除 `close_tab_safe`。

### 5.3 Service 层改造 (`bsk/service.py`)

1. **彻底移除字符串拼接**：
   - 移除 `_build_action_args`、`_build_interact_args`、`_with_tab_id` 等组装参数的冗余方法；
   - 将 `INTERACT_SPECS`、`TABS_SPECS` 等参数映射结构下沉至 `cli.py`（若 `cli.py` 的具体方法已各自承载，则 Service 层不再需要这些表）；
2. **重写操作派发**：
   - 例如 `open_page` / `navigate`：
     ```python
     nav_result = await self.sessions.execute_action(
         session_key,
         lambda sid: self.cli.navigate(
             sid,
             url,
             timeout=self._timeout(TIMEOUT_NAVIGATE),
             raise_on_error=True,
         ),
     )
     ```
   - 例如 `observe`：
     ```python
     result = await self.sessions.execute_action(
         session_key,
         lambda sid: self.cli.observe(
             sid,
             cursor=cursor,
             max_depth=max_depth,
             max_tokens=max_tokens,
             probe_hover=probe_hover,
             debug_surfaces=debug_surfaces,
             tab_id=tab_id,
             timeout=self._timeout(TIMEOUT_OBSERVE),
             raise_on_error=True,
         ),
         allow_uncertain=True,
     )
     ```
   - 例如 `act` / `interact`：
     直接调用 `self.cli.click`、`self.cli.fill` 等或委托给 `self.cli.interact`。
   - 例如 `tabs(action="close")`：
     直接调用 `await self.sessions.close_tab_safe(session_key, tab_id)`。

---

## 6. 开发者自主决策范围 (Left to Builder)

以下非核心细节留由具体实现时裁量：
1. `BskCli` 中各个原子方法的具体默认超时参数与底层 `_execute` 的分发细节；
2. 对于可选参数较多的命令（如 `click`、`screenshot`），是否引入对应的 Options dataclass 还是保持具名参数展开（建议保持具名参数以便于 IDE 自动补全）；
3. 单元测试针对各个新增方法的参数组装顺序断言与覆盖度细节。
