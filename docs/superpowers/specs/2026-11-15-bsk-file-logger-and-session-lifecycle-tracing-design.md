# 设计文档：astrbot_plugin_bsk_browser 日志转存与 Session 全生命周期追踪

## 1. 意图与背景 (Intent & Why)

### 现状与痛点
在 `astrbot_plugin_bsk_browser` 中，机器人调用浏览器工具并驱动 `bsk` 命令行子进程执行页面操作。目前系统已具备基本的工具调用记录（`@_trace_tool_call`）以及底层 `BskRunner` 指令与输出的 DEBUG 日志。
然而，在多会话并发、长期运行与生产排查场景下，存在以下两项明显痛点：
1. **日志易随容器/控制台丢失且无法单独留存**：缺少将插件的所有运行与调试日志转存到指定外部文件的能力。当宿主 AstrBot 重启、日志轮转或控制台滚动过快时，排查历史偶发问题（如页面崩溃、卡死、权限被占）极为困难。
2. **Session 与页面/Tab 生命周期盲区**：虽然工具进出与子进程命令有日志，但**浏览器会话与页面标签的内部生命周期扭转**缺乏成体系的追踪。何时准备请求（`prepare`）、何时认领（`claim`）、何时启动新窗口、打开了哪个网址、打在哪个 Tab 上、何时关闭、何时因空闲超时回收、何时被容量淘汰、何时清理遗留孤儿，以及当前实时存活多少个 session/tab/窗口，均缺少结构化的 DEBUG 追踪日志。

### 目标定位
完善插件日志系统：
1. 在配置中提供可选的日志转存文件路径，具备安全探测能力（路径为空或无写权限则自动跳过，绝不报错中断插件）；
2. 基于依赖注入实现全分流的纯标准库 `FileLogger` / `TeeLogger`，将插件产生的所有日志（包括底层指令、工具调用、运行信息及本次新增的全部 DEBUG 日志）统一转存到该文件中，严格遵守无 `import logging` 的插件市场合规红线；
3. 为 `SessionManager` 与 `BskService` 补齐全流程 DEBUG 追踪与快照日志，做到会话与标签页流转全透明。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
1. **配置扩展与权限容错**：在 `_conf_schema.json` 与 `bsk/config.py` 中增加 `log_file_path` 配置项；在 `main.py` 初始化时进行探测，空串直接跳过，无操作/写入权限时发出 AstrBot 警告并安全降级，主业务流程不受任何影响。
2. **纯标准库转存分流器**：在 `bsk/logger.py` 中实现满足 `LoggerLike` 协议的 `FileLogger` 与 `TeeLogger`，具备线程安全锁、UTF-8 编码追加写入与标准时间戳/级别格式（`YYYY-MM-DD HH:MM:SS.mmm [LEVEL] msg`），全链路覆盖插件自身日志。
3. **Session 全生命周期追踪**：
   - 准备与认领：记录 `_prepare_request`（token）、`_claim_request`（token -> session_id）、`_cancel_request`。
   - 建立与获取：记录 `_start`、`_restart`、`acquire`，输出会话 ID、关联浏览器、窗口 ID（`agent_window_id`）及当前会话总数。
   - 关闭与清理：记录 `_stop_session_id`、`release`、`_shutdown_entries`，输出关闭原因（主动释放/退出清理/LRU淘汰）及剩余会话数。
   - 超时与淘汰：记录 `reap_idle`（空闲时长与阈值）、`_evict_for_capacity`（淘汰的会话及剩余容量）。
   - 孤儿会话恢复：记录 `recover_orphans`（探测到的遗留会话与启动请求 token，以及清理结果）。
4. **页面与 Tab 动作追踪**：
   - 页面导航：`open_page` 与 `navigate` 记录打开的目标 URL、所使用的 `tab_id`、窗口 ID 及当前已知 Tab 数量。
   - 标签管理：`tabs`（新建 `create`、切换 `select`、关闭 `close`、借用 `borrow`、归还 `return`）记录操作目标 Tab、URL 及变动后的 Tab 列表数量。
   - 自动行为：`detect_new_tabs_and_switch`（点击后检测新 Tab）与 `sweep_agent_tabs`（清理临时 Agent Tab）记录检测与清理前后的 Tab 状态。
5. **所有追踪日志严格保持 DEBUG 等级**：不提高日志等级，不刷屏普通用户正常会话。
6. **严格遵守架构规范与市场审核**：
   - 零 `import logging`、零 `import astrbot` 在 `bsk/` 内部；
   - `main.py` 仅使用 `astrbot.api.logger`；
   - 保证所有单元测试和架构检查脚本（`test_logger_injection.py`、`verify_compliance.py` 等）100% 通过。

### 非目标 (Non-Goals)
1. 不引入外部复杂的日志框架（如 loguru 等第三方包）。
2. 不修改 AstrBot 宿主程序自身的全局日志输出（只管理插件自身和注入组件的日志流）。
3. 不更改任何 LLM 工具的对外 schema、参数或面向大模型的返回文本。
4. 不在没有 Tab 操作的普通高频动作（如每次获取 HTML 或滚动）中强制注入额外的阻塞式 `bsk tab list` CLI 远程查询，以避免拉慢浏览器自动化性能；Tab 计数基于已知状态和各动作的实际载荷进行追踪。

### 反目标 (Anti-Goals)
1. **严禁写日志引发异常中断业务**：若磁盘满、权限被临时吊销或日志文件被外部删除/占用，写入异常必须被安全捕获并静默降级，绝不能抛出给上层工具或中断会话。
2. **严禁引入内置 `logging` 依赖**：绝不在 `bsk/` 或 `main.py` 中写 `import logging`，防止被插件市场合规核验一票否决。

---

## 3. 约束条件 (Constraints)

1. **合规红线**：AstrBot 插件审核规则要求插件只能使用 `astrbot.api.logger`，严禁使用 Python 内置 `logging` 模块；同时静态检查 `test_logger_injection.py` 强制要求 `bsk/` 不得 import 任何 `astrbot` 或 `logging`。
2. **并发与时序安全**：多会话可能在多个 asyncio 任务或线程池中调用日志，文件写入必须具备基本的线程安全锁保护。
3. **性能开销最小化**：格式化与写文件不得阻塞关键异步链路，日志级别关闭或降级时不产生多余计算。

---

## 4. 备选方案对比与决策 (Approaches)

### 方案一：纯标准库 `FileLogger` + `TeeLogger` 分流 + 内部状态埋点（选定）
- **做法**：
  在 `bsk/logger.py` 中基于原生文件操作与 `threading.Lock` 实现轻量线程安全的 `FileLogger`；实现 `TeeLogger` 将日志调用同时分发给主 logger（如 `astrbot_logger`）和 `FileLogger`。在 `main.py` 启动阶段检查 `log_file_path` 并执行写入探针：合法且可写则构建 `TeeLogger` 注入；无效或无权限则记录 warning 并回退。在 `SessionManager` 与 `BskService` 的关键生命周期节点打点输出格式化的 DEBUG 状态。
- **优点**：
  零外部依赖、零内置 `logging` 导入，100% 符合规范；即使进程非正常退出，文件末尾的追加写入也不会因为异步队列滞留而丢失；单机机器人场景下开销极低且极其稳定。
- **代价**：
  需手工实现基本的格式化（时间戳、级别前缀）与安全写入防护。

### 方案二：异步队列缓冲写盘（Async Log Queue Worker）
- **做法**：所有日志写入内存 `asyncio.Queue`，后台协程异步批量刷盘。
- **缺点与舍弃原因**：
  增加了额外的后台 Task 维护；在进程被 SIGTERM 终止、崩溃或发生同步异常关机时，队列中积攒的关键收尾日志容易丢失；且同步调用链路（如 `journal`）难以稳定访问事件循环。

### 方案三：使用标准库 `logging.FileHandler`
- **缺点与舍弃原因**：
  直接违反插件市场合规红线，且会被仓库现有静态 AST 检查拦截。

**决策**：选定**方案一**。

---

## 5. 详细实现设计 (Detailed Implementation)

### 5.1 配置项扩展 (`_conf_schema.json` & `bsk/config.py`)

1. **`_conf_schema.json`**：
   ```json
   "log_file_path": {
     "description": "日志转存文件路径",
     "type": "string",
     "default": "",
     "hint": "指定一个文件路径用于转存本插件的所有运行与调试日志。若留空或对该路径没有写入操作权限，则自动跳过转存，不影响插件正常运行。"
   }
   ```

2. **`bsk/config.py`**：
   - `Settings` 类增加字段：
     ```python
     log_file_path: str = ""
     """日志转存文件路径。为空或无写权限则不转存。"""
     ```
   - `parse_settings` 中解析：
     ```python
     log_file_path=_as_str(raw.get("log_file_path"), "").strip()
     ```
   - `validate_settings` 中校验：
     若填写的路径经展开后是已存在的目录，则提示问题（`log_file_path 指向了已有目录而不是文件`）。

---

### 5.2 纯标准库日志写入与分流 (`bsk/logger.py`)

在 `bsk/logger.py` 中新增以下组件（纯 Python 标准库，零 `logging` / 零 `astrbot` 依赖）：

1. **`FileLogger`**：
   - 属性：`path: Path`、`_lock: threading.Lock`、`_file: TextIO | None`、`_disabled: bool`。
   - 方法：
     - `debug`, `info`, `warning`, `error`, `exception` 均遵循 `LoggerLike` 签名 `(msg: object, *args: Any, **kwargs: Any) -> None`。
     - 格式化格式：`YYYY-MM-DD HH:MM:SS.mmm [LEVEL] <消息正文>`。
     - 若 `exception` 调用或含有 `exc_info=True`，附加 `traceback.format_exc()`。
     - 所有写盘操作用 `try...except OSError` 保护；一旦发生不可恢复写入错误，将 `_disabled = True` 标记降级并关闭句柄，永不向外抛出异常。
     - 提供 `close()` 方法供插件卸载时安全 flush 并关闭文件句柄。

2. **`TeeLogger`**：
   - 包装主 logger（如 `astrbot_logger`）与副 logger（如 `FileLogger`）。
   - 实现 `LoggerLike` 协议全部 5 个方法，内部逐个安全派发；主 logger 始终优先调用，副 logger 异常不波及主 logger。
   - 若副 logger 提供 `close()` 方法，在自身的 `close()` 中一并调用。

3. **探测与构建函数 `create_safe_file_logger(path_str: str) -> FileLogger | None`**：
   - 若 `not path_str`：返回 `None`。
   - 解析为 `Path(path_str).expanduser().resolve()`。
   - 若路径是现有目录：返回 `None`。
   - 尝试创建父目录：`path.parent.mkdir(parents=True, exist_ok=True)`。
   - 尝试以追加模式打开并尝试写空串探测权限：
     ```python
     try:
         with open(path, "a", encoding="utf-8") as f:
             f.write("")
         return FileLogger(path)
     except Exception:
         return None
     ```

---

### 5.3 插件入口装配 (`main.py`)

在 `BskBrowserPlugin.__init__` 中：
1. 检查 `self.settings.log_file_path`。
2. 若用户配置了路径：
   - 调用 `create_safe_file_logger(path)`。
   - 若返回 `None`（无权限或路径非法）：通过 `astrbot_logger.warning("[bsk_browser] 日志转存文件 %s 无写入权限或路径无效，已跳过文件转存。", path)`。
   - 若成功返回 `file_logger`：
     - 构建 `plugin_logger = TeeLogger(astrbot_logger, file_logger)`。
     - 保存 `self._file_logger = file_logger`。
     - 将 `plugin_logger` 注入给 `BskService`。
     - `main.py` 内部的工具拦截切面及各操作日志使用 `plugin_logger` 进行输出，确保工具调用日志和 bsk 内部日志一并转存。
3. 在插件卸载 `terminate` 时：
   - 若 `self._file_logger` 存在，调用其 `close()` 释放文件句柄。

---

### 5.4 会话与状态全生命周期追踪埋点 (`bsk/session.py`)

在 `SessionManager` 中为所有会话状态节点增加结构化 DEBUG 日志：

1. **会话准备 (`_prepare_request`)**：
   - `self._logger.debug("[会话准备] 准备启动请求 token=%s | 当前活跃会话数: %d, 槽位数: %d", request_id, active_count, slot_count)`
2. **会话认领 (`_claim_request`)**：
   - `self._logger.debug("[会话认领] 认领启动请求 token=%s | 会话ID: %s, 浏览器实例: %s", request_id, session_id, browser_instance)`
3. **会话取消 (`_cancel_request`)**：
   - `self._logger.debug("[会话取消] 取消未认领启动请求 token=%s", request_id)`
4. **会话启动与获取 (`_start` / `_restart` / `acquire`)**：
   - `self._logger.debug("[会话启动] 会话 %s 建立完成 | 浏览器: %s, 窗口ID: %s | 当前活跃会话数: %d/%d", session_id, browser, window_id, active_count, max_sessions)`
   - `self._logger.debug("[会话获取] key=%s, 会话ID=%s, 窗口ID=%s | 当前总会话数: %d", key, session_id, window_id, len(self._entries))`
5. **会话关闭与释放 (`_stop_session_id` / `release`)**：
   - `self._logger.debug("[会话关闭] 关闭会话 %s (key=%s, 窗口ID=%s) | 触发原因: %s | 剩余活跃会话数: %d", session_id, key, window_id, reason, remaining_count)`
6. **空闲超时回收 (`reap_idle`)**：
   - 对每个超时槽位：`self._logger.debug("[会话超时] 会话 %s (key=%s) 空闲超时 (已空闲 %.1fs >= 阈值 %.1fs) 执行回收", session_id, key, idle_sec, threshold)`
   - 回收结束：`self._logger.debug("[会话超时回收完成] 共回收 %d 个超时会话 | 剩余活跃会话数: %d", reaped, remaining)`
7. **容量淘汰 (`_evict_for_capacity`)**：
   - `self._logger.debug("[会话容量淘汰] 会话池已满 (%d/%d)，按 LRU 淘汰会话 %s (key=%s, 空闲 %.1fs)", count, max_sessions, session_id, key, idle_sec)`
8. **孤儿恢复 (`recover_orphans`)**：
   - `self._logger.debug("[孤儿会话检查] 开始检查遗留孤儿会话...")`
   - 对发现的孤儿会话/请求：`self._logger.debug("[孤儿会话清理] 清理遗留孤儿会话 %s (窗口ID=%s)", session_id, window_id)` 与 `self._logger.debug("[孤儿请求清理] 回收遗留未认领请求 token=%s", token)`
   - 清理完成：`self._logger.debug("[孤儿清理完成] 共清理 %d 个遗留会话与请求 | 当前会话池状态: %s", stopped, stats_summary)`

---

### 5.5 页面、网址与 Tab 追踪埋点 (`bsk/service.py`)

在 `BskService` 中为页面打开与 Tab 操作增加结构化 DEBUG 日志：

1. **页面打开与导航 (`open_page` / `navigate`)**：
   - `open_page`：`self._logger.debug("[页面打开] 会话: %s (窗口ID=%s) | 目标URL: %s | 当前已知Tab数: %s", key, window_id, url, known_tabs_count)`
   - `navigate`：`self._logger.debug("[页面导航] 会话: %s (窗口ID=%s) | 目标URL: %s | 指定Tab: %s", key, window_id, url, tab_id or "当前Tab")`
2. **标签操作 (`tabs`)**：
   - `action == "create"`：`self._logger.debug("[标签新建] 会话: %s | URL: %s | 当前Tab数: %s", key, url, tabs_count)`
   - `action == "select"`：`self._logger.debug("[标签切换] 会话: %s | 目标Tab: %s", key, target_tab_id)`
   - `action == "close"`：`self._logger.debug("[标签关闭] 会话: %s | 关闭Tab: %s", key, target_tab_id)`
   - `action == "borrow"`：`self._logger.debug("[标签借用] 会话: %s | 借用用户Tab: %s (超时=%ss)", key, target_tab_id, timeout)`
   - `action == "return"`：`self._logger.debug("[标签归还] 会话: %s | 归还用户Tab: %s", key, target_tab_id)`
3. **标签自动检测与扫尾 (`detect_new_tabs_and_switch` / `sweep_agent_tabs`)**：
   - `detect_new_tabs_and_switch`：`self._logger.debug("[新标签发现] 会话: %s | 点击后产生新Tab: %s，已自动切换 | 当前Tab总数: %d", key, new_tab_id, total_tabs)`
   - `sweep_agent_tabs`：`self._logger.debug("[标签扫尾清理] 会话: %s | 清理多余临时Tab: %s | 保留首个Agent Tab: %s", key, closed_tabs, keeper_id)`

---

## 6. 测试与验证策略 (Testing Strategy)

1. **配置单元测试 (`test_config.py`)**：
   - 验证 `log_file_path` 的解析与默认空串。
   - 验证 `log_file_path` 指向目录时的 validation 警告。
2. **日志写入器单元测试 (`test_logger_injection.py`)**：
   - 测试 `create_safe_file_logger`：空路径返回 `None`、目录返回 `None`、无写权限目录（如 `/root/test.log` 或不可写路径）安全返回 `None` 且不崩溃。
   - 测试 `FileLogger`：正常写入日志、格式串与参数惰性 `%` 格式化、时间戳与级别前缀、`exception` 时的堆栈格式化。
   - 测试 `TeeLogger`：主 logger 与文件 logger 同时收到相同日志；当副 logger 写入故障时主 logger 不受影响。
   - 静态 AST 检查保持通过：确保 `bsk/` 和 `main.py` 内部零 `import logging`。
3. **会话生命周期日志单元测试 (`test_session.py`)**：
   - 针对 `prepare`、`claim`、`start`、`stop`、`reap_idle`、`evict`、`recover_orphans`，使用 `RecordingLogger` 断言日志关键字与结构化字段出现。
4. **服务与 Tab 生命周期日志单元测试 (`test_service.py`)**：
   - 断言 `open_page`、`navigate`、`tabs`（create/select/close）、`detect_new_tabs_and_switch`、`sweep_agent_tabs` 的 DEBUG 记录。
5. **合规核验脚本**：
   - 运行 `python tests/verify_compliance.py` 与 `python tests/verify_release_ready.py`，确保合规与发布状态保持 100% 通过。

---

## 7. 留给实现者决定的细节 (Left to Builder)
1. 具体快照字符串微调（如 `active_count` 和 `slot_count` 在一条日志中的并列格式）。
2. `FileLogger` 内部单行最大刷新频率或 `flush()` 调用时机（默认每次写入后自动 flush，保证不丢日志）。
3. 提示信息与 warning 字符串的具体精简文案。
