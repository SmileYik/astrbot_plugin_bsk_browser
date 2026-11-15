"""bsk 层的日志接口 —— 依赖注入的接缝。

本包有两条必须同时成立的约束，它们把"日志怎么写"这件事夹到了唯一一条路上：

1. 插件市场审核要求 logger 必须来自 ``astrbot.api``，不得使用 Python 内置的
   日志模块；
2. 本包不得依赖 AstrBot（有静态测试守着），否则就没法脱离框架独立单测。

两者同时满足的办法只有一个：本模块只声明"日志该长什么样"，真正的 logger 由
``main.py``（唯一允许依赖框架的文件）取来后通过构造参数注入。没注入时
（单测、脚本、以及解析失败后的降级）一律退回 :data:`NULL_LOGGER`。

调用约定与标准库 logger 一致 —— **惰性 %-格式化**，格式串与参数分开传::

    self._logger.info("会话 %s 已重建为 %s", key, new_id)

本包既有的全部调用点都是这个形态，所以接口必须保持这个签名，不能改成
f-string：那样在日志级别被关掉时白白做一次字符串拼接与格式化。
"""

from __future__ import annotations

import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "FileLogger",
    "NULL_LOGGER",
    "LoggerLike",
    "NullLogger",
    "TeeLogger",
    "create_safe_file_logger",
    "truncate_log_text",
]


def truncate_log_text(text: Any, max_len: int) -> str:
    """按字符上限截断日志文本。

    Args:
        text: 待截断的内容（非字符串安全转为 str，None 转为空串）。
        max_len: 字符上限；<= 0 表示不截断。

    Returns:
        安全截断后的字符串，若截断则附带 '... [已截断，共 N 字符]' 后缀。
    """
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    if max_len <= 0 or len(s) <= max_len:
        return s
    return f"{s[:max_len]}... [已截断，共 {len(s)} 字符]"



@runtime_checkable
class LoggerLike(Protocol):
    """``bsk/`` 各组件接受的日志接口（结构类型，不要求继承）。

    刻意用 :class:`~typing.Protocol` 而不是抽象基类：要注入进来的是
    ``astrbot.api.logger``、标准库的 logger、以及测试里的记录型假对象，
    它们都不该为了被本包接受而去改继承关系。方法齐全即算满足。

    方法签名里的 ``*args`` 是必须的 —— 它承载的就是上一条说的惰性
    %-格式化参数（``logger.info("...%s", x)``）。``exception`` 也必须存在：
    ``main.py`` 在几个工具的兜底分支上用它，而且它靠的是"记录当前异常"
    这个语义（调用点不传 ``exc_info``）。

    ``runtime_checkable`` 让"注入的东西像不像 logger"能在测试里直接用
    ``isinstance`` 断言（只看方法名，不看签名）。
    """

    def debug(self, msg: object, *args: Any, **kwargs: Any) -> None: ...

    def info(self, msg: object, *args: Any, **kwargs: Any) -> None: ...

    def warning(self, msg: object, *args: Any, **kwargs: Any) -> None: ...

    def error(self, msg: object, *args: Any, **kwargs: Any) -> None: ...

    def exception(self, msg: object, *args: Any, **kwargs: Any) -> None: ...


class NullLogger:
    """兜底 logger：什么都不做，也永不抛异常。

    为什么不干脆让调用点写 ``if self._logger is not None``：那种判断要重复
    几十次，漏掉一处就是一个 ``AttributeError`` —— 而它偏偏会出现在最不该
    出问题的降级路径上（journal 读写失败、截图清理失败、探测失败……）。
    有了本类，调用点可以无条件地写 ``self._logger.debug(...)``。

    所有参数一律接受、一律忽略：参数个数与类型完全由调用点决定，兜底实现
    若对它们做任何检查（例如只认字符串），就会在"绝不添乱"这件事上反过来
    添乱。这也是它必须显式实现全部五个级别、而不是靠 ``__getattr__`` 兜住
    的原因 —— 显式的方法能撑住 :class:`LoggerLike` 的结构检查。
    """

    __slots__ = ()

    def debug(self, msg: object, *args: Any, **kwargs: Any) -> None:
        """忽略一条 debug 日志。"""

    def info(self, msg: object, *args: Any, **kwargs: Any) -> None:
        """忽略一条 info 日志。"""

    def warning(self, msg: object, *args: Any, **kwargs: Any) -> None:
        """忽略一条 warning 日志。"""

    def error(self, msg: object, *args: Any, **kwargs: Any) -> None:
        """忽略一条 error 日志。"""

    def exception(self, msg: object, *args: Any, **kwargs: Any) -> None:
        """忽略一条 exception 日志。"""


NULL_LOGGER = NullLogger()
"""全局共用的兜底实例（无状态，可以安全共享）。"""


class FileLogger:
    """基于纯标准库实现的线程安全文件日志记录器。

    满足 :class:`LoggerLike` 协议，采用惰性 %-格式化输出，附带毫秒时间戳与级别前缀。
    写文件遇到任何异常（磁盘满、权限吊销）自动禁用并安全静默，绝不向外抛异常。
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).resolve()
        self._lock = threading.Lock()
        self._disabled = False
        self._file: Any | None = None
        try:
            self._file = open(self.path, "a", encoding="utf-8")
        except Exception:
            self._disabled = True

    def _write(self, level: str, msg: object, *args: Any, **kwargs: Any) -> None:
        if self._disabled or self._file is None:
            return
        try:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            if args:
                try:
                    text = str(msg) % args
                except Exception:
                    text = f"{msg} {' '.join(str(a) for a in args)}"
            else:
                text = str(msg)

            exc_text = ""
            if kwargs.get("exc_info") or level == "ERROR":
                tb = traceback.format_exc()
                if tb and tb.strip() != "NoneType: None":
                    exc_text = f"\n{tb.rstrip()}"

            line = f"{now_str} [{level}] {text}{exc_text}\n"

            with self._lock:
                if self._file is not None and not self._disabled:
                    self._file.write(line)
                    self._file.flush()
        except Exception:
            self._disabled = True
            try:
                if self._file is not None:
                    self._file.close()
            except Exception:
                pass
            self._file = None

    def debug(self, msg: object, *args: Any, **kwargs: Any) -> None:
        self._write("DEBUG", msg, *args, **kwargs)

    def info(self, msg: object, *args: Any, **kwargs: Any) -> None:
        self._write("INFO", msg, *args, **kwargs)

    def warning(self, msg: object, *args: Any, **kwargs: Any) -> None:
        self._write("WARNING", msg, *args, **kwargs)

    def error(self, msg: object, *args: Any, **kwargs: Any) -> None:
        self._write("ERROR", msg, *args, **kwargs)

    def exception(self, msg: object, *args: Any, **kwargs: Any) -> None:
        kwargs_with_exc = dict(kwargs)
        kwargs_with_exc["exc_info"] = True
        self._write("ERROR", msg, *args, **kwargs_with_exc)

    def close(self) -> None:
        """关闭文件句柄。"""
        with self._lock:
            if self._file is not None:
                try:
                    self._file.flush()
                    self._file.close()
                except Exception:
                    pass
                self._file = None


class TeeLogger:
    """将一条日志同时分发给多个 logger 的组合器。

    满足 :class:`LoggerLike` 协议。主 logger（首个）始终优先调用；
    后续副 logger 的异常自动吞掉，保证主通道绝不被破坏。
    """

    def __init__(self, *loggers: LoggerLike) -> None:
        self._loggers = tuple(l for l in loggers if l is not None)

    def debug(self, msg: object, *args: Any, **kwargs: Any) -> None:
        for i, l in enumerate(self._loggers):
            try:
                l.debug(msg, *args, **kwargs)
            except Exception:
                if i == 0:
                    raise

    def info(self, msg: object, *args: Any, **kwargs: Any) -> None:
        for i, l in enumerate(self._loggers):
            try:
                l.info(msg, *args, **kwargs)
            except Exception:
                if i == 0:
                    raise

    def warning(self, msg: object, *args: Any, **kwargs: Any) -> None:
        for i, l in enumerate(self._loggers):
            try:
                l.warning(msg, *args, **kwargs)
            except Exception:
                if i == 0:
                    raise

    def error(self, msg: object, *args: Any, **kwargs: Any) -> None:
        for i, l in enumerate(self._loggers):
            try:
                l.error(msg, *args, **kwargs)
            except Exception:
                if i == 0:
                    raise

    def exception(self, msg: object, *args: Any, **kwargs: Any) -> None:
        for i, l in enumerate(self._loggers):
            try:
                l.exception(msg, *args, **kwargs)
            except Exception:
                if i == 0:
                    raise

    def close(self) -> None:
        """安全关闭所有支持 close 的下游 logger。"""
        for l in self._loggers:
            close_fn = getattr(l, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:
                    pass


def create_safe_file_logger(path_str: str) -> FileLogger | None:
    """安全探测并创建日志文件记录器。

    Args:
        path_str: 用户填入的文件路径字符串。

    Returns:
        若路径为空、是已有目录或无写权限，返回 None；否则返回初始化的 FileLogger。
    """
    if not path_str or not isinstance(path_str, str) or not path_str.strip():
        return None
    try:
        p = Path(path_str.strip()).expanduser().resolve()
        if p.exists() and p.is_dir():
            return None
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as probe:
            probe.write("")
        return FileLogger(p)
    except Exception:
        return None
