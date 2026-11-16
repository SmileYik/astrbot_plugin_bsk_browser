"""bsk 会话生命周期管理。

将 bsk 的会话（session start / session stop）封装为按业务 key 隔离的并发安全对象池。

核心机制：
1. 细粒度隔离：按 key 加锁，实现同一会话内命令严格串行化，不同会话并发执行；
2. 失效自愈：遭遇 not_found（BskSessionGone）时自动重建会话并以新 id 重试一次；
3. 瞬时退避：遭遇 session_busy 短暂重试，未知结果（outcome_unknown）直接上抛；
4. 资源清理：支持空闲主动回收（reap_idle）与全量优雅停止（release_all）；
5. 有界停止：session stop 支持有界重试与总预算兜底，防止阻塞插件终止；
6. 孤儿恢复：结合 journal 持久化所有权记录与可恢复启动协议，在崩溃重启后精确回收遗留会话。

设计约束：零第三方依赖，单调时钟计时，清理路径吞掉异常保证不阻塞上层生命周期。
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import os
import re
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from .errors import (
    CODE_CANCELLED,
    EXIT_TIMEOUT,
    OUTCOME_UNKNOWN_REASONS,
    BskBrowserAmbiguous,
    BskError,
    BskNotInstalled,
    BskOutcomeUnknown,
    BskProtocolError,
    BskSessionBusy,
    BskSessionGone,
    BskStartCancelled,
    BskTimeout,
    BskVersionError,
    is_cancelled_error,
)
from .journal import JournalEntry, SessionJournal, now_seconds
from .logger import NULL_LOGGER, LoggerLike
from .models import BrowserInstance, BskResult, BskSession
from .runner import DEFAULT_CANCEL_GRACE_SEC, DRAIN_TIMEOUT_SEC, BskRunner

if TYPE_CHECKING:  # pragma: no cover - 仅类型检查期存在，运行时不 import
    # config.py 由另一路并行开发，可能存在也可能不存在。
    # 放在 TYPE_CHECKING 里可以两边都跑通：真正 import 它会把本模块
    # 和对方的进度绑死，而运行时我们只用 getattr 读几个属性。
    from .config import Settings

__all__ = [
    "SessionManager",
    "BUSY_RETRY_DELAY_SEC",
    "DEFAULT_IDLE_RELEASE_SEC",
    "DEFAULT_MAX_SESSIONS",
    "LIVE_REQUEST_STATES",
    "REQUEST_PROBE_TIMEOUT_SEC",
    "REQUEST_PROTOCOL_TIMEOUT_SEC",
    "REQUEST_STATE_ACTIVE",
    "REQUEST_STATE_CANCELLING",
    "REQUEST_STATE_CLOSED",
    "REQUEST_STATE_PREPARED",
    "REQUEST_STATE_READY",
    "REQUEST_TOKEN_RE",
    "REQUEST_TOKEN_TTL_MARGIN_SEC",
    "REQUEST_TOKEN_TTL_MAX_SEC",
    "REQUEST_TOKEN_TTL_SEC",
    "STOP_MAX_ATTEMPTS",
    "STOP_RETRY_BUDGET_SEC",
    "STOP_RETRY_DELAY_SEC",
    "STOP_TIMEOUT_SEC",
    "STOP_TOTAL_BUDGET_SEC",
    "TERMINAL_REQUEST_STATES",
]


# --- 可调常量 ---

BUSY_RETRY_DELAY_SEC = 0.1
"""session_busy 后的重试等待时长（秒）。"""

MAX_ATTEMPTS = 2
"""命令最大执行次数（首次执行 + 最多重试 1 次）。"""

DEFAULT_MAX_SESSIONS = 3
"""默认最大并发会话数。与 config.py 保持一致。"""

DEFAULT_IDLE_RELEASE_SEC = 240.0
"""默认空闲回收阈值（秒）。早于 bsk 自身 5 分钟超时以主动归还标签页。"""

DEFAULT_COMMAND_TIMEOUT_SEC = 60.0
"""默认命令执行超时（秒）。"""

START_TIMEOUT_FLOOR_SEC = 30.0
"""session start 最小超时下限（秒），预留浏览器扩展连接时间。"""

STOP_TIMEOUT_SEC = 15.0
"""session stop 单次尝试超时（秒）。"""

STOP_MAX_ATTEMPTS = 3
"""session stop 最大尝试次数（含首次）。覆盖瞬时 cleanup 异常。"""

STOP_RETRY_DELAY_SEC = 0.5
"""session stop 重试间隔时长（秒）。"""

STOP_RETRY_BUDGET_SEC = 5.0
"""session stop 重试阶段额外时间预算（秒）。"""

STOP_RETRY_MIN_TIMEOUT_SEC = 1.0
"""单次 stop 尝试的最低预算门槛（秒）。低于此阈值直接放弃重试。"""

STOP_ATTEMPT_OVERHEAD_SEC = DEFAULT_CANCEL_GRACE_SEC + DRAIN_TIMEOUT_SEC
"""单次 stop 超时后的清理开销（秒，包含优雅取消与管道收尾）。"""

STOP_TOTAL_BUDGET_SEC = (
    STOP_TIMEOUT_SEC + STOP_ATTEMPT_OVERHEAD_SEC + STOP_RETRY_BUDGET_SEC
)
"""session stop 调用的绝对墙钟总上限（秒 = 15 + 17 + 5 = 37s），防止阻塞 terminate。"""

STOP_ATTEMPT_BACKSTOP_MARGIN_SEC = 5.0
"""单次 stop 兜底计时器余量（秒）。"""

STOP_TRANSIENT_ERROR_MARKERS: tuple[str, ...] = (
    "background execution cleanup",
    "cleanup timed out",
    "rpcerror",
    "protocolerror",
    "extension rejected",
    "session_busy",
)
"""判定 session stop 瞬时故障的文本标记元组。"""


def _is_transient_stop_error(exc: BaseException) -> bool:
    """判定 session stop 失败是否属于瞬时故障可安全重试。

    判定规则：
    1. 不可重试类型否决：BskNotInstalled、BskVersionError；
    2. outcome_unknown 错误不重试（由 journal 与孤儿回收兜底）；
    3. 匹配 STOP_TRANSIENT_ERROR_MARKERS 文本标记则重试；
    4. BskTimeout 或 BskSessionBusy 类型重试；
    5. 其他异常不重试。
    """
    if isinstance(exc, (BskNotInstalled, BskVersionError)):
        return False

    reason = getattr(exc, "reason", "")
    if reason in OUTCOME_UNKNOWN_REASONS:
        return False

    haystack = f"{exc}".lower()
    for marker in STOP_TRANSIENT_ERROR_MARKERS:
        if marker in haystack:
            return True

    return isinstance(exc, (BskTimeout, BskSessionBusy))


RECOVER_LIST_TIMEOUT_SEC = 5.0
"""恢复时 session list 的超时（秒）。"""


# --- 可恢复启动（request_id 协议）---
# 在发出 start 前先持久化令牌，即便启动回执丢失也能凭令牌向 daemon 取消孤儿窗口。

REQUEST_TOKEN_TTL_SEC = 300.0
"""令牌有效期下限（秒）。"""

REQUEST_TOKEN_TTL_MAX_SEC = 540.0
"""令牌有效期上限（秒）。"""

REQUEST_TOKEN_TTL_MARGIN_SEC = 60.0
"""令牌有效期时间余量（秒）。"""

REQUEST_PROBE_TIMEOUT_SEC = 10.0
"""可恢复启动能力探测超时（秒）。"""

REQUEST_PROTOCOL_TIMEOUT_SEC = 30.0
"""prepare / claim / cancel / query 协议命令超时（秒）。"""

REQUEST_STATE_PREPARED = "prepared"
"""令牌已预约，窗口尚未创建。"""

REQUEST_STATE_READY = "ready"
"""bsk 已受理启动请求，正在创建窗口。"""

REQUEST_STATE_ACTIVE = "active"
"""窗口已建立并成功认领。"""

REQUEST_STATE_CLOSED = "closed"
"""启动已取消，窗口已关闭。"""

REQUEST_STATE_CANCELLING = "cancelling"
"""启动正在取消中。"""

LIVE_REQUEST_STATES = frozenset({
    REQUEST_STATE_PREPARED, REQUEST_STATE_READY, REQUEST_STATE_ACTIVE, REQUEST_STATE_CANCELLING,
})
"""代表后台可能存在对应窗口的活动状态集。"""

TERMINAL_REQUEST_STATES = frozenset({REQUEST_STATE_CLOSED, "failed"})
"""代表窗口已确认不存在的终态集。"""

REQUEST_TOKEN_RE = re.compile(r"^\d+:[0-9a-f-]{36}$")
"""令牌格式正则：<到期-unix-毫秒>:<UUID>。"""


def _cancelled_from(exc: BaseException) -> BskStartCancelled:
    """把一次 ``code="cancelled"`` 的失败翻译成 BskStartCancelled。"""
    return BskStartCancelled(
        f"可恢复启动被取消：{exc}",
        friendly=("这次浏览器启动已被取消（bsk 回复 cancelled），不会重试、"
                  "也不会改用普通方式重开。如果这不是你预期的，请稍后重新发起一次。"),
        code=CODE_CANCELLED,
        exit_code=getattr(exc, "exit_code", -1),
        reason=getattr(exc, "reason", ""),
    )

RELEASE_WAIT_SEC = 5.0
"""释放会话前最多等多久让 in-flight 命令结束。超过就强行 stop（宁可命令失败，
也不能让 ``terminate()`` 挂住）。"""

RELEASE_POLL_STEP_SEC = 0.02
"""等待 in-flight 命令结束的轮询间隔。

这里刻意用"轮询 ``lock.locked()``"而不是 ``asyncio.wait_for(lock.acquire())``：
后者在超时取消时存在"锁被唤醒后又被取消"的经典边界，可能让锁状态错乱。
释放路径只在关闭/回收时走，轮询的代价可以忽略。
"""

MAX_ENTRY_RETRIES = 4
"""``execute`` 取 entry 的最大尝试次数。

只有当另一个协程在极窄的窗口里疯狂 release 时才可能用满，正常路径一次就够。
加这个上限是为了保证不出现活锁。
"""

ArgsBuilder = Callable[[str], "list[str] | Awaitable[list[str]]"]
"""参数构造函数：接收 session_id，返回完整参数列表（不含 bsk 自身路径）。

之所以要传函数而不是现成列表，是为了让"重建会话后用新 id 重新构造参数"
变得自然 —— 这是自动重建能正确工作的关键。
"""

BrowserProbe = Callable[[], Any]
"""可选的浏览器探测函数：返回 BrowserInstance（或它的列表 / instance_id 字符串）。

可以是同步函数也可以是协程函数，返回结果宽松解析。
"""


def _as_float(value: Any, default: float) -> float:
    """把配置里的任意值安全地转成 float。"""
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    """把配置里的任意值安全地转成 int。"""
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_str(value: Any, default: str = "") -> str:
    """把配置里的任意值安全地转成去空白的字符串。"""
    if isinstance(value, str):
        return value.strip()
    return default


def _setting(settings: Any, name: str, default: Any) -> Any:
    """读一个配置项，缺属性 / 取值非法时回退到默认值。

    刻意用 ``getattr`` 而不是 ``settings.name``：``Settings`` 由另一路并行
    开发，字段名或存在性都可能在变，这里必须容错，不能因为对方少一个字段
    就让整个会话管理起不来。
    """
    if settings is None:
        return default
    return getattr(settings, name, default)


def _adopt(target: BskSession, fresh: BskSession) -> None:
    """把新建成功的会话字段原地写进旧对象。

    这样做的目的：``acquire()`` 返回的 ``BskSession`` 对象在同一个 key 上
    始终保持同一身份，自动重建之后调用方手里的引用不会变成陈旧副本。
    """
    target.session_id = fresh.session_id
    target.browser_instance_id = fresh.browser_instance_id
    target.agent_window_id = fresh.agent_window_id
    target.interaction = fresh.interaction


def _coerce_probe_result(value: Any) -> str:
    """从 ``browser_probe`` 的任意返回值里抠出一个 instance_id。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, BrowserInstance):
        # 无响应的浏览器不能选用（bsk 也会拒绝）。
        return "" if value.unresponsive else value.instance_id.strip()
    if isinstance(value, (list, tuple)):
        for item in value:
            found = _coerce_probe_result(item)
            if found:
                return found
        return ""
    if isinstance(value, dict):
        return _coerce_probe_result(value.get("instance_id"))
    # 鸭子类型兜底：任何带 instance_id 属性的对象。
    return _as_str(getattr(value, "instance_id", None))


@dataclass(slots=True)
class _Entry:
    """会话槽位，包含会话实例、互斥锁及活跃状态。"""

    key: str
    session: BskSession
    lock: asyncio.Lock
    last_used: float
    seq: int = 0
    closed: bool = False


class SessionManager:
    """按 key 管理 bsk 会话的并发安全对象池。

    Args:
        runner: 子进程执行器。
        settings: 插件配置对象。
        cli: 可选的 BskCli 实例。
        browser_probe: 可选的浏览器实例探测器。
        journal: 可选的持久化会话日记账（用于跨进程孤儿回收）。
        stop_max_attempts: 停止会话最大重试次数。
        stop_retry_delay_sec: 停止重试间隔秒数。
        stop_retry_budget_sec: 停止重试总时间预算。
        stop_timeout_sec: 单次停止命令超时秒数。
        stop_total_budget_sec: 停止操作总时间上限。
        stop_attempt_overhead_sec: 单次尝试超时后的清理开销预估。
        stop_attempt_backstop_sec: 单次尝试的硬性墙钟兜底上限。
        logger: 可选日志器。
    """

    def __init__(
        self,
        runner: BskRunner,
        settings: "Settings | Any",
        *,
        cli: Any = None,
        browser_probe: BrowserProbe | None = None,
        journal: SessionJournal | None = None,
        stop_max_attempts: int = STOP_MAX_ATTEMPTS,
        stop_retry_delay_sec: float = STOP_RETRY_DELAY_SEC,
        stop_retry_budget_sec: float = STOP_RETRY_BUDGET_SEC,
        stop_timeout_sec: float = STOP_TIMEOUT_SEC,
        stop_total_budget_sec: float | None = None,
        stop_attempt_overhead_sec: float = STOP_ATTEMPT_OVERHEAD_SEC,
        stop_attempt_backstop_sec: float | None = None,
        logger: LoggerLike | None = None,
    ) -> None:
        self._runner = runner
        from .cli import BskCli

        if cli is not None:
            self._cli = cli
        else:
            runner_cli = getattr(runner, "cli", None)
            if not isinstance(runner_cli, BskCli):
                self._cli = BskCli(runner)
            else:
                self._cli = runner_cli
        self._browser_probe = browser_probe
        self._journal = journal
        self._logger = logger or NULL_LOGGER

        # 初始化 stop 重试参数，防御性校验并回退非法值
        attempts = _as_int(stop_max_attempts, STOP_MAX_ATTEMPTS)
        self._stop_max_attempts = attempts if attempts >= 1 else STOP_MAX_ATTEMPTS
        delay = _as_float(stop_retry_delay_sec, STOP_RETRY_DELAY_SEC)
        self._stop_retry_delay_sec = delay if delay >= 0 else STOP_RETRY_DELAY_SEC
        budget = _as_float(stop_retry_budget_sec, STOP_RETRY_BUDGET_SEC)
        self._stop_retry_budget_sec = budget if budget > 0 else STOP_RETRY_BUDGET_SEC
        timeout = _as_float(stop_timeout_sec, STOP_TIMEOUT_SEC)
        self._stop_timeout_sec = timeout if timeout > 0 else STOP_TIMEOUT_SEC
        overhead = _as_float(stop_attempt_overhead_sec, STOP_ATTEMPT_OVERHEAD_SEC)
        self._stop_attempt_overhead_sec = (
            overhead if overhead >= 0 else STOP_ATTEMPT_OVERHEAD_SEC
        )
        if stop_total_budget_sec is None:
            self._stop_total_budget_sec = (
                self._stop_timeout_sec
                + self._stop_attempt_overhead_sec
                + self._stop_retry_budget_sec
            )
        else:
            total = _as_float(stop_total_budget_sec, 0.0)
            self._stop_total_budget_sec = (
                total if total > 0 else self._stop_timeout_sec
            )
        if stop_attempt_backstop_sec is None:
            self._stop_attempt_backstop_sec = (
                self._stop_timeout_sec
                + self._stop_attempt_overhead_sec
                + STOP_ATTEMPT_BACKSTOP_MARGIN_SEC
            )
        else:
            backstop = _as_float(stop_attempt_backstop_sec, 0.0)
            self._stop_attempt_backstop_sec = (
                backstop if backstop > 0 else self._stop_timeout_sec
            )
        self._stop_attempt_backstop_sec = min(
            self._stop_attempt_backstop_sec, self._stop_total_budget_sec
        )

        self._max_sessions = max(
            1, _as_int(_setting(settings, "max_sessions", DEFAULT_MAX_SESSIONS),
                       DEFAULT_MAX_SESSIONS)
        )
        idle = _as_float(
            _setting(settings, "idle_release_sec", DEFAULT_IDLE_RELEASE_SEC),
            DEFAULT_IDLE_RELEASE_SEC,
        )
        self._idle_release_sec = idle
        self._browser_instance_id = _as_str(
            _setting(settings, "browser_instance_id", "")
        )
        self._command_timeout = _as_float(
            _setting(settings, "command_timeout_sec", DEFAULT_COMMAND_TIMEOUT_SEC),
            DEFAULT_COMMAND_TIMEOUT_SEC,
        )
        if self._command_timeout <= 0:
            self._command_timeout = DEFAULT_COMMAND_TIMEOUT_SEC
        self._start_timeout = max(START_TIMEOUT_FLOOR_SEC, self._command_timeout)

        # 可恢复启动配置与协议支持状态
        self._enable_request_id = bool(
            _setting(settings, "enable_request_id", True)
        )
        self._request_protocol: bool | None = None

        self._entries: dict[str, _Entry] = {}
        self._registry_lock = asyncio.Lock()

        self._seq = 0
        self._closed = False
        self._clock: Callable[[], float] = time.monotonic

        self._counters: dict[str, int] = {
            "started": 0,
            "rebuilt": 0,
            "stopped": 0,
            "stop_failed": 0,
            "busy_retries": 0,
            "evicted": 0,
            "reaped": 0,
            "not_found_rebuilds": 0,
            # stop 重试指标
            "stop_retries": 0,
            "stop_recovered": 0,
            "stop_retry_budget_skips": 0,
            # 可恢复启动指标
            "request_protocol_unsupported": 0,
            "request_protocol_disabled": 0,
            "request_write_ahead_failed": 0,
            "request_start_failed": 0,
            "request_cancelled": 0,
            "request_claim_failed": 0,
            "request_orphans_cancelled": 0,
        }
        self._recent_stop_errors: list[str] = []

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    async def acquire(self, key: str, *, start_args: Sequence[str] = ()) -> BskSession:
        """获取（必要时创建）指定 key 的会话。

        同一 key 并发调用共享同一会话实例。

        Args:
            key: 会话键。
            start_args: 仅新建会话时追加到 ``session start`` 的参数（如窗口尺寸）。已有会话时忽略。

        Returns:
            BskSession 实例。
        """
        self._ensure_open()
        extra = tuple(str(item) for item in start_args)
        async with self._locked_entry(key) as entry:
            await self._ensure_session(entry, start_args=extra)
            self._touch(entry)
            self._logger.debug(
                "[会话获取] key=%s, 会话ID=%s, 窗口ID=%s | 当前总会话数: %d",
                key,
                entry.session.session_id or "(未建立)",
                entry.session.agent_window_id,
                self._active_session_count(),
            )
            return entry.session

    async def execute_action(
        self,
        key: str,
        action: Any,
        *,
        timeout: float | None = None,
    ) -> BskResult:
        """核心方法：带上会话 id 调度执行一个异步 CLI 动作 (BskCli 方法调用)。

        自动处理：per-key 加锁（同 key 串行）、会话失效时重建并带新 session_id 重试、
        ``session_busy`` 短暂重试。结果未知错误不重试直接上抛。任何情况下都只重试一次。

        Args:
            key: 业务键（umo 等）。
            action: 接收 session_id 并返回 Awaitable[BskResult] 的可调用对象。
            timeout: 超时秒数；None 时用 ``settings.command_timeout_sec``。

        Returns:
            成功的 BskResult。
        """
        self._ensure_open()

        async with self._locked_entry(key) as entry:
            await self._ensure_session(entry)
            self._touch(entry)

            for attempt in range(1, MAX_ATTEMPTS + 1):
                try:
                    res = action(entry.session.session_id)
                    if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                        result = await res
                    else:
                        result = res
                except BskOutcomeUnknown:
                    raise
                except BskError as exc:
                    if exc.reason in OUTCOME_UNKNOWN_REASONS:
                        raise

                    if isinstance(exc, BskSessionGone):
                        if attempt >= MAX_ATTEMPTS or entry.closed:
                            raise
                        self._counters["not_found_rebuilds"] += 1
                        await self._restart(entry, stop_old=False)
                        self._logger.info(
                            "会话 %s 已失效，已重建为 %s，重试一次",
                            key,
                            entry.session.session_id,
                        )
                        continue

                    if isinstance(exc, BskSessionBusy):
                        if attempt >= MAX_ATTEMPTS:
                            raise
                        self._counters["busy_retries"] += 1
                        await asyncio.sleep(BUSY_RETRY_DELAY_SEC)
                        continue

                    raise

                self._touch(entry)
                return result

            raise AssertionError("unreachable")

    async def execute(
        self,
        key: str,
        args_builder: ArgsBuilder,
        *,
        timeout: float | None = None,
    ) -> BskResult:
        """核心方法：带上会话 id 执行一条 bsk 命令（兼容层，内部转调 execute_action）。

        Args:
            key: 业务键（umo 等）。
            args_builder: 接收 ``session_id`` 返回完整参数列表的可调用对象。
            timeout: 超时秒数；None 时用 ``settings.command_timeout_sec``。

        Returns:
            成功的 ``BskResult``。
        """
        effective_timeout = (
            float(timeout) if timeout is not None else self._command_timeout
        )

        async def _run_args(sid: str) -> BskResult:
            args = await self._build_args(args_builder, sid)
            return await self._runner.run_or_raise(args, timeout=effective_timeout)

        return await self.execute_action(
            key,
            _run_args,
            timeout=effective_timeout,
        )

    async def close_tab_safe(
        self,
        key_or_session_id: str,
        tab_id: int | str,
        *,
        timeout: float = 5.0,
        raise_on_error: bool = False,
    ) -> BskResult:
        """安全关闭标签页的标准业务流程（聚焦 -> 同步凭证 -> 携带凭证关闭）。"""
        session_id = str(key_or_session_id)
        if key_or_session_id in self._entries:
            entry = self._entries[key_or_session_id]
            if entry.session and entry.session.session_id:
                session_id = entry.session.session_id

        # 1. 尝试聚焦目标标签
        try:
            await self._cli.select_tab(session_id, tab_id, timeout=timeout)
        except Exception:
            pass

        # 2. 尝试同步获取最新凭据
        obs_id: str | None = None
        ctx_id: str | None = None
        try:
            sync_res = await self._cli.sync_tab(session_id, tab_id=tab_id, timeout=timeout)
            raw = sync_res.data if isinstance(sync_res.data, dict) else {}
            obs_val = raw.get("observation_id") or raw.get("obs")
            ctx_val = raw.get("context_id") or raw.get("ctx")
            if obs_val:
                obs_id = str(obs_val)
            if ctx_val:
                ctx_id = str(ctx_val)
        except Exception:
            pass

        # 3. 携带凭据执行关闭
        return await self._cli.close_tab(
            session_id,
            tab_id,
            observation=obs_id,
            context=ctx_id,
            timeout=timeout,
            raise_on_error=raise_on_error,
        )

    async def release(self, key: str) -> bool:
        """显式关闭并移除指定 key 的会话。绝不抛异常。

        等待进行中的命令结束后调用 ``session stop <id>``。

        Returns:
            True 表示会话已确认停止；False 表示不存在或停止失败。
        """
        entry = self._entries.pop(key, None)
        if entry is None:
            return False
        entry.closed = True
        self._logger.debug(
            "[会话释放] 释放会话 key=%s (会话ID=%s) | 剩余槽位数: %d",
            key,
            entry.session.session_id or "(未建立)",
            len(self._entries),
        )
        try:
            await self._wait_idle(entry, RELEASE_WAIT_SEC)
            return await self._stop_entry(entry)
        except Exception as exc:  # noqa: BLE001 - 清理路径必须吞掉一切
            self._logger.warning("释放会话 %s 时出现意外错误：%r", key, exc)
            self._record_stop_error(f"{key}: {exc!r}")
            return False

    async def release_all(self) -> int:
        """并发关闭所有会话，返回成功关闭的数量。绝不抛异常。"""
        entries: list[_Entry] = []
        for key in list(self._entries.keys()):
            entry = self._entries.pop(key, None)
            if entry is not None:
                entry.closed = True
                entries.append(entry)
        if not entries:
            return 0
        return await self._shutdown_entries(entries)

    async def reap_idle(self) -> int:
        """回收空闲超时的会话，返回回收数量。正在执行命令的会话跳过。"""
        if self._idle_release_sec <= 0 or not self._entries:
            return 0

        now = self._clock()
        victims: list[_Entry] = []
        for key in list(self._entries.keys()):
            entry = self._entries.get(key)
            if entry is None or entry.lock.locked():
                continue
            if now - entry.last_used >= self._idle_release_sec:
                popped = self._entries.pop(key, None)
                if popped is not None:
                    popped.closed = True
                    victims.append(popped)
                    self._logger.debug(
                        "[会话超时] 会话 %s (key=%s) 空闲超时 (已空闲 %.1fs >= 阈值 %.1fs) 执行回收",
                        popped.session.session_id or "(未建立)",
                        key,
                        now - entry.last_used,
                        self._idle_release_sec,
                    )

        if not victims:
            return 0
        count = await self._shutdown_entries(victims)
        self._counters["reaped"] += count
        self._logger.info("空闲回收了 %d 个浏览器会话", count)
        self._logger.debug(
            "[会话超时回收完成] 共回收 %d 个超时会话 | 剩余活跃会话数: %d",
            count,
            self._active_session_count(),
        )
        return count

    async def recover_orphans(self) -> int:
        """清理上一进程遗留的会话与启动请求。绝不抛异常。

        流程：
        1. 按启动令牌回收未认领的启动请求；
        2. 查询 live 会话，双重校验 session_id 与 agent_window_id 确认归属；
        3. 按精确 id 停止遗留会话并清理 journal。

        Returns:
            清理掉的遗留会话与请求总数。
        """
        journal = self._journal
        if journal is None:
            return 0

        self._logger.debug("[孤儿会话检查] 开始检查遗留孤儿会话...")
        try:
            recorded = journal.load()
        except Exception as exc:  # noqa: BLE001 - journal 自身已经吞异常，这里再兜一层
            self._logger.debug("读取会话 journal 失败（忽略）：%r", exc)
            return 0

        if not recorded:
            return 0

        # 按令牌回收未认领请求
        recorded, token_stopped = await self._recover_by_request(recorded)

        # 获取当前 live 会话列表
        try:
            live = await self._list_live_sessions()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("session list 失败，跳过孤儿会话恢复：%r", exc)
            live = None

        if live is None:
            self._journal_clear()
            return token_stopped

        # 逐条比对精确停止，跳过不属于本进程的会话
        stopped = token_stopped
        skipped = 0
        for entry in recorded:
            matches = live.get(entry.session_id)
            if matches is None or entry.agent_window_id not in matches:
                skipped += 1
                self._logger.debug(
                    "跳过遗留会话 %s（agent_window_id=%s）：daemon 侧不匹配",
                    entry.session_id,
                    entry.agent_window_id,
                )
                continue
            if await self._stop_session_id(entry.session_id):
                stopped += 1
                self._logger.debug(
                    "[孤儿会话清理] 清理遗留孤儿会话 %s (窗口ID=%s)",
                    entry.session_id,
                    entry.agent_window_id,
                )
            else:
                skipped += 1

        if stopped or skipped:
            self._logger.info(
                "恢复清理：停掉 %d 个上次遗留的浏览器会话，跳过 %d 个不匹配的",
                stopped,
                skipped,
            )
        self._journal_clear()
        self._logger.debug(
            "[孤儿清理完成] 共清理 %d 个遗留会话与请求 | 当前会话槽位: %d",
            stopped,
            len(self._entries),
        )
        return stopped

    async def _recover_by_request(
        self, recorded: list[JournalEntry]
    ) -> tuple[list[JournalEntry], int]:
        """按令牌回收上一进程遗留的启动请求。绝不抛异常。

        Returns:
            (剩余需按会话 id 检查的记录列表, 已成功取消的请求数)。
        """
        tokens = [e.request_id for e in recorded if e.request_id]
        if not tokens:
            return recorded, 0
        if not await self._request_protocol_supported():
            return recorded, 0

        remaining: list[JournalEntry] = []
        stopped = 0
        for entry in recorded:
            token = entry.request_id
            if not token:
                remaining.append(entry)
                continue
            state = await self._query_request(token)
            if state is None:
                remaining.append(entry)
                continue
            if state in LIVE_REQUEST_STATES:
                if await self._cancel_request(token):
                    self._journal_remove_by_request(token)
                    stopped += 1
                    self._counters["request_orphans_cancelled"] += 1
                    self._logger.debug("[孤儿请求清理] 回收遗留未认领请求 token=%s", token)
                else:
                    remaining.append(entry)
                continue
            if state in TERMINAL_REQUEST_STATES:
                self._journal_remove_by_request(token)
                continue
            remaining.append(entry)
        if stopped:
            self._logger.info("按启动令牌回收了 %d 个遗留的浏览器启动请求", stopped)
        return remaining, stopped

    async def _list_live_sessions(self) -> dict[str, set[int]]:
        """``bsk session list --json`` → ``{session_id: {agent_window_id, ...}}``。

        Raises:
            BskError: daemon 没在跑或命令失败。调用方会把"失败"当成
                "没有遗留会话"处理。
        """
        result = await self._cli.list_sessions(
            timeout=RECOVER_LIST_TIMEOUT_SEC, raise_on_error=True
        )
        raw = result.data
        mapping: dict[str, set[int]] = {}
        if not isinstance(raw, list):
            return mapping
        for item in raw:
            if not isinstance(item, dict):
                continue
            session_id = _as_str(item.get("session_id"))
            if not session_id:
                continue
            mapping.setdefault(session_id, set()).add(
                _as_int(item.get("agent_window_id"), 0)
            )
        return mapping

    def stats(self) -> dict:
        """给 ``/bskstatus`` 用的运行状态摘要（同步方法，随时可调）。"""
        now = self._clock()
        details: list[dict[str, Any]] = []
        for key, entry in self._entries.items():
            details.append(
                {
                    "key": key,
                    "session_id": entry.session.session_id or "(未建立)",
                    "browser_instance_id": entry.session.browser_instance_id,
                    "agent_window_id": entry.session.agent_window_id,
                    "busy": entry.lock.locked(),
                    "idle_sec": round(max(0.0, now - entry.last_used), 1),
                }
            )
        return {
            "closed": self._closed,
            "sessions": len(details),
            "max_sessions": self._max_sessions,
            "idle_release_sec": self._idle_release_sec,
            "default_timeout_sec": self._command_timeout,
            "details": details,
            "counters": dict(self._counters),
            "recent_stop_errors": list(self._recent_stop_errors),
        }

    def _active_session_count(self) -> int:
        """当前具有有效 session_id 的活跃会话数。"""
        return sum(1 for e in self._entries.values() if e.session.session_id)

    async def close(self) -> None:
        """释放所有会话并标记关闭。绝不抛异常。"""
        try:
            await self.release_all()
        except Exception as exc:  # noqa: BLE001 - 关闭路径绝不抛
            self._logger.warning("close() 释放会话时出现意外错误：%r", exc)
        finally:
            self._entries.clear()
            self._closed = True

    # ------------------------------------------------------------------
    # 内部：entry 生命周期
    # ------------------------------------------------------------------

    def _ensure_open(self) -> None:
        """管理器关闭后拒绝新建或执行操作。"""
        if self._closed:
            raise BskError(
                "会话管理器已关闭",
                friendly="浏览器插件正在关闭或已关闭，会话已全部释放。请稍后重试。",
                code="manager_closed",
            )

    @contextlib.asynccontextmanager
    async def _locked_entry(self, key: str):
        """获取指定 key 槽位并持有锁的异步上下文管理器。"""
        for _ in range(MAX_ENTRY_RETRIES):
            entry = await self._get_or_create_entry(key)
            await entry.lock.acquire()
            try:
                if self._entries.get(key) is entry and not entry.closed:
                    yield entry
                    return
                self._logger.debug("会话槽位 %s 在等待锁期间已被释放，重新获取", key)
            finally:
                entry.lock.release()
        raise BskError(
            f"会话槽位 {key} 反复被释放",
            friendly="浏览器会话正在被反复释放，请稍后重试。",
            code="session_churn",
        )

    async def _get_or_create_entry(self, key: str) -> _Entry:
        """获取或创建槽位。若不存在则预占位并按 LRU 检查容量。"""
        self._ensure_open()

        entry = self._entries.get(key)
        if entry is not None and not entry.closed:
            return entry

        # 先按 LRU 腾出容量
        await self._evict_for_capacity()

        async with self._registry_lock:
            entry = self._entries.get(key)
            if entry is not None and not entry.closed:
                return entry
            self._seq += 1
            entry = _Entry(
                key=key,
                session=BskSession(session_id=""),
                lock=asyncio.Lock(),
                last_used=self._clock(),
                seq=self._seq,
            )
            self._entries[key] = entry
            return entry

    async def _ensure_session(
        self, entry: _Entry, *, start_args: tuple[str, ...] = ()
    ) -> BskSession:
        """确保槽位里有一个可用的会话（占位 entry 在这里才真正 start）。

        Args:
            start_args: 仅在**这一步真的要新建会话**时生效，见
                :meth:`acquire`。已有会话时直接返回，参数被忽略。
        """
        if entry.session.is_valid():
            return entry.session
        return await self._start_into(entry, start_args=start_args)

    async def _start_into(
        self,
        entry: _Entry,
        *,
        is_rebuild: bool = False,
        start_args: tuple[str, ...] = (),
    ) -> BskSession:
        """新建一个 bsk 会话并原地写进槽位。

        进函数先把 id 清空：万一 ``start`` 失败，槽位必须如实报告"当前没有
        会话"，否则下次 ``execute`` 会拿着死 id 再撞一次 ``not_found``。

        Args:
            is_rebuild: 这是不是一次"会话失效后的重建"（只影响计数器）。
            start_args: 追加到 ``session start`` 后面的额外参数。只有
                :meth:`acquire` 那条路径会传；重建路径（:meth:`_restart`）
                刻意不传 —— 重建是为了恢复，不是为了改窗口尺寸。
        """
        previous_id = entry.session.session_id
        entry.session.session_id = ""

        # 可恢复启动流程：预写 journal 令牌 -> daemon prepare -> start --request-id -> claim
        # 若令牌写入失败则降级为普通启动，避免阻塞会话建立。
        token = ""
        if await self._request_protocol_supported():
            token = self._new_request_token()
            if not self._journal_add_pending(token):
                self._counters["request_write_ahead_failed"] += 1
                self._logger.warning(
                    "启动令牌写入 journal 失败，本次会话降级为普通启动：%s",
                    token,
                )
                token = ""
            else:
                try:
                    await self._prepare_request(token)
                except BaseException:
                    await self._cancel_request(token)
                    self._journal_remove_by_request(token)
                    raise

        try:
            fresh = await self._start(start_args=start_args, request_id=token)
        except BaseException:
            if token:
                self._counters["request_start_failed"] += 1
                if await self._cancel_request(token):
                    self._journal_remove_by_request(token)
            raise

        # 启动成功立即落盘记录会话所有权
        self._journal_add(
            fresh,
            request_id=token,
            state=(REQUEST_STATE_PREPARED if token else ""),
        )
        if previous_id and previous_id != fresh.session_id:
            self._journal_remove(previous_id)

        if token:
            try:
                await self._claim_request(token)
            except BaseException:
                self._counters["request_claim_failed"] += 1
                if await self._cancel_request(token):
                    self._journal_remove_by_request(token)
                raise
            self._journal_add(fresh, request_id=token, state=REQUEST_STATE_ACTIVE)

        if entry.closed:
            # 槽位在启动期间被释放，立即清理该新会话防止泄漏
            with contextlib.suppress(Exception):
                await self._stop_session_id(fresh.session_id)
            raise BskError(
                f"会话槽位 {entry.key} 在建立会话期间被释放",
                friendly="浏览器会话已被释放，请重新发起这次操作。",
                code="session_released",
            )

        _adopt(entry.session, fresh)
        entry.last_used = self._clock()
        self._counters["started"] += 1
        if is_rebuild:
            self._counters["rebuilt"] += 1
        return entry.session

    async def _restart(self, entry: _Entry, *, stop_old: bool) -> BskSession:
        """丢弃旧会话并重建。

        Args:
            stop_old: 是否显式 stop 旧会话（not_found 触发时传 False）。
        """
        if stop_old and entry.session.is_valid():
            await self._stop_entry(entry)
        return await self._start_into(entry, is_rebuild=True)

    async def _start(
        self, *, start_args: Sequence[str] = (), request_id: str = ""
    ) -> BskSession:
        """执行 ``session start`` 并解析会话。

        Args:
            start_args: 启动额外参数（如窗口尺寸）。
            request_id: 可恢复启动令牌。

        Raises:
            BskError: 启动失败或协议数据异常。
            BskStartCancelled: 启动已被取消。
        """
        browser_id = await self._resolve_browser_instance()
        try:
            result = await self._cli.start_session(
                browser_id=browser_id,
                request_id=request_id,
                focus=False,
                extra_args=start_args,
                timeout=self._start_timeout,
                raise_on_error=True,
            )
        except BskError as exc:
            if is_cancelled_error(exc):
                self._counters["request_cancelled"] += 1
                raise _cancelled_from(exc) from exc
            raise
        session = BskSession.from_json(result.data)
        if not session.is_valid():
            raise BskProtocolError(
                f"session start 未返回 session_id：{(result.stdout or '')[:200]}",
                friendly="无法创建浏览器会话（bsk 返回的数据不完整），请稍后重试。",
                code="bad_session_payload",
                exit_code=result.exit_code,
            )
        self._logger.info(
            "已创建浏览器会话 %s（browser=%s）",
            session.session_id,
            session.browser_instance_id or browser_id or "默认",
        )
        self._logger.debug(
            "[会话启动] 会话 %s 建立完成 | 浏览器: %s, 窗口ID: %s | 当前活跃会话数: %d/%d",
            session.session_id,
            session.browser_instance_id or browser_id or "默认",
            session.agent_window_id,
            self._active_session_count() + 1,
            self._max_sessions,
        )
        return session

    # ------------------------------------------------------------------
    # 内部：可恢复启动（request_id 协议）
    # ------------------------------------------------------------------

    def _new_request_token(self) -> str:
        """生成可恢复启动令牌：``<到期-unix-毫秒>:<UUID>``。"""
        ttl = min(
            REQUEST_TOKEN_TTL_MAX_SEC,
            max(REQUEST_TOKEN_TTL_SEC, 2 * self._start_timeout + REQUEST_TOKEN_TTL_MARGIN_SEC),
        )
        return f"{int((time.time() + ttl) * 1000)}:{uuid.uuid4()}"

    async def _request_protocol_supported(self) -> bool:
        """探测当前 bsk 是否支持可恢复启动协议。每进程仅探测一次并缓存结果。"""
        if not self._enable_request_id:
            self._counters["request_protocol_disabled"] += 1
            self._logger.info(
                "配置里关闭了可恢复启动（enable_request_id=false），"
                "会话将按旧方式建立（不带启动令牌）"
            )
            return False
        if self._request_protocol is None:
            self._request_protocol = await self._probe_request_protocol()
            if self._request_protocol:
                self._logger.debug("bsk 支持可恢复启动（session request --prepare 可用）")
            else:
                self._counters["request_protocol_unsupported"] += 1
                self._logger.warning(
                    "当前 bsk 不支持可恢复启动（session request 子命令不可用），"
                    "本次运行退回旧行为：浏览器会话照常建立，但启动回执丢失时"
                    "无法凭令牌找回窗口。把 bsk 升级到最新版即可恢复这层保护。"
                )
        return self._request_protocol

    async def _probe_request_protocol(self) -> bool:
        """探测 bsk 是否支持 session request。失败返回 False，绝不抛异常。"""
        try:
            result = await self._cli.request_probe(timeout=REQUEST_PROBE_TIMEOUT_SEC)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("bsk 不支持 session request（能力探测失败）：%r", exc)
            return False
        return "--prepare" in (result.stdout or "")

    async def _request_command(
        self, args: list[str], *, request_id: str
    ) -> dict[str, Any]:
        """执行 ``session request`` 命令并解析 JSON。失败抛 BskError。"""
        try:
            result = await self._cli.request_command(
                args, timeout=REQUEST_PROTOCOL_TIMEOUT_SEC, raise_on_error=True
            )
        except BskSessionGone as exc:
            raise BskError(
                f"启动令牌不存在或已过期：{request_id}（{exc}）",
                friendly=(
                    "这次可恢复启动的令牌在后台服务里查不到（可能已过期或已被清理）。"
                    "请重新发起一次浏览器操作。"
                ),
                code="request_not_found",
                exit_code=getattr(exc, "exit_code", -1),
                reason=getattr(exc, "reason", ""),
            ) from exc
        except BskError as exc:
            if is_cancelled_error(exc):
                raise _cancelled_from(exc) from exc
            raise
        data = result.data
        if not isinstance(data, dict):
            raise BskProtocolError(
                f"session request 未返回 JSON 对象：{(result.stdout or '')[:200]}",
                friendly=(
                    "bsk 命令行与后台服务版本不匹配，无法使用可恢复启动。"
                    "请把 bsk 与本插件都升级到最新版。"
                ),
                code="request_bad_payload",
                exit_code=result.exit_code,
            )
        return data

    async def _prepare_request(self, request_id: str) -> None:
        """预约启动令牌（``session request <令牌> --prepare``）。"""
        self._logger.debug(
            "[会话准备] 准备启动请求 token=%s | 当前活跃会话数: %d, 槽位数: %d",
            request_id,
            self._active_session_count(),
            len(self._entries),
        )
        data = await self._request_command(
            ["session", "request", request_id, "--prepare", "--json"],
            request_id=request_id,
        )
        state = _as_str(data.get("state"))
        if state != REQUEST_STATE_PREPARED:
            raise BskError(
                f"session request --prepare 返回了意外的状态：{state or '(空)'}",
                friendly=(
                    "bsk 命令行与后台服务版本不匹配，无法准备可恢复启动。"
                    "请把 bsk 与本插件都升级到最新版。"
                ),
                code="request_prepare_failed",
            )

    async def _claim_request(self, request_id: str) -> None:
        """认领启动令牌（``session request <令牌> --claim``）。"""
        self._logger.debug(
            "[会话认领] 认领启动请求 token=%s",
            request_id,
        )
        data = await self._request_command(
            ["session", "request", request_id, "--claim", "--json"],
            request_id=request_id,
        )
        state = _as_str(data.get("state"))
        if state != REQUEST_STATE_ACTIVE:
            raise BskError(
                f"session request --claim 返回了意外的状态：{state or '(空)'}",
                friendly=(
                    "bsk 命令行与后台服务版本不匹配，无法确认这次浏览器启动的所有权。"
                    "请把 bsk 与本插件都升级到最新版。"
                ),
                code="request_claim_failed",
            )

    async def _cancel_request(self, request_id: str) -> bool:
        """取消启动令牌并关闭关联窗口（``session request <令牌> --cancel``）。绝不抛异常。

        Returns:
            True 表示已确认关闭；False 表示未确认。
        """
        if not request_id:
            return False
        self._logger.debug("[会话取消] 取消未认领启动请求 token=%s", request_id)
        try:
            data = await self._request_command(
                ["session", "request", request_id, "--cancel", "--json"],
                request_id=request_id,
            )
        except BaseException as exc:  # noqa: BLE001 - 含 CancelledError
            self._logger.warning(
                "取消启动请求 %s 失败，保留 journal 记录待下次启动重试：%r",
                request_id,
                exc,
            )
            return False
        state = _as_str(data.get("state"))
        cleanup_error = data.get("cleanup_error")
        if state == REQUEST_STATE_CLOSED and not cleanup_error:
            self._logger.debug("启动请求 %s 已取消（确认窗口不在）", request_id)
            return True
        self._logger.warning(
            "启动请求 %s 未确认已关闭（state=%s, cleanup_error=%r），"
            "保留 journal 记录待下次启动重试",
            request_id,
            state or "(空)",
            cleanup_error,
        )
        return False

    async def _query_request(self, request_id: str) -> str | None:
        """查询启动令牌状态。问不到或出错返回 None。"""
        if not request_id:
            return None
        try:
            data = await self._request_command(
                ["session", "request", request_id, "--json"], request_id=request_id
            )
        except Exception as exc:  # noqa: BLE001 - 启动路径上跑的，不该吞取消
            self._logger.debug("查询启动请求 %s 状态失败：%r", request_id, exc)
            return None
        state = _as_str(data.get("state"))
        return state or None

    async def _resolve_browser_instance(self) -> str:
        """决定 ``session start`` 要指定哪个浏览器。

        优先用配置里的 ``browser_instance_id``；没配就用 ``browser_probe``
        探一个；探测失败返回空串（不传 ``--browser``，让 bsk 自己选默认）。

        唯一的例外是 :class:`BskBrowserAmbiguous`：它表示"探测成功了，但
        同时连着多个浏览器，无法确定用哪一个"——这是用户配置问题，
        不是探测失败。它必须原样抛出去让用户看到，否则会被下面的
        ``except Exception`` 吞掉，退化成"不传 --browser，让 bsk 随便选一个"
        （正是本次要修掉的静默随机行为）。注意用户的显式配置在上面的
        ``if`` 里已经直接返回，所以"配了就必须尊重配置"不受此影响。
        """
        if self._browser_instance_id:
            return self._browser_instance_id
        if self._browser_probe is None:
            return ""
        try:
            probed = self._browser_probe()
            if inspect.isawaitable(probed):
                probed = await probed
            return _coerce_probe_result(probed)
        except BskBrowserAmbiguous:
            raise
        except Exception as exc:  # noqa: BLE001 - 探测失败只是回退，不是错误
            self._logger.debug("browser_probe 探测失败，回退到 bsk 默认浏览器：%r", exc)
            return ""

    async def _stop_entry(self, entry: _Entry) -> bool:
        """停掉一个槽位里的会话。绝不抛异常。

        Returns:
            True 表示 bsk 侧确认该会话已不存在（stop 成功，或本来就没了）。
        """
        if not entry.session.session_id:
            return True  # 只有占位槽位，没有真实会话可停。

        # 在停止会话前，清理 Agent Window 中所有的标签页，避免触发 dropOnly 导致窗口留在宿主机
        try:
            res = await self._cli.list_tabs(
                session=entry.session.session_id, scope="agent", timeout=5.0
            )
            raw = res.data
            tab_list = (
                raw.get("tabs", [])
                if isinstance(raw, dict)
                else (raw if isinstance(raw, list) else [])
            )
            if isinstance(tab_list, list) and tab_list:
                for t in tab_list:
                    if isinstance(t, dict):
                        tid = t.get("tab_id", t.get("id"))
                        if tid is not None:
                            try:
                                await self.close_tab_safe(
                                    entry.session.session_id, tid, timeout=5.0, raise_on_error=False
                                )
                            except Exception as exc:  # noqa: BLE001
                                self._logger.debug("安全关闭标签页 %s 失败（忽略）：%r", tid, exc)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("获取 Agent 标签页列表以清理失败（忽略）：%r", exc)

        return await self._stop_session_id(entry.session.session_id)

    async def _stop_session_id(self, session_id: str) -> bool:
        """按精确 id 停止会话，对瞬时故障执行有界重试。绝不抛异常。

        核心机制：
        1. 仅按精确 session_id 停止，绝不使用 session stop --all；
        2. 幂等处理：若返回 not_found 视为已成功停止；
        3. 有界重试：总耗时由 STOP_TOTAL_BUDGET_SEC 约束，避免阻塞 terminate 流程；
        4. 成功后清理 journal 记录，重试耗尽失败时保留记录供下次启动恢复。

        Args:
            session_id: bsk 会话 id。空串直接返回 True。

        Returns:
            True 表示会话已确认不存在（停止成功或原本不存在）；False 表示停止失败。
        """
        if not session_id:
            return True

        args = ["session", "stop", session_id]
        deadline = time.monotonic() + self._stop_total_budget_sec
        last_exc: BaseException | None = None
        attempt = 0

        for attempt in range(1, self._stop_max_attempts + 1):
            remaining = max(0.0, deadline - time.monotonic())
            budget_for_timeout = remaining - self._stop_attempt_overhead_sec
            attempt_timeout = min(self._stop_timeout_sec, max(0.0, budget_for_timeout))

            min_worthwhile = min(
                STOP_RETRY_MIN_TIMEOUT_SEC, self._stop_timeout_sec
            )
            if attempt > 1 and attempt_timeout < min_worthwhile:
                self._counters["stop_retry_budget_skips"] += 1
                self._logger.warning(
                    "停止会话 %s 剩余预算 %.2fs 不足以重试，放弃",
                    session_id,
                    remaining,
                )
                break
            if attempt == 1 and attempt_timeout < min_worthwhile:
                attempt_timeout = min(remaining, min_worthwhile)
            if attempt > 1:
                self._counters["stop_retries"] += 1

            backstop = min(
                self._stop_attempt_backstop_sec,
                remaining,
                attempt_timeout
                + self._stop_attempt_overhead_sec
                + STOP_ATTEMPT_BACKSTOP_MARGIN_SEC,
            )
            backstop = max(backstop, attempt_timeout)
            try:
                await self._stop_once(args, session_id, attempt_timeout, backstop)
            except BskSessionGone:
                self._counters["stopped"] += 1
                self._journal_remove(session_id)
                if attempt > 1:
                    self._counters["stop_recovered"] += 1
                    self._logger.info(
                        "会话 %s 在第 %d 次尝试时确认已停止", session_id, attempt
                    )
                else:
                    self._logger.debug("会话 %s 已不存在，无需停止", session_id)
                self._logger.debug(
                    "[会话关闭] 会话 %s 已确认不存在 | 剩余活跃会话数: %d",
                    session_id,
                    self._active_session_count(),
                )
                return True
            except Exception as exc:  # noqa: BLE001 - 清理路径吞掉一切
                last_exc = exc
                remaining = deadline - time.monotonic()

                if attempt >= self._stop_max_attempts:
                    break
                if not _is_transient_stop_error(exc):
                    self._logger.debug(
                        "停止会话 %s 失败且不属于瞬时故障，不再重试：%r",
                        session_id,
                        exc,
                    )
                    break
                self._logger.warning(
                    "停止会话 %s 第 %d 次失败（瞬时故障），%.2fs 后重试：%r",
                    session_id,
                    attempt,
                    self._stop_retry_delay_sec,
                    exc,
                )
                await asyncio.sleep(
                    min(self._stop_retry_delay_sec, max(0.0, remaining))
                )
                continue
            else:
                self._counters["stopped"] += 1
                self._journal_remove(session_id)
                if attempt > 1:
                    self._counters["stop_recovered"] += 1
                    self._logger.info(
                        "会话 %s 在第 %d 次尝试时停止成功（瞬时故障已恢复）",
                        session_id,
                        attempt,
                    )
                else:
                    self._logger.info("已停止浏览器会话 %s", session_id)
                self._logger.debug(
                    "[会话关闭] 关闭会话 %s 完成 | 剩余活跃会话数: %d",
                    session_id,
                    self._active_session_count(),
                )
                return True

        self._counters["stop_failed"] += 1
        self._record_stop_error(f"{session_id}: {last_exc}")
        self._logger.warning(
            "停止会话 %s 失败（共尝试 %d 次，上限 %d）：%r",
            session_id,
            attempt,
            self._stop_max_attempts,
            last_exc,
        )
        # 刻意不删 journal 记录：这次没停掉，会话可能还活着，
        # 留着记录能让下一次启动的 recover_orphans 再试一次。
        return False

    async def _stop_once(
        self, args: list[str], session_id: str, attempt_timeout: float, backstop: float
    ) -> None:
        """执行一次 ``session stop`` 命令。

        Args:
            args: 命令参数列表。
            session_id: 会话 ID。
            attempt_timeout: 本次执行超时。
            backstop: 硬性超时兜底。

        Raises:
            BskError: 命令执行失败。
            BskTimeout: 超出兜底时间未返回。
        """
        try:
            await asyncio.wait_for(
                self._cli.stop_session(
                    session_id, timeout=attempt_timeout, raise_on_error=True
                ),
                timeout=backstop,
            )
        except asyncio.TimeoutError as exc:
            raise BskTimeout(
                f"session stop {session_id} 超过 {backstop:.1f}s 未返回"
                "（runner 未遵守自身超时约定）",
                friendly="关闭浏览器会话超时了，稍后会自动重试。",
                code="stop_backstop_timeout",
                exit_code=EXIT_TIMEOUT,
            ) from exc

    async def _shutdown_entries(self, entries: list[_Entry]) -> int:
        """并发停掉一批会话，返回成功数量。任何失败都不会传播。"""
        results = await asyncio.gather(
            *(self._shutdown_one(entry) for entry in entries),
            return_exceptions=True,
        )
        return sum(1 for r in results if r is True)

    async def _shutdown_one(self, entry: _Entry) -> bool:
        """等待进行中的命令结束并停止会话。绝不抛异常。"""
        try:
            await self._wait_idle(entry, RELEASE_WAIT_SEC)
            return await self._stop_entry(entry)
        except Exception as exc:  # noqa: BLE001 - 清理路径吞掉一切
            self._logger.warning("关闭会话槽位 %s 时出现意外错误：%r", entry.key, exc)
            self._record_stop_error(f"{entry.key}: {exc!r}")
            return False

    async def _evict_for_capacity(self) -> int:
        """按 LRU 淘汰超出容量上限的会话，返回淘汰数量。"""
        evicted = 0
        while self._entries and len(self._entries) >= self._max_sessions:
            victim_key, victim = self._pick_lru()
            popped = self._entries.pop(victim_key, None)
            if popped is None:
                break
            popped.closed = True
            await self._wait_idle(popped, RELEASE_WAIT_SEC)
            await self._stop_entry(popped)
            evicted += 1
            self._counters["evicted"] += 1
            self._logger.info(
                "会话数已达上限 %d，淘汰最久未使用的会话 %s（key=%s）",
                self._max_sessions,
                popped.session.session_id or "(未建立)",
                victim_key,
            )
            self._logger.debug(
                "[会话容量淘汰] 会话池已满 (%d/%d)，按 LRU 淘汰会话 %s (key=%s, 空闲 %.1fs)",
                len(self._entries) + 1,
                self._max_sessions,
                popped.session.session_id or "(未建立)",
                victim_key,
                self._clock() - popped.last_used,
            )
            del victim
        return evicted

    def _pick_lru(self) -> tuple[str, _Entry]:
        """挑出最久未使用的槽位。相同时间按创建序号排序。"""
        return min(
            self._entries.items(),
            key=lambda kv: (kv[1].last_used, kv[1].seq),
        )

    async def _wait_idle(self, entry: _Entry, timeout: float) -> bool:
        """等待正在执行的命令结束（最多 timeout 秒）。"""
        if not entry.lock.locked():
            return True
        deadline = time.monotonic() + max(0.0, timeout)
        while entry.lock.locked() and time.monotonic() < deadline:
            await asyncio.sleep(RELEASE_POLL_STEP_SEC)
        if entry.lock.locked():
            self._logger.warning("等待会话 %s 空闲超过 %.1fs，仍继续停止", entry.key, timeout)
            return False
        return True

    # ------------------------------------------------------------------
    # 内部：小工具
    # ------------------------------------------------------------------

    def _touch(self, entry: _Entry) -> None:
        """刷新活跃时间戳。"""
        entry.last_used = self._clock()

    async def _build_args(self, builder: ArgsBuilder, session_id: str) -> list[str]:
        """用当前 session_id 构造参数列表（支持同步/异步 builder）。"""
        produced = builder(session_id)
        if inspect.isawaitable(produced):
            produced = await produced
        if isinstance(produced, tuple):
            produced = list(produced)
        if not isinstance(produced, list):
            raise BskProtocolError(
                f"args_builder 必须返回参数列表，实际返回 {type(produced).__name__}",
                friendly="插件内部错误：命令参数构造失败，请反馈。",
                code="bad_args_builder",
            )
        return [str(item) for item in produced]

    def _record_stop_error(self, detail: str) -> None:
        """记录 stop 失败原因（保留最近 5 条供 /bskstatus 排查）。"""
        self._recent_stop_errors.append(detail)
        del self._recent_stop_errors[:-5]

    # ------------------------------------------------------------------
    # 内部：journal（尽力而为，异常仅记录 debug 日志）
    # ------------------------------------------------------------------

    def _journal_add(
        self, session: BskSession, *, request_id: str = "", state: str = ""
    ) -> None:
        """将会话所有权记录写入 journal。"""
        if self._journal is None or not session.session_id:
            return
        try:
            self._journal.add(
                JournalEntry(
                    session_id=session.session_id,
                    browser_instance_id=session.browser_instance_id,
                    agent_window_id=session.agent_window_id,
                    created_at=now_seconds(),
                    pid=os.getpid(),
                    request_id=request_id,
                    state=state,
                )
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("写会话 journal 失败（忽略）：%r", exc)

    def _journal_add_pending(self, request_id: str) -> bool:
        """在创建会话前将启动令牌预写进 journal。"""
        if not REQUEST_TOKEN_RE.match(request_id or ""):
            self._logger.warning(
                "拒绝把格式非法的启动令牌写进 journal：%r",
                request_id,
            )
            return False
        if self._journal is None:
            return True
        try:
            ok = bool(
                self._journal.add_checked(
                    JournalEntry(
                        session_id="",
                        browser_instance_id="",
                        agent_window_id=0,
                        created_at=now_seconds(),
                        pid=os.getpid(),
                        request_id=request_id,
                        state=REQUEST_STATE_PREPARED,
                    )
                )
            )
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("写启动令牌到 journal 失败：%r", exc)
            return False
        if not ok:
            self._logger.debug("journal.add_checked 报告写入失败：%s", request_id)
        return ok

    def _journal_remove_by_request(self, request_id: str) -> None:
        """按启动令牌从 journal 移除记录。"""
        if self._journal is None or not request_id:
            return
        try:
            self._journal.remove_by_request(request_id)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("按令牌清理 journal 记录失败（忽略）：%r", exc)

    def _journal_remove(self, session_id: str) -> None:
        """按会话 ID 从 journal 移除记录。"""
        if self._journal is None or not session_id:
            return
        try:
            self._journal.remove(session_id)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("清理会话 journal 记录失败（忽略）：%r", exc)

    def _journal_clear(self) -> None:
        """清空 journal。"""
        if self._journal is None:
            return
        try:
            self._journal.clear()
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("清空会话 journal 失败（忽略）：%r", exc)
