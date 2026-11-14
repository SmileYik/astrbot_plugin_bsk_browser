# DEBUG 日志系统 (bsk-debug-logging-system) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `astrbot_plugin_bsk_browser` 构建完整的 DEBUG 调试日志系统，无遗漏地成对记录 16 个工具的调用（含平台会话与耗时）以及底层 `bsk` CLI 指令执行（含参数、耗时、退出码与标准输出/错误），并支持可配置的字符截断保护。

**Architecture:** 
1. 在 `bsk/logger.py` 中实现安全的文本截断辅助函数 `truncate_log_text`，并在 `_conf_schema.json` 和 `bsk/config.py` 中引入 `log_max_output_length` 配置。
2. 在 `bsk/runner.py` 的执行收敛点 `BskRunner.run` 注入 `LoggerLike`，记录底层子进程命令的起止、退出码、耗时与截断输出；在 `BskService` 中统一注入。
3. 在 `main.py` 中实现支持普通异步函数与异步生成器（`bsk_screenshot`）的统一切面装饰器 `@_trace_tool_call`，修饰全部 16 个工具，记录调用起止、平台会话 `umo`、发送者、内部会话 key、耗时与截断出参。

**Tech Stack:** Python 3.10+, AstrBot Star Plugin API (`astrbot.api.logger`), asyncio subprocess, unittest.

**Spec:** [docs/superpowers/specs/2026-11-15-bsk-debug-logging-system-design.md](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-bsk-debug-logging-system-design.md)

## Global Constraints

- 所有 AstrBot 面向框架的 logger 必须通过 `from astrbot.api import logger` 引用。
- `bsk/` 子包内严禁直接 `import astrbot`，严禁使用 Python 内置 `logging` 模块；内部组件通过 `bsk/logger.py` 的 `LoggerLike` 结构类型协议进行依赖注入。
- 所有日志必须以 `DEBUG` 级别输出，严禁擅自提升为 INFO 或 WARNING。
- 绝不漏记任何一次工具调用或 bsk 子进程执行，即使用户被权限拒绝、参数校验失败或执行异常，也必须成对输出「开始」与「结束」日志。
- 日志格式化与参数转换绝不能抛出未捕获异常影响主业务执行。
- 工具切面必须保留被修饰函数的 `__name__`、`__doc__` 和参数签名（通过 `@functools.wraps`），确保框架 schema 解析与 `self` 绑定正常。

## Review Focus

1. **大文本/二进制截断保护**：当工具返回几十万字符的 HTML 源码或 bsk 输出大文件时，`truncate_log_text` 必须在限定长度内截断并附加省略后缀，且 `max_len <= 0` 时保留全量。
2. **异步生成器迭代生命周期**：`bsk_screenshot` 是 `async def` 返回 `AsyncGenerator`，切面在中间各个 `yield` 时正常透传消息，并在迭代结束或异常中断后在 `finally` 阶段准确输出结束日志与总耗时。
3. **权限拦截与早期返回**：非管理员或白名单拦截时直接 `return self._fail(denied)`，切面仍必须准确输出「开始」与「结束」两条日志。
4. **子进程启动失败/超时记录**：bsk 可执行文件不存在、无执行权限或超时取消时，`BskRunner.run` 必须准确记录「执行命令失败」或超时完成日志，耗时不丢失。
5. **分层合规性**：`verify_compliance.py` 与 `test_logger_injection.py` 严格校验 `bsk/` 源码树内 0 `import astrbot` 和 0 `import logging`。

---

### Task 1: 配置项扩展与日志截断工具函数

**Files:**
- Modify: `_conf_schema.json`
- Modify: `bsk/config.py`
- Modify: `bsk/logger.py`
- Create: `tests/test_logger_truncation.py`
- Modify: `tests/test_config.py`

**Interfaces:**
- Consumes: `Settings`, `bsk/config.py:parse_settings`, `bsk/config.py:validate_settings`
- Produces: 
  - `truncate_log_text(text: Any, max_len: int) -> str`
  - `Settings.log_max_output_length: int` (default 2048)

- [ ] **Step 1: 编写截断函数与配置解析的失败测试**

在 `tests/test_logger_truncation.py` 中编写单测：
```python
import unittest
from bsk.logger import truncate_log_text

class TestLoggerTruncation(unittest.TestCase):
    def test_truncate_within_limit(self):
        self.assertEqual(truncate_log_text("hello", 10), "hello")

    def test_truncate_exceeds_limit(self):
        result = truncate_log_text("abcdefghij", 5)
        self.assertEqual(result, "abcde... [已截断，共 10 字符]")

    def test_truncate_disabled_when_zero_or_negative(self):
        self.assertEqual(truncate_log_text("abcdefghij", 0), "abcdefghij")
        self.assertEqual(truncate_log_text("abcdefghij", -1), "abcdefghij")

    def test_truncate_non_str_safe(self):
        self.assertEqual(truncate_log_text(12345, 3), "123... [已截断，共 5 字符]")
        self.assertEqual(truncate_log_text(None, 5), "")
```

并在 `tests/test_config.py` 中增加对 `log_max_output_length` 默认值与解析的测试：
```python
def test_log_max_output_length_default_and_custom(self):
    settings = parse_settings({})
    self.assertEqual(settings.log_max_output_length, 2048)
    custom = parse_settings({"log_max_output_length": 500})
    self.assertEqual(custom.log_max_output_length, 500)
    disabled = parse_settings({"log_max_output_length": 0})
    self.assertEqual(disabled.log_max_output_length, 0)
```

- [ ] **Step 2: 运行测试以确认失败**

运行：`python3 -m unittest tests/test_logger_truncation.py`
预期：FAIL (ImportError: cannot import name 'truncate_log_text' from 'bsk.logger')

- [ ] **Step 3: 实现 `truncate_log_text` 并更新配置定义**

1. 在 `bsk/logger.py` 中实现 `truncate_log_text` 并将其加入 `__all__`：
```python
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
```
2. 在 `_conf_schema.json` 中增加 `log_max_output_length` 定义：
```json
"log_max_output_length": {
  "type": "int",
  "default": 2048,
  "description": "调试日志中工具返回与 bsk 命令输出的最大字符截断长度。设为 0 或负数表示不截断全量记录。"
}
```
3. 在 `bsk/config.py` 中的 `Settings` 增加字段 `log_max_output_length: int = 2048`，在 `parse_settings` 中增加解析：
```python
log_max_output_length = _get_int(
    raw, "log_max_output_length", default=2048, min_val=-1
)
```
并在 `validate_settings` 中校验其上限 `log_max_output_length <= 1_000_000`。

- [ ] **Step 4: 运行测试以确认通过**

运行：`python3 -m unittest tests/test_logger_truncation.py tests/test_config.py`
预期：PASS

---

### Task 2: BskRunner 日志注入与底层指令收敛记录

**Files:**
- Modify: `bsk/runner.py`
- Modify: `bsk/service.py`
- Create: `tests/test_runner_logging.py`
- Modify: `tests/test_logger_injection.py`

**Interfaces:**
- Consumes: `LoggerLike`, `NULL_LOGGER`, `truncate_log_text`, `Settings.log_max_output_length`
- Produces: 
  - `BskRunner.__init__(..., logger: LoggerLike | None = None, max_log_len: int = 2048)`
  - `BskRunner.run` emits DEBUG logs on start and completion/failure with timing, exit code, and truncated stdout/stderr.

- [ ] **Step 1: 编写 BskRunner 日志输出的失败测试**

在 `tests/test_runner_logging.py` 中编写单测：
```python
import unittest
from bsk.runner import BskRunner
from bsk.models import BskResult
from tests.test_logger_injection import RecordingLogger

class TestBskRunnerLogging(unittest.TestCase):
    async def test_runner_logs_start_and_finish_on_mock(self):
        # 验证 BskRunner 在执行命令时成对输出 [bsk] 执行命令开始 与 [bsk] 执行命令完成
        logger = RecordingLogger()
        runner = BskRunner("dummy_bsk", logger=logger, max_log_len=50)
        # 用 mock subprocess 或现有 fake runner 机制测试
        ...
```

- [ ] **Step 2: 运行测试以确认失败**

运行：`python3 -m unittest tests/test_runner_logging.py`
预期：FAIL (BskRunner 没有 logger 参数或未记录日志)

- [ ] **Step 3: 实现 BskRunner 的日志记录逻辑与 BskService 注入**

1. 修改 `bsk/runner.py`：
   - 导入 `truncate_log_text` 与 `LoggerLike`, `NULL_LOGGER`。
   - `BskRunner.__init__` 新增参数 `logger: LoggerLike | None = None, max_log_len: int = 2048`，保存至 `self._logger` 与 `self.max_log_len`。
   - 在 `run()` 方法中：
     - 命令启动前：
       ```python
       self._logger.debug(
           "[bsk] 执行命令开始: %s (超时=%s秒)",
           argv,
           f"{effective_timeout:.1f}" if effective_timeout else "默认",
       )
       ```
     - 捕获 `OSError` 抛出 `BskError` 前：
       ```python
       self._logger.debug(
           "[bsk] 执行命令失败: %s | 耗时: %.3fs | 错误: %r",
           argv,
           time.monotonic() - started,
           exc,
       )
       ```
     - 结束返回 `BskResult` 前（包括正常与超时）：
       ```python
       out_trunc = truncate_log_text(stdout, self.max_log_len)
       err_trunc = truncate_log_text(stderr, self.max_log_len)
       self._logger.debug(
           "[bsk] 执行命令完成: %s | 退出码: %s | 耗时: %.3fs | stdout: %s | stderr: %s",
           argv,
           code,
           elapsed,
           out_trunc,
           err_trunc,
       )
       ```
2. 修改 `bsk/service.py`：
   - 在 `BskService.__init__` 中实例化 `BskRunner` 时透传 `logger=self._logger` 和 `max_log_len=settings.log_max_output_length`。

- [ ] **Step 4: 运行测试以确认通过**

运行：`python3 -m unittest tests/test_runner_logging.py tests/test_logger_injection.py`
预期：PASS

---

### Task 3: 工具调用追踪切面装饰器与 16 个工具应用

**Files:**
- Modify: `main.py`
- Create: `tests/test_tool_logging.py`

**Interfaces:**
- Consumes: `truncate_log_text`, `astrbot.api.logger`, `Settings.log_max_output_length`, `event.unified_msg_origin`, `event.get_sender_id()`, `self._key(event)`
- Produces: `@_trace_tool_call(tool_name: str)` 修饰全部 16 个工具，实现成对输出 DEBUG 日志。

- [ ] **Step 1: 编写工具调用追踪切面的失败测试**

在 `tests/test_tool_logging.py` 中编写单测：
- 构造模拟的 `AstrMessageEvent`（带 `unified_msg_origin="group:123"`, `get_sender_id=lambda: "user_456"`）。
- 验证普通异步工具调用（如 `bsk_page`、`bsk_open`）产生两条日志：
  - `[工具调用开始] 工具: bsk_xxx | 会话: ... (umo=group:123, sender=user_456) | 参数: ...`
  - `[工具调用结束] 工具: bsk_xxx | 会话: ... | 耗时: ...s | 状态: 成功 | 返回: ...`
- 验证生成器工具（`bsk_screenshot`）完整 yield 项并产生对应的开始与结束日志。
- 验证权限拒绝（`_denied` 返回拒绝文案）正常产生开始与结束日志。
- 验证内部抛出异常时状态记录为 `异常` 且异常原样抛出。

- [ ] **Step 2: 运行测试以确认失败**

运行：`python3 -m unittest tests/test_tool_logging.py`
预期：FAIL (未捕获工具日志)

- [ ] **Step 3: 在 `main.py` 中实现 `_trace_tool_call` 并修饰所有工具**

1. 在 `main.py` 中引入 `functools`, `inspect`, `time` 以及 `from .bsk.logger import truncate_log_text`。
2. 实现 `_trace_tool_call(tool_name: str)` 装饰器工厂函数：
   - 处理普通异步协程：在入口打印开始日志，`try...except Exception...finally` 测量耗时并记录结束日志。
   - 处理异步生成器（通过 `inspect.isasyncgenfunction` 判断）：在开始迭代时打印开始日志，`async for` 迭代 `yield` 每一项并收集输出，`finally` 阶段打印结束日志。
3. 将 `@_trace_tool_call("bsk_xxx")` 依次添加到 16 个 `@filter.llm_tool("bsk_xxx")` 的正下方：
   - 8 个核心新工具：`bsk_session`, `bsk_page`, `bsk_inspect`, `bsk_debug`, `bsk_load_tools`, `bsk_interact`, `bsk_tabs`, `bsk_assist`。
   - 8 个旧版兼容工具：`bsk_open`, `bsk_read`, `bsk_act`, `bsk_screenshot`, `bsk_close`, `bsk_status`, `bsk_evaluate`, `bsk_logs`。

- [ ] **Step 4: 运行测试以确认通过**

运行：`python3 -m unittest tests/test_tool_logging.py`
预期：PASS

---

### Task 4: 全量测试、合规与回归验证

**Files:**
- Test: 全量单元测试套件
- Verify: `tests/verify_compliance.py`
- Verify: `tests/verify_release_ready.py`

**Interfaces:**
- Consumes: Task 1, 2, 3 全部交付物
- Produces: 零违规告警，900+ 单元测试 100% 通过。

- [ ] **Step 1: 运行全量单元测试套件**

运行：`python3 -m unittest discover -s astrbot_plugin_bsk_browser/tests`
预期：Ran 900+ tests ... OK

- [ ] **Step 2: 运行合规性核验脚本**

运行：`python3 astrbot_plugin_bsk_browser/tests/verify_compliance.py`
预期：全部 check 显示 [ok  ]，零 FAIL，零违规引入 `logging` 或违规 import astrbot。

- [ ] **Step 3: 运行发布前自检脚本**

运行：`python3 astrbot_plugin_bsk_browser/tests/verify_release_ready.py`
预期：发布自检项全部通过，零配置或元数据告警。
