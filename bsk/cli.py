"""bsk 命令行调用的语义化包装层 (BskCli)。

提供针对 bsk 各 CLI 指令的强类型、具名参数包装方法与完备文档，
统一集中处理命令行参数的组装，消除零散的手动拼接 runner 调用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .models import BskResult
    from .runner import BskRunner


class BskCli:
    """bsk 命令行接口的强类型语义化包装客户端。

    所有方法均封装对底层 ``BskRunner`` 的调度执行，支持完整的参数类型注解、
    默认参数规范、可选的异常抛出控制（``raise_on_error``），以及高阶业务流程（例如安全关闭标签页）。
    """

    def __init__(self, runner: BskRunner) -> None:
        """初始化 BskCli。

        Args:
            runner: 底层 BskRunner 子进程执行器实例。
        """
        self._runner = runner

    async def _execute(
        self,
        args: list[str],
        *,
        timeout: float,
        raise_on_error: bool = False,
        expect_json: bool = True,
    ) -> BskResult:
        """统一底层执行分发器。

        Args:
            args: CLI 参数列表。
            timeout: 超时时间（秒）。
            raise_on_error: 是否在非零退出码或错误时抛出 BskError 系列异常（默认 False）。
            expect_json: 是否期望 JSON 解析（默认 True）。

        Returns:
            BskResult 执行结果。
        """
        if raise_on_error:
            if not expect_json:
                return await self._runner.run_or_raise(
                    args, timeout=timeout, expect_json=False
                )
            return await self._runner.run_or_raise(args, timeout=timeout)
        if not expect_json:
            return await self._runner.run(args, timeout=timeout, expect_json=False)
        return await self._runner.run(args, timeout=timeout)

    # =========================================================================
    # 标签管理 (Tab Commands)
    # =========================================================================

    async def select_tab(
        self,
        session: str,
        tab_id: int | str,
        *,
        json: bool = True,
        timeout: float = 5.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """激活并聚焦指定的标签页。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 目标标签页 ID (必填)。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["tab", "select", str(tab_id), "--session", str(session)]
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def sync_tab(
        self,
        session: str,
        tab_id: int | str | None = None,
        *,
        wait_for: str = "",
        wait_not: str = "",
        timeout_ms: int | None = None,
        max_tokens: int | None = None,
        json: bool = True,
        timeout: float = 5.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """同步指定标签页（或当前激活标签页）的 VOM 快照与协同控制凭据。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 目标标签页 ID（可选，默认为会话当前激活标签）。
            wait_for: 等待特定元素出现（可选）。
            wait_not: 等待特定元素消失（可选）。
            timeout_ms: 超时毫秒数（可选）。
            max_tokens: 最大 token 数（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 包含 observation_id 与 context_id 的执行结果。
        """
        params = ["sync", "--session", str(session)]
        if wait_for:
            params.extend(["--wait-for", str(wait_for)])
        if wait_not:
            params.extend(["--wait-not", str(wait_not)])
        if timeout_ms is not None:
            params.extend(["--timeout-ms", str(int(timeout_ms))])
        if max_tokens is not None:
            params.extend(["--max-tokens", str(int(max_tokens))])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def close_tab(
        self,
        session: str,
        tab_id: int | str,
        *,
        observation: str | None = None,
        context: str | None = None,
        json: bool = True,
        timeout: float = 5.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """关闭指定的标签页。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 待关闭的标签页 ID (必填)。
            observation: 来自 sync 响应的 observation_id 凭据（可选，严格协同模式下必填）。
            context: 来自 sync 响应的 context_id 凭据（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["tab", "close", str(tab_id), "--session", str(session)]
        if observation:
            params.extend(["--observation", str(observation)])
        if context:
            params.extend(["--context", str(context)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def list_tabs(
        self,
        session: str | None = None,
        *,
        scope: str | None = "agent",
        json: bool = True,
        timeout: float = 5.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """列出指定范围或会话中的标签页列表。

        Args:
            session: 浏览器会话标识 (Session ID)；若为 None 则列出全局/默认范围。
            scope: 范围限定，如 'agent' 或 'user'（默认 'agent'；为 None 时不传 --scope）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 包含 tabs 列表的执行结果。
        """
        params = ["tab", "list"]
        if scope:
            params.extend(["--scope", str(scope)])
        if session:
            params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def create_tab(
        self,
        session: str,
        url: str | None = None,
        *,
        index: int | None = None,
        active: bool = True,
        json: bool = True,
        timeout: float = 5.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """在 Agent Window 中创建新标签页。

        Args:
            session: 浏览器会话标识 (Session ID)。
            url: 目标 URL（可选，默认打开空白页或起始页）。
            index: 在标签栏中的插入位置（可选）。
            active: 是否自动激活新标签页（默认 True；为 False 时传 --no-active 作为后台标签打开）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果，包含新建的 tab_id。
        """
        params = ["tab", "create", "--session", str(session)]
        if url:
            params.extend(["--url", str(url)])
        if index is not None:
            params.extend(["--index", str(int(index))])
        if not active:
            params.append("--no-active")
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def borrow_tab(
        self,
        session: str,
        tab_id: int | str,
        *,
        json: bool = True,
        timeout: float = 5.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """将用户标签页借入 Agent Window。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 要借入的用户标签页 ID (必填)。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["tab", "borrow", str(tab_id), "--session", str(session)]
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def return_tab(
        self,
        session: str,
        tab_id: int | str,
        *,
        json: bool = True,
        timeout: float = 5.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """将借入的标签页归还至用户窗口。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 要归还的标签页 ID (必填)。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["tab", "return", str(tab_id), "--session", str(session)]
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    # =========================================================================
    # 会话管理 (Session Commands)
    # =========================================================================

    async def list_sessions(
        self,
        *,
        json: bool = True,
        timeout: float = 10.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """列出当前所有活跃的浏览器会话。

        Args:
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 10.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 包含 sessions 列表的执行结果。
        """
        params = ["session", "list"]
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def start_session(
        self,
        session_id: str | None = None,
        *,
        browser_id: str | None = None,
        request_id: str | None = None,
        headless: bool | None = None,
        incognito: bool | None = None,
        focus: bool = True,
        extra_args: list[str] | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """创建并启动一个新的浏览器会话。

        Args:
            session_id: 自定义会话 ID（可选，None 时由 bsk 自动生成）。
            browser_id: 目标浏览器实例 ID（可选）。
            request_id: 可恢复启动令牌 ID（可选）。
            headless: 是否无头运行（可选）。
            incognito: 是否开启无痕模式（可选）。
            focus: 是否激活窗口焦点（默认 True；为 False 时传递 --no-focus）。
            extra_args: 额外的命令行参数列表（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 启动超时时间（秒，默认 30.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["session", "start"]
        if not focus:
            params.append("--no-focus")
        if session_id:
            params.extend(["--session", str(session_id)])
        if browser_id:
            params.extend(["--browser", str(browser_id)])
        if headless is True:
            params.append("--headless")
        elif headless is False:
            params.append("--no-headless")
        if incognito is True:
            params.append("--incognito")
        if extra_args:
            params.extend([str(item) for item in extra_args])
        if request_id:
            params.extend(["--request-id", str(request_id)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def stop_session(
        self,
        session_id: str,
        *,
        json: bool = False,
        timeout: float = 15.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """停止指定的浏览器会话并回收其 Agent Window。

        Args:
            session_id: 待停止的会话 ID (必填)。
            json: 是否输出 JSON 格式（默认 False）。
            timeout: 停止超时时间（秒，默认 15.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["session", "stop", str(session_id)]
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def request_probe(
        self,
        *,
        timeout: float = 2.0,
    ) -> BskResult:
        """探测 bsk 是否支持 session request 子命令协议。

        Args:
            timeout: 超时时间（秒，默认 2.0）。

        Returns:
            BskResult 执行结果。
        """
        params = ["session", "request", "--help"]
        return await self._execute(
            params, timeout=timeout, raise_on_error=True, expect_json=False
        )

    async def request_command(
        self,
        args: list[str],
        *,
        timeout: float = 10.0,
        raise_on_error: bool = True,
    ) -> BskResult:
        """执行 session request 相关生命周期协议命令。

        Args:
            args: 完整参数列表（如 ['session', 'request', ...]）。
            timeout: 超时时间（秒，默认 10.0）。
            raise_on_error: 失败时是否抛出异常（默认 True）。

        Returns:
            BskResult 执行结果。
        """
        return await self._execute(
            args, timeout=timeout, raise_on_error=raise_on_error, expect_json=True
        )

    # =========================================================================
    # 系统与诊断 (System Commands)
    # =========================================================================

    async def list_browsers(
        self,
        *,
        json: bool = True,
        timeout: float = 5.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """列出已连接的浏览器实例列表。

        Args:
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 超时时间（秒，默认 5.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 包含浏览器实例列表的执行结果。
        """
        params = ["browsers"]
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def get_version(
        self,
        *,
        json: bool = True,
        timeout: float = 5.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """获取 bsk 可执行文件的版本信息。

        Args:
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 超时时间（秒，默认 5.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 包含 version 信息的执行结果。
        """
        params = ["version"]
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def get_status(
        self,
        *,
        json: bool = True,
        timeout: float = 10.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """获取 bsk 守护进程及浏览器连接状态。

        Args:
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 超时时间（秒，默认 10.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 包含守护进程诊断状态的执行结果。
        """
        params = ["status"]
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    # =========================================================================
    # 导航与页面控制 (Navigation Commands)
    # =========================================================================

    async def navigate(
        self,
        session: str,
        target: str,
        *,
        observation: str | None = None,
        wait_until: str = "load",
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 45.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """导航到指定 URL 或历史方向（back/forward）。

        Args:
            session: 浏览器会话标识 (Session ID)。
            target: 目标 URL 或历史方向 ('back' / 'forward')。
            observation: 协同凭证 observation_id（可选）。
            wait_until: 等待生命周期状态（'load' / 'commit' / 'domcontentloaded' / 'networkidle'，默认 'load'）。
            timeout_ms: bsk 内部硬超时毫秒数（可选）。
            tab_id: 目标标签页 ID（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 45.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["navigate", str(target)]
        if observation:
            params.extend(["--observation", str(observation)])
        if wait_until and wait_until != "load":
            params.extend(["--wait-until", str(wait_until)])
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def reload(
        self,
        session: str,
        *,
        hard: bool = False,
        wait_until: str = "load",
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 15.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """刷新当前激活的标签页。

        Args:
            session: 浏览器会话标识 (Session ID)。
            hard: 是否绕过缓存硬刷新（默认 False）。
            wait_until: 等待生命周期状态（默认 'load'）。
            timeout_ms: bsk 内部硬超时毫秒数（可选）。
            tab_id: 目标标签页 ID（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 15.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["reload"]
        if hard:
            params.append("--hard")
        if wait_until and wait_until != "load":
            params.extend(["--wait-until", str(wait_until)])
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def wait_for_navigation(
        self,
        session: str,
        *,
        wait_until: str = "load",
        timeout_ms: int = 30000,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 35.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """等待页面生命周期事件。

        Args:
            session: 浏览器会话标识 (Session ID)。
            wait_until: 等待生命周期状态（默认 'load'）。
            timeout_ms: bsk 内部硬超时毫秒数（默认 30000）。
            tab_id: 目标标签页 ID（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 35.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["wait-for-navigation"]
        if wait_until and wait_until != "load":
            params.extend(["--wait-until", str(wait_until)])
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    # =========================================================================
    # 观察与 DOM 检查 (Observe & Inspection Commands)
    # =========================================================================

    async def observe(
        self,
        session: str,
        *,
        cursor: str = "",
        max_depth: int | None = None,
        max_tokens: int | None = None,
        probe_hover: bool = False,
        debug_surfaces: bool = False,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 15.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """读取当前页面的语义结构 (VOM)。

        Args:
            session: 浏览器会话标识 (Session ID)。
            cursor: 分页游标（可选）。
            max_depth: 最大 DOM 深度（可选）。
            max_tokens: 最大 token 数（可选）。
            probe_hover: 是否探测 hover 状态（默认 False）。
            debug_surfaces: 是否开启 surface 调试信息（默认 False）。
            tab_id: 目标标签页 ID（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 15.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["observe"]
        if cursor:
            params.extend(["--cursor", str(cursor)])
        if max_depth is not None:
            params.extend(["--max-depth", str(int(max_depth))])
        if max_tokens is not None:
            params.extend(["--max-tokens", str(int(max_tokens))])
        if probe_hover:
            params.append("--probe-hover")
        if debug_surfaces:
            params.append("--debug-surfaces")
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def snapshot(
        self,
        session: str,
        *,
        max_depth: int | None = None,
        max_tokens: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 15.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """生成带 @eN 引用的纯 aria-snapshot 快照。

        Args:
            session: 浏览器会话标识 (Session ID)。
            max_depth: 最大 DOM 深度（可选）。
            max_tokens: 最大 token 数（可选）。
            tab_id: 目标标签页 ID（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 15.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["snapshot"]
        if max_depth is not None:
            params.extend(["--max-depth", str(int(max_depth))])
        if max_tokens is not None:
            params.extend(["--max-tokens", str(int(max_tokens))])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def get_html(
        self,
        session: str,
        *,
        ref: str = "",
        max_bytes: int = 524288,
        out: str | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 15.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """导出页面或指定元素的原始 HTML。

        Args:
            session: 浏览器会话标识 (Session ID)。
            ref: 目标元素引用（如 @e1，可选）。
            max_bytes: 最大字节数（默认 524288）。
            out: 输出文件路径（可选）。
            tab_id: 目标标签页 ID（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 15.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["get-html", "--max-bytes", str(int(max_bytes))]
        if ref:
            params.extend(["--ref", str(ref)])
        if out:
            params.extend(["--out", str(out)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def evaluate(
        self,
        session: str,
        expression: str,
        *,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 45.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """在页面上下文中执行任意 JavaScript 脚本。

        Args:
            session: 浏览器会话标识 (Session ID)。
            expression: 要执行的 JavaScript 表达式。
            timeout_ms: bsk 内部硬超时毫秒数（可选）。
            tab_id: 目标标签页 ID（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 45.0）。
            raise_on_error: 失败时是否抛出异常（默认 False）。

        Returns:
            BskResult 执行结果。
        """
        params = ["evaluate", str(expression)]
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    # =========================================================================
    # 交互动作 (Interaction Commands)
    # =========================================================================

    async def click(
        self,
        session: str,
        target: str,
        *,
        button: str | None = None,
        click_count: int | None = None,
        modifiers: list[str] | None = None,
        capture_id: str | None = None,
        image_x: int | None = None,
        image_y: int | None = None,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """点击指定的元素或坐标。"""
        params = ["click", str(target)]
        if button:
            params.extend(["--button", str(button)])
        if click_count is not None:
            params.extend(["--click-count", str(int(click_count))])
        if modifiers:
            params.extend(["--modifiers", ",".join(str(m) for m in modifiers)])
        if capture_id:
            params.extend(["--capture", str(capture_id)])
        if image_x is not None:
            params.extend(["--image-x", str(int(image_x))])
        if image_y is not None:
            params.extend(["--image-y", str(int(image_y))])
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def hover(
        self,
        session: str,
        target: str,
        *,
        modifiers: list[str] | None = None,
        settle_ms: int | None = None,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """悬停在指定的元素上。"""
        params = ["hover", str(target)]
        if modifiers:
            params.extend(["--modifiers", ",".join(str(m) for m in modifiers)])
        if settle_ms is not None:
            params.extend(["--settle", format_duration(settle_ms)])
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def scroll_to(
        self,
        session: str,
        target: str,
        *,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """将指定元素滚动至当前视口。"""
        params = ["scroll-to", str(target)]
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def focus(
        self,
        session: str,
        target: str,
        *,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """聚焦指定的元素。"""
        params = ["focus", str(target)]
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def blur(
        self,
        session: str,
        target: str,
        *,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """取消指定元素的焦点。"""
        params = ["blur", str(target)]
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def fill(
        self,
        session: str,
        target: str,
        value: str,
        *,
        no_clear: bool = False,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """填充文本输入框、多行文本或可编辑元素。"""
        params = ["fill", str(target), "--value", str(value)]
        if no_clear:
            params.append("--no-clear")
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def press(
        self,
        session: str,
        key: str,
        *,
        target: str | None = None,
        modifiers: list[str] | None = None,
        observation_id: str | None = None,
        hold_ms: int | None = None,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """发送按键或按键组合。"""
        params = ["press", str(key)]
        if target:
            params.extend(["--ref", str(target)])
        if modifiers:
            params.extend(["--modifiers", ",".join(str(m) for m in modifiers)])
        if observation_id:
            params.extend(["--observation", str(observation_id)])
        if hold_ms is not None:
            params.extend(["--hold-ms", format_duration(hold_ms)])
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def select(
        self,
        session: str,
        target: str,
        values: list[str] | str,
        *,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """设置 select 下拉框的一个或多个选项值。"""
        params = ["select", str(target)]
        v_list = values if isinstance(values, (list, tuple)) else [values]
        for v in v_list:
            params.extend(["--value", str(v)])
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def wheel(
        self,
        session: str,
        *,
        delta_x: int = 0,
        delta_y: int = 0,
        target: str | None = None,
        modifiers: list[str] | None = None,
        observation_id: str | None = None,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """触发鼠标滚轮事件。"""
        params = ["wheel"]
        if target:
            params.append(str(target))
        params.extend(["--delta-x", str(int(delta_x)), "--delta-y", str(int(delta_y))])
        if modifiers:
            params.extend(["--modifiers", ",".join(str(m) for m in modifiers)])
        if observation_id:
            params.extend(["--observation", str(observation_id)])
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def drag(
        self,
        session: str,
        target: str,
        *,
        to_ref: str | None = None,
        to_selector: str | None = None,
        offset_x: int | None = None,
        offset_y: int | None = None,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """拖拽元素到目标元素或相对偏移位置。"""
        params = ["drag", str(target)]
        if to_ref:
            params.extend(["--to-ref", str(to_ref)])
        if to_selector:
            params.extend(["--to-selector", str(to_selector)])
        if offset_x is not None:
            params.extend(["--offset-x", str(int(offset_x))])
        if offset_y is not None:
            params.extend(["--offset-y", str(int(offset_y))])
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def upload(
        self,
        session: str,
        target: str,
        files: list[str] | str,
        *,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """通过文件选择框上传一个或多个文件。"""
        params = ["upload", str(target)]
        f_list = files if isinstance(files, (list, tuple)) else [files]
        for f in f_list:
            params.extend(["--file", str(f)])
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def download(
        self,
        session: str,
        out_path: str,
        *,
        timeout_ms: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 60.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """捕获下载并保存到指定路径。"""
        params = ["download", str(out_path)]
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def wait_for_element(
        self,
        session: str,
        target: str,
        *,
        state: str = "visible",
        timeout_ms: int = 30000,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 35.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """等待元素达到指定状态 (visible/hidden/attached/detached)。"""
        params = ["wait-for-element", str(target), "--state", str(state)]
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def wait_ms(
        self,
        session: str,
        duration_ms: int,
        *,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 35.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """在守护进程端等待指定时间。"""
        params = ["wait-ms", format_duration(duration_ms)]
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def interact(
        self,
        session: str,
        action: str,
        *,
        target: str = "",
        tab_id: int | None = None,
        timeout: float = 30.0,
        raise_on_error: bool = False,
        **opts: Any,
    ) -> BskResult:
        """动态交互动作分发入口。"""
        from .errors import BskError

        normalized_action = action.replace("_", "-")
        target_str = str(opts.get("target") or target or "").strip()

        if normalized_action in ("click", "hover", "scroll-to", "focus", "blur", "fill", "select") and not target_str:
            raise BskError(
                f"{action} 需要 target",
                friendly=f"「{action}」必须指定要操作的元素：给 target 传元素编号（如 @e3）或 CSS 选择器。",
                code="missing_target",
            )

        if normalized_action == "click":
            return await self.click(
                session, target_str, tab_id=tab_id, timeout=timeout, raise_on_error=raise_on_error,
                button=opts.get("button"), click_count=opts.get("click_count"),
                modifiers=opts.get("modifiers"), capture_id=opts.get("capture_id"),
                image_x=opts.get("image_x"), image_y=opts.get("image_y"),
                timeout_ms=opts.get("timeout_ms"),
            )
        if normalized_action == "hover":
            return await self.hover(
                session, target_str, tab_id=tab_id, timeout=timeout, raise_on_error=raise_on_error,
                modifiers=opts.get("modifiers"), settle_ms=opts.get("settle_ms"),
                timeout_ms=opts.get("timeout_ms"),
            )
        if normalized_action == "scroll-to":
            return await self.scroll_to(
                session, target_str, tab_id=tab_id, timeout=timeout, raise_on_error=raise_on_error,
                timeout_ms=opts.get("timeout_ms"),
            )
        if normalized_action == "focus":
            return await self.focus(
                session, target_str, tab_id=tab_id, timeout=timeout, raise_on_error=raise_on_error,
                timeout_ms=opts.get("timeout_ms"),
            )
        if normalized_action == "blur":
            return await self.blur(
                session, target_str, tab_id=tab_id, timeout=timeout, raise_on_error=raise_on_error,
                timeout_ms=opts.get("timeout_ms"),
            )
        if normalized_action == "fill":
            return await self.fill(
                session, target_str, str(opts.get("value", "")), tab_id=tab_id, timeout=timeout,
                raise_on_error=raise_on_error, no_clear=bool(opts.get("no_clear", False)),
                timeout_ms=opts.get("timeout_ms"),
            )
        if normalized_action == "press":
            key = str(opts.get("key") or opts.get("press_key") or "")
            if not key:
                raise BskError(
                    "press 缺少 key",
                    friendly="「press」必须提供 key 参数。",
                    code="missing_argument",
                )
            return await self.press(
                session, key, target=target_str or None, tab_id=tab_id, timeout=timeout,
                raise_on_error=raise_on_error, modifiers=opts.get("modifiers"),
                observation_id=opts.get("observation_id"), hold_ms=opts.get("hold_ms"),
                timeout_ms=opts.get("timeout_ms"),
            )
        if normalized_action == "select":
            vals = opts.get("values") or ([opts["value"]] if "value" in opts else [])
            if not vals:
                raise BskError("select 需要 value", friendly="请提供要选中的选项值。", code="missing_argument")
            return await self.select(
                session, target_str, vals, tab_id=tab_id, timeout=timeout,
                raise_on_error=raise_on_error, timeout_ms=opts.get("timeout_ms"),
            )
        if normalized_action == "wheel":
            return await self.wheel(
                session, delta_x=int(opts.get("delta_x", 0)), delta_y=int(opts.get("delta_y", 0)),
                target=target_str or None, modifiers=opts.get("modifiers"),
                observation_id=opts.get("observation_id"), timeout_ms=opts.get("timeout_ms"),
                tab_id=tab_id, timeout=timeout, raise_on_error=raise_on_error,
            )
        if normalized_action == "drag":
            return await self.drag(
                session, target_str, to_ref=opts.get("to_ref"), to_selector=opts.get("to_selector"),
                offset_x=opts.get("offset_x"), offset_y=opts.get("offset_y"),
                timeout_ms=opts.get("timeout_ms"), tab_id=tab_id, timeout=timeout,
                raise_on_error=raise_on_error,
            )
        if normalized_action == "upload":
            files = opts.get("files") or ([opts["file"]] if "file" in opts else [])
            return await self.upload(
                session, target_str, files, timeout_ms=opts.get("timeout_ms"),
                tab_id=tab_id, timeout=timeout, raise_on_error=raise_on_error,
            )
        if normalized_action == "download":
            return await self.download(
                session, str(opts.get("out") or opts.get("out_path") or ""),
                timeout_ms=opts.get("timeout_ms"), tab_id=tab_id, timeout=timeout,
                raise_on_error=raise_on_error,
            )
        if normalized_action == "wait-for-element":
            return await self.wait_for_element(
                session, target_str, state=str(opts.get("state", "visible")),
                timeout_ms=int(opts.get("timeout_ms", 30000)), tab_id=tab_id,
                timeout=timeout, raise_on_error=raise_on_error,
            )
        if normalized_action == "wait-ms":
            return await self.wait_ms(
                session, int(opts.get("duration_ms", 0)), tab_id=tab_id,
                timeout=timeout, raise_on_error=raise_on_error,
            )
        raise BskError(f"不支持的交互动作: {action}", code="unsupported_action")

    # =========================================================================
    # 日志与诊断 (Console & Diagnostic Commands)
    # =========================================================================

    async def read_console(
        self,
        session: str,
        *,
        since: int = 0,
        limit: int | None = None,
        max_text_chars: int | None = None,
        include_stack: bool = False,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 5.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """读取控制台日志缓冲。"""
        params = ["console", "--since", str(int(since))]
        if limit is not None:
            params.extend(["--limit", str(int(limit))])
        if max_text_chars is not None:
            params.extend(["--max-text-chars", str(int(max_text_chars))])
        if include_stack:
            params.append("--include-stack")
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def read_network(
        self,
        session: str,
        *,
        since: int = 0,
        limit: int | None = None,
        max_text_chars: int | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 5.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """读取网络活动日志缓冲。"""
        params = ["network", "--since", str(int(since))]
        if limit is not None:
            params.extend(["--limit", str(int(limit))])
        if max_text_chars is not None:
            params.extend(["--max-text-chars", str(int(max_text_chars))])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def debug(
        self,
        session: str,
        debug_action: str,
        *,
        id: str | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 10.0,
        raise_on_error: bool = False,
        **extra_args: Any,
    ) -> BskResult:
        """执行页面调试命令。"""
        import json as _json

        params = ["debug", str(debug_action)]
        if id:
            params.append(str(id))
        for k, v in extra_args.items():
            if v is None or v is False or v == "":
                continue
            flag = f"--{k.replace('_', '-')}"
            if v is True:
                params.append(flag)
            elif isinstance(v, (dict, list)):
                params.extend([flag, _json.dumps(v, ensure_ascii=False, separators=(",", ":"))])
            else:
                params.extend([flag, str(v)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    # =========================================================================
    # 视口、截图与环境 (Viewport & Screenshot Commands)
    # =========================================================================

    async def screenshot(
        self,
        session: str,
        *,
        out: str | None = None,
        full_page: bool = False,
        ref: str | None = None,
        selector: str | None = None,
        format: str | None = None,
        quality: int | None = None,
        tab_id: int | None = None,
        scope: str | None = None,
        observation: str | None = None,
        json: bool = True,
        timeout: float = 30.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """页面截图。"""
        params = ["screenshot"]
        if out:
            params.extend(["--out", str(out)])
        if full_page:
            params.append("--full-page")
        if ref:
            params.extend(["--ref", str(ref)])
        if selector:
            params.extend(["--selector", str(selector)])
        if format:
            params.extend(["--format", str(format)])
        if quality is not None:
            params.extend(["--quality", str(int(quality))])
        if scope:
            params.extend(["--scope", str(scope)])
        if observation:
            params.extend(["--observation", str(observation)])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def emulate(
        self,
        session: str,
        *,
        device: str | None = None,
        width: int | None = None,
        height: int | None = None,
        mobile: bool = False,
        no_mobile: bool = False,
        off: bool = False,
        user_agent: str | None = None,
        touch: bool | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 10.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """模拟移动设备视口或环境。"""
        params = ["emulate"]
        if off:
            params.append("--off")
        else:
            if device:
                params.extend(["--device", str(device)])
            if width is not None and height is not None:
                params.extend(["--width", str(int(width)), "--height", str(int(height))])
            elif width is not None:
                params.extend(["--width", str(int(width))])
            elif height is not None:
                params.extend(["--height", str(int(height))])
            if mobile:
                params.append("--mobile")
            elif no_mobile:
                params.append("--no-mobile")
            if user_agent:
                params.extend(["--ua", str(user_agent)])
            if touch is True:
                params.append("--touch")
            elif touch is False:
                params.append("--no-touch")
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def resize_window(
        self,
        session: str,
        width: int,
        height: int,
        *,
        json: bool = True,
        timeout: float = 10.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """调整 Agent Window 窗口尺寸。"""
        params = ["window", "resize", "--width", str(int(width)), "--height", str(int(height)), "--session", str(session)]
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )

    async def request_help(
        self,
        session: str,
        prompt: str,
        *,
        title: str | None = None,
        targets: list[str] | None = None,
        timeout_ms: int | None = None,
        timeout_sec: int | None = None,
        completion_criteria: dict | str | None = None,
        tab_id: int | None = None,
        json: bool = True,
        timeout: float = 60.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """向人类请求交互协助。"""
        import json as _json

        params = ["request-help", "--prompt", str(prompt)]
        if title:
            params.extend(["--title", str(title)])
        for t in targets or []:
            params.extend(["--target", str(t)])
        if timeout_ms is not None:
            params.extend(["--timeout", format_duration(timeout_ms)])
        elif timeout_sec is not None:
            params.extend(["--timeout", f"{int(timeout_sec)}s"])
        if completion_criteria:
            if isinstance(completion_criteria, str):
                params.extend(["--completion-criteria", completion_criteria])
            else:
                params.extend([
                    "--completion-criteria",
                    _json.dumps(completion_criteria, ensure_ascii=False, separators=(",", ":")),
                ])
        if tab_id is not None:
            params.extend(["--tab-id", str(tab_id)])
        params.extend(["--session", str(session)])
        if json:
            params.append("--json")
        return await self._execute(
            params, timeout=timeout, raise_on_error=raise_on_error, expect_json=json
        )


def format_duration(milliseconds: int | float) -> str:
    """把毫秒数转成 bsk 接受的 duration 字符串（例如 1000 -> '1s'）。"""
    ms = int(milliseconds)
    if ms % 1000 == 0:
        return f"{ms // 1000}s"
    return f"{ms}ms"

