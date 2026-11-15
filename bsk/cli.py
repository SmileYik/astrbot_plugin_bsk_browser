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
    默认参数规范以及高阶业务流程（例如安全关闭标签页）。
    """

    def __init__(self, runner: BskRunner) -> None:
        """初始化 BskCli。

        Args:
            runner: 底层 BskRunner 子进程执行器实例。
        """
        self._runner = runner

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
    ) -> BskResult:
        """激活并聚焦指定的标签页。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 目标标签页 ID (必填)。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。

        Returns:
            BskResult 执行结果。
        """
        params = ["tab", "select", str(tab_id), "--session", str(session)]
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
        """同步指定标签页（或当前激活标签页）的 VOM 快照与协同控制凭据。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 目标标签页 ID（可选，默认为会话当前激活标签）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。

        Returns:
            BskResult 包含 observation_id 与 context_id 的执行结果。
        """
        params = ["sync", "--session", str(session)]
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
            observation: 来自 sync 响应的 observation_id 凭据（可选，严格协同模式下必填）。
            context: 来自 sync 响应的 context_id 凭据（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。

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
        return await self._runner.run(params, timeout=timeout)

    async def close_tab_safe(
        self,
        session: str,
        tab_id: int | str,
        *,
        timeout: float = 5.0,
    ) -> BskResult:
        """安全关闭标签页的标准业务流程。

        解决直接调用 tab close 遭遇 observation_required 或由于后台标签 DOM
        更新导致 observation_changed 的问题。

        执行标准流程：
        1. select_tab: 先将目标标签页置于激活/聚焦状态，防止后台页面动态更新使观察凭据失效；
        2. sync_tab: 获取该标签页最新的 observation_id 与 context_id 凭据；
        3. close_tab: 携带凭据关闭该标签页。

        对 select 和 sync 步骤中出现的非致命异常做防御性降级，确保最终必然尝试关闭。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 待关闭的标签页 ID (必填)。
            timeout: 每步命令的超时时间（秒，默认 5.0）。

        Returns:
            BskResult 最终 close_tab 的执行结果。
        """
        # 1. 尝试聚焦目标标签
        try:
            await self.select_tab(session, tab_id, timeout=timeout)
        except Exception:  # noqa: BLE001
            pass

        # 2. 尝试同步获取最新凭证
        obs_id: str | None = None
        ctx_id: str | None = None
        try:
            sync_res = await self.sync_tab(session, tab_id=tab_id, timeout=timeout)
            raw = sync_res.data if isinstance(sync_res.data, dict) else {}
            obs_val = raw.get("observation_id") or raw.get("obs")
            ctx_val = raw.get("context_id") or raw.get("ctx")
            if obs_val:
                obs_id = str(obs_val)
            if ctx_val:
                ctx_id = str(ctx_val)
        except Exception:  # noqa: BLE001
            pass

        # 3. 携带凭证执行关闭
        return await self.close_tab(
            session,
            tab_id,
            observation=obs_id,
            context=ctx_id,
            timeout=timeout,
        )


    async def list_tabs(
        self,
        session: str | None = None,
        *,
        scope: str = "agent",
        json: bool = True,
        timeout: float = 5.0,
    ) -> BskResult:
        """列出指定范围或会话中的标签页列表。

        Args:
            session: 浏览器会话标识 (Session ID)；若为 None 则列出全局/默认范围。
            scope: 范围限定，如 'agent' 或 'user'（默认 'agent'）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。

        Returns:
            BskResult 包含 tabs 列表的执行结果。
        """
        params = ["tab", "list", "--scope", str(scope)]
        if session:
            params.extend(["--session", str(session)])
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
        """在 Agent Window 中创建新标签页。

        Args:
            session: 浏览器会话标识 (Session ID)。
            url: 目标 URL（可选，默认打开空白页或起始页）。
            active: 是否自动激活新标签页（默认 True；为 False 时传 --no-active 作为后台标签打开）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。

        Returns:
            BskResult 执行结果，包含新建的 tab_id。
        """
        params = ["tab", "create", "--session", str(session)]
        if url:
            params.extend(["--url", str(url)])
        if not active:
            params.append("--no-active")
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    async def borrow_tab(
        self,
        session: str,
        tab_id: int | str,
        *,
        json: bool = True,
        timeout: float = 5.0,
    ) -> BskResult:
        """将用户标签页借入 Agent Window。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 要借入的用户标签页 ID (必填)。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。

        Returns:
            BskResult 执行结果。
        """
        params = ["tab", "borrow", str(tab_id), "--session", str(session)]
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    async def return_tab(
        self,
        session: str,
        tab_id: int | str,
        *,
        json: bool = True,
        timeout: float = 5.0,
    ) -> BskResult:
        """将借入的标签页归还至用户窗口。

        Args:
            session: 浏览器会话标识 (Session ID)。
            tab_id: 要归还的标签页 ID (必填)。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 5.0）。

        Returns:
            BskResult 执行结果。
        """
        params = ["tab", "return", str(tab_id), "--session", str(session)]
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    # =========================================================================
    # 会话管理 (Session Commands)
    # =========================================================================

    async def list_sessions(
        self,
        *,
        json: bool = True,
        timeout: float = 10.0,
    ) -> BskResult:
        """列出当前所有活跃的浏览器会话。

        Args:
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 命令超时时间（秒，默认 10.0）。

        Returns:
            BskResult 包含 sessions 列表的执行结果。
        """
        params = ["session", "list"]
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    async def start_session(
        self,
        session_id: str | None = None,
        *,
        headless: bool | None = None,
        incognito: bool | None = None,
        json: bool = True,
        timeout: float = 30.0,
    ) -> BskResult:
        """创建并启动一个新的浏览器会话。

        Args:
            session_id: 自定义会话 ID（可选，None 时由 bsk 自动生成）。
            headless: 是否无头运行（可选）。
            incognito: 是否开启无痕模式（可选）。
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 启动超时时间（秒，默认 30.0）。

        Returns:
            BskResult 执行结果。
        """
        params = ["session", "start"]
        if session_id:
            params.extend(["--session", str(session_id)])
        if headless is True:
            params.append("--headless")
        elif headless is False:
            params.append("--no-headless")
        if incognito is True:
            params.append("--incognito")
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    async def stop_session(
        self,
        session_id: str,
        *,
        json: bool = False,
        timeout: float = 15.0,
    ) -> BskResult:
        """停止指定的浏览器会话并回收其 Agent Window。

        Args:
            session_id: 待停止的会话 ID (必填)。
            json: 是否输出 JSON 格式（默认 False）。
            timeout: 停止超时时间（秒，默认 15.0）。

        Returns:
            BskResult 执行结果。
        """
        params = ["session", "stop", str(session_id)]
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    # =========================================================================
    # 系统与诊断 (System Commands)
    # =========================================================================

    async def get_version(
        self,
        *,
        json: bool = True,
        timeout: float = 5.0,
    ) -> BskResult:
        """获取 bsk 可执行文件的版本信息。

        Args:
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 超时时间（秒，默认 5.0）。

        Returns:
            BskResult 包含 version 信息的执行结果。
        """
        params = ["version"]
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)

    async def get_status(
        self,
        *,
        json: bool = True,
        timeout: float = 10.0,
    ) -> BskResult:
        """获取 bsk 守护进程及浏览器连接状态。

        Args:
            json: 是否输出 JSON 格式（默认 True）。
            timeout: 超时时间（秒，默认 10.0）。

        Returns:
            BskResult 包含守护进程诊断状态的执行结果。
        """
        params = ["status"]
        if json:
            params.append("--json")
        return await self._runner.run(params, timeout=timeout)
