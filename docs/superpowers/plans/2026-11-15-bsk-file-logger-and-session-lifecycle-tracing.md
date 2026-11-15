# 日志转存与 Session 全生命周期追踪实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `astrbot_plugin_bsk_browser` 增加安全的本地文件日志转存选项（路径空或无权限则静默跳过），并对 Session、页面打开及标签页操作实现全生命周期 DEBUG 日志与状态快照追踪。

**Architecture:** 基于纯 Python 标准库在 `bsk/logger.py` 中实现满足 `LoggerLike` 协议的 `FileLogger` 与 `TeeLogger` 分流器，在 `main.py` 启动阶段完成写入探针与依赖注入；在 `SessionManager` 与 `BskService` 各生命周期切入点埋设带计数快照的 DEBUG 日志，严格遵守无 `import logging` 的插件市场合规约束。

**Tech Stack:** Python 3.10+ (纯标准库, `threading`, `pathlib`, `unittest`)，AstrBot API (`astrbot.api.logger`)。

**Spec:** `docs/superpowers/specs/2026-11-15-bsk-file-logger-and-session-lifecycle-tracing-design.md`

## Global Constraints

- 严禁在 `bsk/` 及其子模块中引入 `astrbot` 或标准库 `logging` 模块（受 `tests/test_logger_injection.py` 与合规核验强制约束）。
- `main.py` 必须仅使用 `astrbot.api.logger`，严禁使用内置 `logging` 模块。
- 日志文件写入出现任何异常（权限丧失、磁盘满等）绝不能中断或抛出异常影响主业务流程。
- 所有生命周期追踪与状态快照日志必须使用 `DEBUG` 级别。
- 工具提示文本与其他文本需要能在正确表义基础上做到精炼简洁不啰嗦。
- 遵循 `AGENTS.md`：完成后核对 SKILL 文档并提交 git commit。

## Review Focus

1. **未创建的深层目录路径**：`log_file_path` 指向尚不存在的多层子目录（如 `/tmp/not_exist_sub/app.log`），应自动递归创建父目录并成功转存。
2. **只读或无写权限路径**：`log_file_path` 指向无写权限目录（如 `/root/forbidden.log`），必须安全降级、发出 warning 并不抛出未捕获异常。
3. **指向已有目录而非文件**：`log_file_path` 填入已有目录名，`create_safe_file_logger` 必须识别并返回 `None`，不覆写或破坏目录。
4. **日志写入期间突发 IOError**：写入过程中文件被删除或不可写，`FileLogger` 必须安全捕获并将自身标记为 disabled，绝不向外抛出异常。
5. **并发调用与优雅关闭**：多个协程同时打印日志时线程安全，且在插件卸载 `terminate` 时正确关闭文件句柄。

---

### Task 1: 配置项扩展 (`log_file_path`) 与校验

**Files:**
- Modify: `astrbot_plugin_bsk_browser/_conf_schema.json`
- Modify: `astrbot_plugin_bsk_browser/bsk/config.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_config.py`

**Interfaces:**
- Produces: `Settings.log_file_path: str`

- [ ] **Step 1: Write the failing tests in `tests/test_config.py`**

```python
    def test_log_file_path_defaults_to_empty(self) -> None:
        s = parse_settings({})
        self.assertEqual(s.log_file_path, "")

    def test_log_file_path_strips_whitespace(self) -> None:
        s = parse_settings({"log_file_path": "  /tmp/bsk.log  "})
        self.assertEqual(s.log_file_path, "/tmp/bsk.log")

    def test_validate_settings_warns_if_log_file_path_is_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            s = parse_settings({"log_file_path": td})
            problems = validate_settings(s)
            self.assertTrue(any("目录" in p for p in problems))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd astrbot_plugin_bsk_browser && python3 -m unittest tests/test_config.py -k test_log_file_path`
Expected: FAIL (AttributeError: 'Settings' object has no attribute 'log_file_path')

- [ ] **Step 3: Implement `log_file_path` in `bsk/config.py` and `_conf_schema.json`**

- In `bsk/config.py`:
  - Add `log_file_path: str = ""` to `Settings` dataclass.
  - In `parse_settings`: `log_file_path=_as_str(raw.get("log_file_path"), "").strip()`.
  - In `validate_settings`: check if `s.log_file_path` is non-empty and `Path(s.log_file_path).is_dir()`, add warning problem if so.
- In `_conf_schema.json`:
  - Add `"log_file_path"` field definition (type: string, default: "", description and hint).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd astrbot_plugin_bsk_browser && python3 -m unittest tests/test_config.py`
Expected: PASS (all tests in test_config.py pass)

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_bsk_browser && git add _conf_schema.json bsk/config.py tests/test_config.py
git commit -m "feat(config): add log_file_path configuration and validation"
```

---

### Task 2: 纯标准库 `FileLogger` 与 `TeeLogger` 分流器

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/logger.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_logger_injection.py`

**Interfaces:**
- Produces:
  - `class FileLogger: LoggerLike`
  - `class TeeLogger: LoggerLike`
  - `def create_safe_file_logger(path_str: str) -> FileLogger | None`

- [ ] **Step 1: Write the failing tests in `tests/test_logger_injection.py`**

```python
    def test_create_safe_file_logger_empty_or_dir(self) -> None:
        self.assertIsNone(create_safe_file_logger(""))
        self.assertIsNone(create_safe_file_logger("   "))
        self.assertIsNone(create_safe_file_logger(str(self.dir)))

    def test_create_safe_file_logger_creates_parent_and_file(self) -> None:
        target = self.dir / "sub" / "app.log"
        logger = create_safe_file_logger(str(target))
        self.assertIsNotNone(logger)
        try:
            logger.debug("测试 debug %s", "成功")
            content = target.read_text(encoding="utf-8")
            self.assertIn("[DEBUG]", content)
            self.assertIn("测试 debug 成功", content)
        finally:
            logger.close()

    def test_tee_logger_dispatches_to_multiple_loggers(self) -> None:
        rec1 = RecordingLogger()
        rec2 = RecordingLogger()
        tee = TeeLogger(rec1, rec2)
        tee.info("信息 %d", 123)
        self.assertEqual(len(rec1.records), 1)
        self.assertEqual(len(rec2.records), 1)
        self.assertIn("信息 123", rec1.rendered())
        self.assertIn("信息 123", rec2.rendered())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd astrbot_plugin_bsk_browser && python3 -m unittest tests/test_logger_injection.py -k test_create_safe_file_logger`
Expected: FAIL (ImportError / NameError: create_safe_file_logger not found)

- [ ] **Step 3: Implement `FileLogger`, `TeeLogger`, and `create_safe_file_logger` in `bsk/logger.py`**

- In `bsk/logger.py`:
  - `FileLogger`:
    - Takes `path: Path | str`, opens in append mode (`open(path, "a", encoding="utf-8")`), stores `threading.Lock()`.
    - Implements `debug`, `info`, `warning`, `error`, `exception`.
    - Formats timestamp `datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]`, level in brackets `[LEVEL]`, lazy `%` format, and `traceback.format_exc()` if exception or `exc_info`.
    - Writes line, flushes; catches `OSError` and marks `self._disabled = True`, closes file, never raises.
    - Implements `close()`.
  - `TeeLogger`:
    - Accepts `*loggers: LoggerLike`.
    - Delegates all 5 methods to each logger in sequence. Catches exceptions from non-primary loggers.
    - Implements `close()` calling `close()` on any logger that has it.
  - `create_safe_file_logger(path_str: str) -> FileLogger | None`:
    - Returns `None` if empty, whitespace, or points to existing directory.
    - Attempts `path.parent.mkdir(parents=True, exist_ok=True)` and probe write.
    - Returns `FileLogger(path)` on success, `None` on any `OSError`/`Exception`.
  - Ensure `__all__` exports `FileLogger`, `TeeLogger`, `create_safe_file_logger`.
  - Ensure zero `import logging` or `import astrbot` is added!

- [ ] **Step 4: Run test to verify it passes and verify AST checks**

Run: `cd astrbot_plugin_bsk_browser && python3 -m unittest tests/test_logger_injection.py`
Expected: PASS (all tests including AST checks pass)

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_bsk_browser && git add bsk/logger.py tests/test_logger_injection.py
git commit -m "feat(logger): implement pure-stdlib FileLogger and TeeLogger"
```

---

### Task 3: `main.py` 插件日志分流注入与安全挂载

**Files:**
- Modify: `astrbot_plugin_bsk_browser/main.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_logger_injection.py`

**Interfaces:**
- Consumes: `create_safe_file_logger`, `TeeLogger` from `bsk/logger.py`
- Produces: `self._plugin_logger`, `self._file_logger` in `BskBrowserPlugin`

- [ ] **Step 1: Write test for main plugin file logger initialization**

Add unit test in `tests/test_logger_injection.py` testing logger wiring behavior:
- Verify that if `log_file_path` is empty or invalid, `create_safe_file_logger` returns `None` and fallback behaves gracefully.
- Verify that if `file_logger` exists, `TeeLogger` receives calls from both `@_trace_tool_call` and `service`.

- [ ] **Step 2: Run test to verify behavior**

Run: `cd astrbot_plugin_bsk_browser && python3 -m unittest tests/test_logger_injection.py`

- [ ] **Step 3: Modify `main.py` to initialize and inject the file logger**

- In `main.py` `BskBrowserPlugin.__init__`:
  - Check `self.settings.log_file_path`.
  - If given:
    ```python
    file_logger = create_safe_file_logger(self.settings.log_file_path)
    if file_logger is None:
        astrbot_logger.warning(
            "[bsk_browser] 日志转存文件 %s 无写入权限或路径无效，已跳过文件转存。",
            self.settings.log_file_path,
        )
        self._file_logger = None
        self._plugin_logger = astrbot_logger
    else:
        self._file_logger = file_logger
        self._plugin_logger = TeeLogger(astrbot_logger, file_logger)
    ```
  - If not given:
    `self._file_logger = None`, `self._plugin_logger = astrbot_logger`.
  - Pass `logger=self._plugin_logger` when instantiating `BskService`.
  - Update `@_trace_tool_call` in `main.py` to use `self._plugin_logger.debug` instead of direct `astrbot_logger.debug`.
- In `main.py` `terminate`:
  - If `self._file_logger is not None`, call `self._file_logger.close()`.

- [ ] **Step 4: Run test suite to verify AST and functionality**

Run: `cd astrbot_plugin_bsk_browser && python3 -m unittest tests/test_logger_injection.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_bsk_browser && git add main.py tests/test_logger_injection.py
git commit -m "feat(main): wire TeeLogger into plugin lifecycle and tool tracing"
```

---

### Task 4: `SessionManager` 全生命周期 DEBUG 追踪

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/session.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_session.py`

**Interfaces:**
- Emits DEBUG logs for:
  - `_prepare_request`: `[会话准备] 准备启动请求 token=%s | 当前活跃会话数: %d, 槽位数: %d`
  - `_claim_request`: `[会话认领] 认领启动请求 token=%s | 会话ID: %s, 浏览器实例: %s`
  - `_cancel_request`: `[会话取消] 取消未认领启动请求 token=%s`
  - `_start` / `_restart` / `acquire`: `[会话启动] 会话 %s 建立完成 | 浏览器: %s, 窗口ID: %s | 当前活跃会话数: %d/%d` and `[会话获取]`
  - `_stop_session_id` / `release`: `[会话关闭] 关闭会话 %s (key=%s, 窗口ID=%s) | 触发原因: %s | 剩余活跃会话数: %d`
  - `reap_idle`: `[会话超时]` and `[会话超时回收完成]`
  - `_evict_for_capacity`: `[会话容量淘汰]`
  - `recover_orphans`: `[孤儿会话检查]`, `[孤儿会话清理]`, `[孤儿请求清理]`, `[孤儿清理完成]`

- [ ] **Step 1: Write failing tests in `tests/test_session.py`**

Add test checking lifecycle log outputs on `RecordingLogger`:
```python
    async def test_lifecycle_logs_emitted(self) -> None:
        rec = RecordingLogger()
        manager = SessionManager(FakeRunner(), make_settings(), logger=rec)
        session = await manager.acquire("umo-1")
        self.assertTrue(any("[会话启动]" in m or "[会话获取]" in m for m in rec.rendered()))
        await manager.release("umo-1")
        self.assertTrue(any("[会话关闭]" in m for m in rec.rendered()))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd astrbot_plugin_bsk_browser && python3 -m unittest tests/test_session.py -k test_lifecycle_logs_emitted`
Expected: FAIL (assertion false)

- [ ] **Step 3: Implement lifecycle logs in `bsk/session.py`**

- In `_prepare_request`: log token, active sessions count (`len([e for e in self._entries.values() if e.session.session_id])`), and slot count (`len(self._entries)`).
- In `_claim_request`: log token, claimed session ID, and browser instance.
- In `_cancel_request`: log cancelled token.
- In `_start` / `_start_into`: log session ID, browser instance, window ID, and active vs max sessions count.
- In `acquire`: log key, session ID, window ID, and total sessions count.
- In `_stop_session_id` / `_stop_entry`: log session ID, key, window ID, reason (e.g. "主动释放", "空闲超时", "容量淘汰", "关闭清理"), and remaining sessions count.
- In `reap_idle`: log for each reaped session with idle seconds and threshold, plus end summary.
- In `_evict_for_capacity`: log evicted session key and idle duration.
- In `recover_orphans`: log orphan scan start, each stopped orphan session and token, and completion summary.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd astrbot_plugin_bsk_browser && python3 -m unittest tests/test_session.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_bsk_browser && git add bsk/session.py tests/test_session.py
git commit -m "feat(session): add structured DEBUG lifecycle logs to SessionManager"
```

---

### Task 5: `BskService` 页面与 Tab 全生命周期 DEBUG 追踪

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_service.py`

**Interfaces:**
- Emits DEBUG logs for:
  - `open_page` / `navigate`: `[页面打开]` / `[页面导航]`
  - `tabs`: `[标签新建]`, `[标签切换]`, `[标签关闭]`, `[标签借用]`, `[标签归还]`
  - `detect_new_tabs_and_switch`: `[新标签发现]`
  - `sweep_agent_tabs`: `[标签扫尾清理]`

- [ ] **Step 1: Write failing tests in `tests/test_service.py`**

Add tests checking DEBUG logs for `open_page`, `navigate`, and `tabs` actions:
```python
    async def test_page_and_tabs_lifecycle_logs(self) -> None:
        rec = RecordingLogger()
        service = BskService(make_settings(), runner=FakeRunner(), logger=rec)
        await service.open_page("umo-1", "https://example.com")
        self.assertTrue(any("[页面打开]" in m for m in rec.rendered()))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd astrbot_plugin_bsk_browser && python3 -m unittest tests/test_service.py -k test_page_and_tabs_lifecycle_logs`
Expected: FAIL

- [ ] **Step 3: Implement page and tab logs in `bsk/service.py`**

- In `open_page`: log session key, window ID, target URL, and known tabs count.
- In `navigate`: log session key, window ID, target URL, specified `tab_id`.
- In `tabs`:
  - When `action == "create"`: log `[标签新建]` with url and tab count.
  - When `action == "select"`: log `[标签切换]` with target tab_id.
  - When `action == "close"`: log `[标签关闭]` with target tab_id.
  - When `action == "borrow"`: log `[标签借用]` with target tab_id and timeout.
  - When `action == "return"`: log `[标签归还]` with target tab_id.
- In `detect_new_tabs_and_switch`: log `[新标签发现]` with new tab_id and total tab count.
- In `sweep_agent_tabs`: log `[标签扫尾清理]` with cleaned temporary tabs and retained keeper tab.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd astrbot_plugin_bsk_browser && python3 -m unittest tests/test_service.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd astrbot_plugin_bsk_browser && git add bsk/service.py tests/test_service.py
git commit -m "feat(service): add page navigation and tab lifecycle DEBUG logs"
```

---

### Task 6: 合规核验、SKILL 校验与最终全量自测

**Files:**
- Inspect: `astrbot_plugin_bsk_browser/skill/bsk-browser/`
- Run: `tests/verify_compliance.py`
- Run: Full unit test suite `python3 -m unittest discover tests`

- [ ] **Step 1: Inspect and update SKILL document if needed**

Inspect `astrbot_plugin_bsk_browser/skill/bsk-browser/` per `AGENTS.md` rules. Ensure explanations of configuration or tool actions are accurate and concise.

- [ ] **Step 2: Run compliance check**

Run: `cd astrbot_plugin_bsk_browser && python3 tests/verify_compliance.py`
Expected: 26 passed, 0 failed.

- [ ] **Step 3: Run full unittest test suite**

Run: `cd astrbot_plugin_bsk_browser && python3 -m unittest discover tests`
Expected: ALL test suites pass (0 errors, 0 failures).

- [ ] **Step 4: Final commit and git status verification**

Run: `cd astrbot_plugin_bsk_browser && git status`
Ensure clean working tree, commit any final changes:
```bash
git add .
git commit -m "chore: complete logging enhancement with compliance verification"
```
