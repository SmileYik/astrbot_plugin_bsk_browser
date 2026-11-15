# Design Document: BskCli Semantic Wrapper Layer and Safe Tab Closure

- **Date**: 2026-11-15
- **Author**: Assistant & User
- **Status**: Draft / Proposed

---

## 1. Intent and Why

### 1.1 背景与现状分析
在真实运行与最新日志分析（`logs/astrbot-2026-11-15-17.54.log`）以及界面截图（`logs/astrbot-2026-11-15-16.45.png`）中，暴露出一个严重的多标签页资源残留缺陷：
1. **外链/弹窗标签页泄漏残留**：当机器人在页面（如百度搜索结果）中点击触发了新标签页（`target="_blank"`），浏览器窗口中同时存在主搜索页和新弹出的次级页面（如贴吧页）。当会话结束或超时回收时，系统尝试清理多余标签页，但底层 BrowserSkill 协作控制机制对直接调用 `tab close` 执行了严格的权限拦截，报错：
   `permission_denied: This action requires an unused strict observation from cooperate sync`。
   此时即使后续执行了 `session stop`，由于 `bsk` 扩展对存在次级标签的窗口启用了保护，导致新弹出的外链标签页留在桌面 Chrome 中，无法被销毁。
2. **后台标签页直接同步触发失效**：即便此前在关闭前增加了 `sync` 调用，但在次级标签页处于后台（非激活）状态时，页面的动态 DOM 变化会使观察令牌失效，抛出 `permission_denied: The strict observation changed before this action` 或 `observation_required`。本地实测证实：**必须严格按照「先切换聚焦（`tab select`）-> 同步获取观察与上下文凭证（`sync`）-> 携带凭据执行关闭（`tab close`）」的顺序，才能 100% 稳定关闭标签页**；且当 Agent Window 中的最后一个标签页被关闭时，窗口与会话会自动优雅销毁。
3. **项目中散落裸调 `runner.run(...)`**：当前在 `session.py`、`service.py` 以及多处测试代码中，大量直接拼接 CLI 字符串列表进行 `runner.run(["tab", ...])` 调用（即“野 runner 调用”），缺少统一的参数类型校验、默认值管理和详细的文档说明，代码可读性与可维护性较差。

### 1.2 目标定位
本设计旨在建立独立的 `BskCli` 语义化包装层，将零散的命令行调用收拢为带有完整文档注释和规范参数的高阶方法，并在全项目中统一复用；同时基于标准流程实现 `close_tab_safe` 安全关闭业务逻辑，彻底根治外链标签页残留泄漏问题。

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **G1 (独立 CLI 客户端层)**：新建 `bsk/cli.py` 并实现 `BskCli` 类，封装 bsk 所有核心子命令（`tab select`、`tab close`、`sync`、`tab list`、`tab create`、`tab borrow`、`tab return`、`session list`、`session start`、`session stop`、`version`、`status` 等）。
- **G2 (完整类型与调用文档)**：`BskCli` 的每个包装方法均具备完整的 Type Hints、参数默认值及详细 Docstring（包含参数说明、返回值、异常及 CLI 参数对应关系）。
- **G3 (标准安全关闭流程)**：在 `BskCli`（或会话管理中）实现 `close_tab_safe(session, tab_id)`：
  1. 调用 `select_tab` 激活并聚焦目标标签页；
  2. 调用 `sync_tab` 获得最新的 `observation_id` 与 `context_id`；
  3. 携带上述凭证调用 `close_tab` 实施关闭。
- **G4 (全生命周期多标签安全清理)**：在 `SessionManager._stop_entry`、`sweep_agent_tabs` 以及 `BskService.tabs("close")` 中，统一使用安全关闭流程逐一清理标签页。会话终止时遍历关闭关联的所有标签页，确保 Chrome 桌面不残留任何孤儿页面。
- **G5 (消灭野 `runner.run` 调用)**：将 `SessionManager` 与 `BskService` 内部原先直接拼接参数调用 `runner.run(...)` / `runner.run_or_raise(...)` 的地方，全部替换为 `BskCli` 对应语义化方法。
- **G6 (架构集成与平滑兼容)**：`BskRunner` 实例自动关联 `BskCli`（如 `runner.cli`），同时可在 `SessionManager` / `BskService` 初始化时显式传入，方便单元测试进行 mock。
- **G7 (日志规范与文档维护)**：遵循 `AGENTS.md`，所有命令执行保持 `DEBUG` 级日志；更新 `skills/bsk-browser/SKILL.md` 中的标签生命周期管理指导。
- **G8 (全面测试验证)**：编写完整的单元测试覆盖 `BskCli` 各方法及 `close_tab_safe` 流程，确保插件已有测试套件 100% 通过。

### Non-Goals
- 修改 `bsk` 二进制可执行文件或 `BrowserSkill` Rust 源码。
- 修改 AstrBot 核心框架或其 Dashboard 逻辑。
- 重构基于 `sessions.execute` 的高阶交互工具流水线（点击、输入、滚动等页内操作仍沿用其现有的会话锁与重试体系，但在需要调底层基础命令时优先复用 CLI 层）。

### Anti-Goals
- 绝不通过 `pkill chrome` 等暴力杀进程方式关闭残留页面，杜绝误伤宿主机日常浏览器进程。
- 绝不静默忽略标签页关闭失败，所有异常需合理降级并记录详细 DEBUG 日志。

---

## 3. Constraints

1. **唯一代码修改范围**：仅修改 `./astrbot_plugin_bsk_browser/` 目录下的代码与文档。
2. **日志规范**：严格使用 AstrBot 日志系统，以 `DEBUG` 等级输出 bsk 命令输入输出与工具调用会话/名称。
3. **版本管理**：任务完成后必须通过 git commit 提交全部改动。
4. **精炼简洁**：提示文本与技能文档在确保准确指导的前提下保持简明扼要。

---

## 4. Approaches

### 4.1 CLI 包装层的组织方式

- **方案 A（独立 `BskCli` 客户端层，选中）**：
  新建 `bsk/cli.py`，专门负责将业务调用映射为具体的 bsk 命令行调用。`BskRunner` 专注于子进程管道管理、UTF-8 编码、超时与取消治理；`BskCli` 专注于命令行参数拼装、类型约束与文档说明。
  - *优点*：职责高度单一，分层清晰，易于维护与扩展；测试时可直接对 `BskCli` 进行打桩或测试参数构造。
  - *缺点*：需新增一个文件及关联关系。
- **方案 B（直接在 `BskRunner` 上增加方法）**：
  在 `bsk/runner.py` 的 `BskRunner` 类中直接定义所有具体子命令包装方法。
  - *缺点*：`runner.py` 职责过载，既管底层 OS 管道 IPC，又管数十个 CLI 子命令的参数拼装，违反单一职责原则。
- **方案 C（纯函数式模块）**：
  在 `cli.py` 中定义无状态独立函数，每次调用需显式传入 `runner`。
  - *缺点*：在面向对象的服务层中传参冗余，且不利于统一 mock。

**决策**：采用 **方案 A**。

---

## 5. Detailed Design & Architecture

### 5.1 `bsk/cli.py` 核心实现

定义 `BskCli` 类，接受 `runner: BskRunner`：

```python
class BskCli:
    """bsk 命令行接口的强类型语义化包装客户端。
    
    负责将高阶方法调用转换为严格符合 bsk CLI 协议的参数列表，
    并由底层的 BskRunner 调度执行。
    """
    def __init__(self, runner: BskRunner):
        self._runner = runner

    # --- 标签管理相关包装方法 ---

    async def select_tab(
        self,
        session: str,
        tab_id: int | str,
        *,
        json: bool = True,
        timeout: float = 5.0,
    ) -> BskResult:
        """激活并聚焦指定的标签页。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 目标标签页 ID (必填)。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 超时时间（秒，默认 5.0）。

        Returns:
            BskResult 执行结果。
        """
        params = ["tab", "select", str(tab_id), "--session", session]
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    async def sync_tab(
        self,
        session: str,
        tab_id: int | str | None = None,
        *,
        json: bool = True,
        timeout: float = 5.0,
    ) -> BskResult:
        """同步指定标签页（或活动标签页）的 VOM 快照与协同控制凭证。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 目标标签页 ID（可选，默认为当前激活标签）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 超时时间（秒，默认 5.0）。

        Returns:
            BskResult 包含 observation_id 与 context_id 的执行结果。
        """
        params = ["sync", "--session", session]
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    async def close_tab(
        self,
        session: str,
        tab_id: int | str,
        *,
        observation: str | None = None,
        context: str | None = None,
        json: bool = True,
        timeout: float = 5.0,
    ) -> BskResult:
        """关闭指定的标签页。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 待关闭的标签页 ID (必填)。
            observation: 来自 sync 响应的 observation_id 凭据（可选，协同模式下建议携带）。
            context: 来自 sync 响应的 context_id 凭据（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 超时时间（秒，默认 5.0）。

        Returns:
            BskResult 执行结果。
        """
        params = ["tab", "close", str(tab_id), "--session", session]
        if observation:
            params.extend(["--observation", observation])
        if context:
            params.extend(["--context", context])
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    async def list_tabs(
        self,
        session: str | None = None,
        *,
        scope: str = "agent",
        json: bool = True,
        timeout: float = 5.0,
    ) -> BskResult:
        """列出可见的标签页列表。"""
        params = ["tab", "list", "--scope", scope]
        if session:
            params.extend(["--session", session])
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    async def create_tab(
        self,
        session: str,
        url: str | None = None,
        *,
        active: bool = True,
        json: bool = True,
        timeout: float = 5.0,
    ) -> BskResult:
        """在 Agent Window 中创建新标签页。"""
        params = ["tab", "create", "--session", session]
        if url:
            params.extend(["--url", url])
        if not active:
            params.append("--no-active")
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    # --- 高阶安全组合业务方法 ---

    async def close_tab_safe(
        self,
        session: str,
        tab_id: int | str,
        *,
        timeout: float = 5.0,
    ) -> BskResult:
        """安全关闭标签页的标准业务流程。
        
        执行步骤：
        1. select_tab: 确保目标标签处于激活/聚焦状态，避免后台状态同步失效；
        2. sync_tab: 提取最新的 observation_id 与 context_id；
        3. close_tab: 携带凭证执行关闭，解除 observation_required 限制。
        """
        # 1. 先切换聚焦
        try:
            await self.select_tab(session, tab_id, timeout=timeout)
        except Exception:
            pass

        # 2. 同步获取凭据
        obs_id: str | None = None
        ctx_id: str | None = None
        try:
            sync_res = await self.sync_tab(session, tab_id=tab_id, timeout=timeout)
            raw = sync_res.data if isinstance(sync_res.data, dict) else {}
            obs_id = raw.get("observation_id") or raw.get("obs")
            ctx_id = raw.get("context_id") or raw.get("ctx")
        except Exception:
            pass

        # 3. 携带凭证关闭
        return await self.close_tab(
            session,
            tab_id,
            observation=obs_id,
            context=ctx_id,
            timeout=timeout,
        )

    # --- 会话生命周期包装方法 ---

    async def list_sessions(self, *, json: bool = True, timeout: float = 10.0) -> BskResult:
        """列出当前所有活跃的浏览器会话。"""
        params = ["session", "list"]
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    async def stop_session(self, session_id: str, *, json: bool = False, timeout: float = 15.0) -> BskResult:
        """停止指定的浏览器会话。"""
        params = ["session", "stop", session_id]
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    # --- 系统与状态包装方法 ---

    async def get_version(self, *, json: bool = True, timeout: float = 5.0) -> BskResult:
        """获取 bsk 版本信息。"""
        params = ["version"]
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    async def get_status(self, *, json: bool = True, timeout: float = 10.0) -> BskResult:
        """获取 bsk 守护进程及浏览器运行状态。"""
        params = ["status"]
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)
```

### 5.2 `SessionManager` 与 `BskService` 重构

1. **`SessionManager` 集成**：
   - 持有 `self._cli = getattr(runner, "cli", None) or BskCli(runner)`；
   - 会话停止与清理流程 `_stop_entry(entry)`：
     ```python
     # 获取该会话下的所有标签页
     res = await self._cli.list_tabs(session=entry.session.session_id, scope="agent")
     # 提取所有有效的 tab_id 列表
     tabs = ...
     # 遍历所有标签页（包括次级弹窗页与主页），依次执行 safe_close
     for tid in tabs:
         await self._cli.close_tab_safe(entry.session.session_id, tid)
     
     # 若 Agent Window 仍未自动关闭，再兜底执行 stop_session
     await self._cli.stop_session(entry.session.session_id)
     ```
   - 其他地方（如 `list_sessions`、`sweep_dead_sessions`）全部替换为调用 `self._cli.list_sessions()`。

2. **`BskService` 集成**：
   - 暴露 `self.cli = self.runner.cli`；
   - `ping()` 替换为 `await self.cli.get_version()`；
   - `status()` 替换为 `await self.cli.get_status()`；
   - `tabs(action="close", tab_id=...)` 统一委托给 `close_tab_safe` 流程。

---

## 6. What's Left to the Builder

- 可以在 `BskCli` 中补充其他常用 bsk 指令（如 `borrow_tab`、`return_tab`、`observe` 等）的语义化包装。
- 对于 `BskRunner.run_or_raise` 的语义，可在 `BskCli` 的各方法中支持参数控制（如 `raise_on_error: bool = False`），或提供对应的 `_or_raise` 变体，以便更灵活地配合异常抛出与分类机制。
- 确保测试用例覆盖全部新增包装方法与异常场景。

---

## 7. Verification Plan

1. **单元测试验证**：
   - 运行针对 `BskCli` 的专属测试 `tests/test_cli_wrapper.py`，验证每个包装方法的命令行参数组装、默认值、凭证传递与 docstring 完备性。
   - 运行标签生命周期与安全清理测试 `tests/test_tab_lifecycle_cleanup.py`，验证 `close_tab_safe` 的调用序列（`select` -> `sync` -> `close`）及多标签回收逻辑。
2. **本地集成测试**：
   - 基于本地 `./bsk` 真实进程运行测试验证脚本，模拟打开百度、点击搜索结果弹出新标签，随后触发退出，验证两个标签页均被完全关闭且 Chrome 无残留窗口。
3. **插件全量测试**：
   - 运行 `pytest` 确保现有全量测试套件 100% 通过。
