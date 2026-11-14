# 设计文档：astrbot_plugin_bsk_browser 完整 DEBUG 日志系统

## 1. 意图与背景 (Intent & Why)

### 现状与痛点
在 `astrbot_plugin_bsk_browser` 中，机器人通过大语言模型调用浏览器工具（新版 8 个工具 + 兼容旧版 8 个工具）并驱动底层的 `bsk` CLI 命令行子进程执行自动化浏览器交互。
目前系统存在以下日志盲区：
1. **工具调用黑盒化**：工具被调用时没有统一的调试切面，缺少精确的时间点戳记、触发该调用的平台会话标识（`unified_msg_origin`、发送者 ID、内部浏览器会话键）以及调用的入参出参追踪。
2. **底层 bsk 调用无记录**：`bsk/runner.py`（负责执行 `bsk <命令> --json` 的核心收敛点）未接入日志，无法获知子进程实际执行了哪些命令参数、命令耗时多少、标准输出/标准错误是什么、退出码如何。当子进程超时卡死或执行出错时难以定位。
3. **输出体积失控风险**：网页的 DOM 结构大纲、完整 HTML 源码或网络抓包 JSON 数据可能长达数万字符，全量打印会迅速刷爆日志文件与控制台；缺少可配置的保护性字符截断机制。

### 目标定位
建立一套无遗漏、结构清晰、带输出截断保护的 DEBUG 等级调试日志体系，完整串联「平台消息触发 -> 工具分派执行 -> 底层 bsk 命令调用 -> 工具返回回执」的全链路。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **工具调用全覆盖**：覆盖全部 16 个 LLM 工具（8 个核心工具 + 8 个旧版兼容工具），每次调用在「开始」与「结束」时各输出一条 DEBUG 日志。
2. **会话与时序信息完整**：工具日志必须记录触发时间戳、工具名、平台会话标识（`event.unified_msg_origin`、`sender_id`、插件内部浏览器会话 key/session_id）、输入参数、执行耗时、执行状态（成功/异常/拒绝）与返回结果。
3. **底层 bsk 指令全覆盖**：收敛在 `BskRunner.run` 中，每次子进程调用在「开始」与「结束」时各输出一条 DEBUG 日志，记录完整 `argv` 命令行、超时设定、执行耗时、退出码、截断后的 `stdout` 和 `stderr`。
4. **输出字符上限可配置**：在插件配置（`_conf_schema.json` 与 `bsk/config.py`）中增加 `log_max_output_length` 配置项（默认 2048 字符，0 或负数表示不截断），统一控制工具出参和 bsk 命令输出的日志截断。
5. **严格遵守分层与审核规范**：
   - 框架层（`main.py`）使用 `astrbot.api.logger`；
   - 内部层（`bsk/`）严禁直接 `import astrbot`，通过 `bsk/logger.py` 的 `LoggerLike` 协议依赖注入；
   - 绝不使用 Python 内置 `logging` 模块。
6. **异步生成器完全兼容**：完美支持 `bsk_screenshot` 这种返回 `AsyncGenerator`（包含 `yield image_result` 和 `yield text`）的工具，不丢失结束日志与耗时统计。
7. **完备测试防护**：编写自动化单元测试，确保现有 900+ 单元测试以及 `verify_compliance.py`、`verify_release_ready.py` 全部 100% 通过。

### 非目标 (Non-Goals)
1. 不更改任何工具面向大模型或最终用户的业务返回文本。
2. 不修改 BrowserSkill 上游可执行文件或扩展源码。
3. 不新增外部第三方依赖库。
4. 不将日志级别提升到 INFO/WARNING（严格保持全部以 DEBUG 级别输出，避免非排查场景下的日志干扰）。

### 反目标 (Anti-Goals)
1. **严禁漏掉任何调用**：即使发生权限拒绝、参数校验失败、内部未捕获异常或超时，也必须成对输出「开始」与「结束」日志。
2. **严禁日志异常中断主流程**：日志格式化、参数序列化或截断逻辑出现任何异常时，绝不能影响工具执行或 bsk 命令的正常返回。
3. **严禁破坏已有工具的签名与 Docstring**：装饰器包装后必须保留原始函数的 `__name__`、`__doc__` 和参数签名，确保 AstrBot 框架的 schema 解析不受影响。

---

## 3. 约束条件 (Constraints)
1. **AstrBot 市场审核约束**：面向框架的日志只能来自 `from astrbot.api import logger`。
2. **架构分层约束**：`bsk/` 必须保持无框架依赖，保证独立单测与脚本可用性。
3. **函数绑定约束**：AstrBot 框架通过 `handler.__module__ == metadata.module_path` 决定是否绑定 `self` 实例，切面包装必须保留模块属性。

---

## 4. 备选方案对比与决策 (Approaches)

### 方案一：装饰器切面拦截（选定）
- **做法**：在 `main.py` 内实现统一的 `@_trace_tool_call` 异步切面装饰器，修饰 16 个工具方法（自动适配协程与异步生成器）；在 `bsk/runner.py` 中为 `BskRunner` 注入 `LoggerLike` 和配置的截断长度并在 `run()` 内打点。
- **优点**：业务代码零侵入、逻辑无重复；无论发生异常还是正常退出，均由切面严格保障成对输出，100% 杜绝漏记。
- **代价**：切面装饰器需要兼顾普通异步函数与异步生成器两种返回模式。

### 方案二：分发层改造收拢
- **做法**：重构 `_dispatch`，将旧工具也一并收拢进 `_dispatch` 转发，在 `_dispatch` 统一埋点。
- **缺点**：旧工具参数签名多样且包含生成器，强行重构改动面过大，易引发回归问题。

### 方案三：各工具函数体内联手动打点
- **做法**：在 9 处函数中分别手动手写日志。
- **缺点**：重复代码多，极易遗漏异常分支的结束日志，维护性差。

**决策**：用户明确选定**方案一**。

---

## 5. 详细实现设计 (Detailed Implementation)

### 5.1 配置项扩展 (`_conf_schema.json` & `bsk/config.py`)

1. **Schema 定义 (`_conf_schema.json`)**：
   ```json
   "log_max_output_length": {
     "type": "int",
     "default": 2048,
     "description": "调试日志中工具返回与 bsk 命令输出的最大字符截断长度。设为 0 或负数表示不截断全量记录。"
   }
   ```

2. **配置解析 (`bsk/config.py`)**：
   - `Settings` 类增加字段：
     ```python
     log_max_output_length: int = 2048
     ```
   - `parse_settings` 解析字段：
     ```python
     log_max_output_length = _get_int(
         raw, "log_max_output_length", default=2048, min_val=-1
     )
     ```
   - 验证配置项在范围 `[-1, 1_000_000]` 内，不合法时降级为 2048 并报 warning。

---

### 5.2 字符串截断辅助逻辑 (`bsk/logger.py`)

在 `bsk/logger.py` 中增加公共截断辅助函数（供 `BskRunner` 与 `main.py` 共用）：
```python
def truncate_log_text(text: Any, max_len: int) -> str:
    """按字符上限截断日志文本。
    
    Args:
        text: 待截断的内容（非字符串安全转为 str）。
        max_len: 字符上限；<= 0 表示不截断。
        
    Returns:
        安全截断后的字符串，若截断则附带 '... [已截断，共 N 字符]' 后缀。
    """
    if text is None:
        return ""
    s = str(text) if not isinstance(text, str) else text
    if max_len <= 0 or len(s) <= max_len:
        return s
    return f"{s[:max_len]}... [已截断，共 {len(s)} 字符]"
```

---

### 5.3 底层 bsk 指令日志 (`bsk/runner.py` & `bsk/service.py`)

1. **`BskRunner` 初始化与属性**：
   ```python
   class BskRunner:
       def __init__(
           self,
           bsk_path: str,
           default_timeout: float = 60.0,
           cancel_grace: float = DEFAULT_CANCEL_GRACE_SEC,
           logger: LoggerLike | None = None,
           max_log_len: int = 2048,
       ) -> None:
           self._logger = logger or NULL_LOGGER
           self.max_log_len = max_log_len
           ...
   ```

2. **`BskRunner.run` 内记录起止**：
   - **开始日志**：
     ```python
     self._logger.debug(
         "[bsk] 执行命令开始: %s (超时=%s秒)",
         argv,
         f"{effective_timeout:.1f}" if effective_timeout else "默认",
     )
     ```
   - **结束日志**（覆盖正常完成、超时、异常）：
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
   - 若创建子进程阶段抛出异常（如 `OSError` / `BskError`）：
     在抛出前打出：
     ```python
     self._logger.debug(
         "[bsk] 执行命令失败: %s | 耗时: %.3fs | 错误: %r",
         argv,
         time.monotonic() - started,
         exc,
     )
     ```

3. **`BskService` 依赖注入传递 (`bsk/service.py`)**：
   在 `BskService.__init__` 中实例化 `BskRunner` 时，将 `self._logger` 和 `settings.log_max_output_length` 传入：
   ```python
   self.runner = runner or BskRunner(
       settings.bsk_path,
       default_timeout=settings.command_timeout_sec,
       logger=self._logger,
       max_log_len=settings.log_max_output_length,
   )
   ```

---

### 5.4 工具调用追踪切面 (`main.py`)

1. **切面装饰器 `_trace_tool_call`**：
   统一封装普通异步函数与异步生成器：
   ```python
   def _trace_tool_call(tool_name: str):
       def decorator(func):
           @functools.wraps(func)
           async def async_wrapper(self, event: AstrMessageEvent, *args, **kwargs):
               # 提取会话上下文
               umo = getattr(event, "unified_msg_origin", "") or ""
               try:
                   sender = str(event.get_sender_id() or "")
               except Exception:
                   sender = ""
               session_key = self._key(event)
               started = time.monotonic()

               astrbot_logger.debug(
                   "[工具调用开始] 工具: %s | 会话: %s (umo=%s, sender=%s) | 参数: %s",
                   tool_name,
                   session_key,
                   umo,
                   sender,
                   kwargs,
               )
               try:
                   ret = await func(self, event, *args, **kwargs)
               except Exception as exc:
                   elapsed = time.monotonic() - started
                   astrbot_logger.debug(
                       "[工具调用结束] 工具: %s | 会话: %s | 耗时: %.3fs | 状态: 异常 | 错误: %r",
                       tool_name,
                       session_key,
                       elapsed,
                       exc,
                   )
                   raise

               elapsed = time.monotonic() - started
               max_len = getattr(self.settings, "log_max_output_length", 2048)
               ret_trunc = truncate_log_text(ret, max_len)
               astrbot_logger.debug(
                   "[工具调用结束] 工具: %s | 会话: %s | 耗时: %.3fs | 状态: 成功 | 返回: %s",
                   tool_name,
                   session_key,
                   elapsed,
                   ret_trunc,
               )
               return ret

           @functools.wraps(func)
           async def gen_wrapper(self, event: AstrMessageEvent, *args, **kwargs):
               # 异步生成器专用包装 (如 bsk_screenshot)
               umo = getattr(event, "unified_msg_origin", "") or ""
               try:
                   sender = str(event.get_sender_id() or "")
               except Exception:
                   sender = ""
               session_key = self._key(event)
               started = time.monotonic()
               outputs = []

               astrbot_logger.debug(
                   "[工具调用开始] 工具: %s | 会话: %s (umo=%s, sender=%s) | 参数: %s",
                   tool_name,
                   session_key,
                   umo,
                   sender,
                   kwargs,
               )
               try:
                   async for item in func(self, event, *args, **kwargs):
                       outputs.append(item)
                       yield item
               except Exception as exc:
                   elapsed = time.monotonic() - started
                   astrbot_logger.debug(
                       "[工具调用结束] 工具: %s | 会话: %s | 耗时: %.3fs | 状态: 异常 | 错误: %r",
                       tool_name,
                       session_key,
                       elapsed,
                       exc,
                   )
                   raise

               elapsed = time.monotonic() - started
               max_len = getattr(self.settings, "log_max_output_length", 2048)
               summary = " | ".join(str(o) for o in outputs)
               ret_trunc = truncate_log_text(summary, max_len)
               astrbot_logger.debug(
                   "[工具调用结束] 工具: %s | 会话: %s | 耗时: %.3fs | 状态: 成功 | 返回: %s",
                   tool_name,
                   session_key,
                   elapsed,
                   ret_trunc,
               )

           if inspect.isasyncgenfunction(func):
               return gen_wrapper
           return async_wrapper
       return decorator
   ```

2. **工具修饰应用**：
   在 `main.py` 中为全部 16 个工具添加修饰器：
   - 8 个新工具：`bsk_session`, `bsk_page`, `bsk_inspect`, `bsk_debug`, `bsk_load_tools`, `bsk_interact`, `bsk_tabs`, `bsk_assist`
   - 8 个旧工具：`bsk_open`, `bsk_read`, `bsk_act`, `bsk_screenshot`, `bsk_close`, `bsk_status`, `bsk_evaluate`, `bsk_logs`
   - 修饰顺序：
     ```python
     @filter.llm_tool("bsk_xxx")
     @_trace_tool_call("bsk_xxx")
     async def bsk_xxx(self, event: AstrMessageEvent, ...):
         ...
     ```

---

## 6. 测试与验证策略 (Testing & Verification)

### 6.1 单元测试新增与更新
1. **`tests/test_runner_logging.py` (新增)**：
   - 注入 `RecordingLogger` 校验 `BskRunner.run` 在成功、失败、超时时均打印 DEBUG 级别的开始与结束日志。
   - 校验输出文本超过 `max_log_len` 时正确触发截断并添加省略提示。
   - 校验未注入 logger（`NULL_LOGGER`）时不抛任何异常。
2. **`tests/test_tool_logging.py` (新增)**：
   - 验证普通异步工具（如 `bsk_page`、`bsk_open`）调用时输出包含会话 `umo`、`sender`、参数和返回值的成对日志。
   - 验证生成器工具（`bsk_screenshot`）调用时输出包含开始与结束日志，且 `yield` 内容正确透传。
   - 验证权限拒绝（`_denied`）时能够正常捕获并打印调用结束日志。
3. **`tests/test_config.py`**：
   - 增加对 `log_max_output_length` 默认值（2048）、合法正整数、0（不截断）、负数及非法类型的单测验证。

### 6.2 质量门禁与回归
- 运行 `python -m unittest discover -s tests`，确保全部现有用例及新增用例全部绿色通过。
- 运行 `python tests/verify_compliance.py`，确认无直接依赖 `logging` 或违规引用。
- 运行 `python tests/verify_release_ready.py`，确认发布合规性无告警。

---

## 7. 交付物与影响范围 (Deliverables & Impact)
- 修改 `_conf_schema.json`
- 修改 `bsk/config.py`
- 修改 `bsk/logger.py`（增加 `truncate_log_text`）
- 修改 `bsk/runner.py`（注入 logger 与起止日志）
- 修改 `bsk/service.py`（实例化 runner 时透传 logger 与截断配置）
- 修改 `main.py`（增加 `_trace_tool_call` 并修饰全部 16 个工具）
- 新增 `tests/test_runner_logging.py` 与 `tests/test_tool_logging.py`
- 更新现有配置测试 `tests/test_config.py` 与 logger 注入测试 `tests/test_logger_injection.py`
