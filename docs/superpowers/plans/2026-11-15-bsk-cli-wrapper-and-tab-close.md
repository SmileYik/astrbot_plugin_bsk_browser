# BskCli Semantic Wrapper Layer and Safe Tab Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `BskCli` semantic wrapper layer and safe tab closure workflow (`select` -> `sync` -> `close`), eliminate raw `runner.run(...)` calls, and prevent browser tab leaks during session cleanup.

**Architecture:** 
1. New `bsk/cli.py` defines `BskCli`, wrapping bsk CLI commands into strongly-typed methods with detailed docstrings, default arguments, and `close_tab_safe` composition logic.
2. `BskRunner` associates `self.cli = BskCli(self)` so components and tests can access it seamlessly.
3. `SessionManager` and `BskService` replace raw `runner.run(...)` calls with `BskCli` semantic methods and use `close_tab_safe` on all session tabs during cleanup.
4. Update `skills/bsk-browser/SKILL.md` and verify all tests pass.

**Tech Stack:** Python 3.10+, asyncio, pytest, AstrBot Plugin SDK.

**Spec:** `docs/superpowers/specs/2026-11-15-bsk-cli-wrapper-and-tab-close-design.md`

## Global Constraints

- **Single repository scope**: Modify only files within `./astrbot_plugin_bsk_browser/`.
- **Logging requirements**: Strictly use AstrBot logger at DEBUG level for bsk command input/output and tool invocations.
- **Git version management**: Commit repository changes after each task.
- **Concise copy**: Keep UI/user-facing copy and SKILL documentation concise and precise.

## Review Focus

1. **Background dynamic tab observation invalidation**: Background tab DOM mutation causes `sync` token to be rejected by `tab close` (`observation_changed`). Test must verify `select_tab` is called before `sync_tab`.
2. **Missing credentials fallback**: If `sync` fails or returns no credentials, `close_tab` must still attempt closing rather than crashing the cleanup pipeline.
3. **Session window auto-close on last tab**: Closing the last tab causes bsk to terminate the Agent window (`session_window_closed`). Cleanup must tolerate subsequent `session stop` returning `not_found`.
4. **Parameter typing and defaults**: All wrapper functions must have required arguments first, optional arguments with default values (`json=True`, `timeout=5.0`), and explicit type annotations.
5. **No leftover raw runner calls**: Ensure all bare `runner.run(["tab", ...])` and `runner.run(["session", ...])` are replaced by semantic `BskCli` calls.

---

### Task 1: Create `BskCli` with Core Command Wrappers in `bsk/cli.py`

**Files:**
- Create: `astrbot_plugin_bsk_browser/bsk/cli.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_cli_wrapper.py`

**Interfaces:**
- Consumes: `BskRunner.run(args: list[str], timeout: float | None = None) -> BskResult`
- Produces: `BskCli` with methods:
  - `select_tab(session: str, tab_id: int | str, *, json: bool = True, timeout: float = 5.0) -> BskResult`
  - `close_tab(session: str, tab_id: int | str, *, observation: str | None = None, context: str | None = None, json: bool = True, timeout: float = 5.0) -> BskResult`
  - `sync_tab(session: str, tab_id: int | str | None = None, *, json: bool = True, timeout: float = 5.0) -> BskResult`
  - `list_tabs(session: str | None = None, *, scope: str = "agent", json: bool = True, timeout: float = 5.0) -> BskResult`
  - `create_tab(session: str, url: str | None = None, *, active: bool = True, json: bool = True, timeout: float = 5.0) -> BskResult`
  - `borrow_tab(session: str, tab_id: int | str, *, json: bool = True, timeout: float = 5.0) -> BskResult`
  - `return_tab(session: str, tab_id: int | str, *, json: bool = True, timeout: float = 5.0) -> BskResult`
  - `list_sessions(*, json: bool = True, timeout: float = 10.0) -> BskResult`
  - `start_session(session_id: str | None = None, *, headless: bool | None = None, json: bool = True, timeout: float = 30.0) -> BskResult`
  - `stop_session(session_id: str, *, json: bool = False, timeout: float = 15.0) -> BskResult`
  - `get_version(*, json: bool = True, timeout: float = 5.0) -> BskResult`
  - `get_status(*, json: bool = True, timeout: float = 10.0) -> BskResult`

- [ ] **Step 1: Write the failing unit tests for `BskCli` basic methods**

Create `tests/test_cli_wrapper.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from bsk.models import BskResult
from bsk.cli import BskCli

@pytest.fixture
def mock_runner():
    runner = MagicMock()
    runner.run = AsyncMock(return_value=BskResult(exit_code=0, stdout="{}", stderr="", data={}))
    return runner

@pytest.mark.asyncio
async def test_cli_select_tab_builds_correct_args(mock_runner):
    cli = BskCli(mock_runner)
    res = await cli.select_tab("sess1", 101)
    assert res.exit_code == 0
    mock_runner.run.assert_awaited_once_with(
        ["tab", "select", "101", "--session", "sess1", "--json"],
        timeout=5.0,
    )

@pytest.mark.asyncio
async def test_cli_close_tab_builds_correct_args(mock_runner):
    cli = BskCli(mock_runner)
    await cli.close_tab("sess1", 102, observation="obs1", context="ctx1")
    mock_runner.run.assert_awaited_once_with(
        ["tab", "close", "102", "--session", "sess1", "--observation", "obs1", "--context", "ctx1", "--json"],
        timeout=5.0,
    )

@pytest.mark.asyncio
async def test_cli_sync_tab_builds_correct_args(mock_runner):
    cli = BskCli(mock_runner)
    await cli.sync_tab("sess1", tab_id=103)
    mock_runner.run.assert_awaited_once_with(
        ["sync", "--session", "sess1", "--tab-id", "103", "--json"],
        timeout=5.0,
    )

@pytest.mark.asyncio
async def test_cli_list_tabs_builds_correct_args(mock_runner):
    cli = BskCli(mock_runner)
    await cli.list_tabs("sess1", scope="agent")
    mock_runner.run.assert_awaited_once_with(
        ["tab", "list", "--scope", "agent", "--session", "sess1", "--json"],
        timeout=5.0,
    )

@pytest.mark.asyncio
async def test_cli_session_methods(mock_runner):
    cli = BskCli(mock_runner)
    await cli.list_sessions()
    mock_runner.run.assert_any_await(["session", "list", "--json"], timeout=10.0)
    await cli.stop_session("sess1")
    mock_runner.run.assert_any_await(["session", "stop", "sess1"], timeout=15.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_wrapper.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bsk.cli'`

- [ ] **Step 3: Implement `BskCli` in `astrbot_plugin_bsk_browser/bsk/cli.py`**

Implement `BskCli` with comprehensive docstrings, parameter validation, type hints, and CLI command formatting.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_wrapper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bsk/cli.py tests/test_cli_wrapper.py
git commit -m "feat(cli): implement BskCli semantic wrapper methods"
```

---

### Task 2: Implement `close_tab_safe` in `BskCli` and Attach `cli` to `BskRunner`

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/cli.py`
- Modify: `astrbot_plugin_bsk_browser/bsk/runner.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_cli_wrapper.py`

**Interfaces:**
- Consumes: `BskCli.select_tab`, `BskCli.sync_tab`, `BskCli.close_tab`
- Produces: `BskCli.close_tab_safe(session: str, tab_id: int | str, *, timeout: float = 5.0) -> BskResult`
- Produces: `BskRunner.cli: BskCli` attribute on runner instance

- [ ] **Step 1: Write unit tests for `close_tab_safe` and `runner.cli` property**

Add to `tests/test_cli_wrapper.py`:
```python
@pytest.mark.asyncio
async def test_cli_close_tab_safe_sequence(mock_runner):
    call_sequence = []
    async def mock_run(args, timeout=None):
        cmd = " ".join(args)
        call_sequence.append(cmd)
        if "sync" in cmd:
            return BskResult(exit_code=0, stdout="", stderr="", data={"observation_id": "obs-999", "context_id": "ctx-888"})
        return BskResult(exit_code=0, stdout="", stderr="", data={})

    mock_runner.run = AsyncMock(side_effect=mock_run)
    cli = BskCli(mock_runner)

    res = await cli.close_tab_safe("sess1", 105)
    assert res.exit_code == 0
    assert len(call_sequence) == 3
    assert call_sequence[0].startswith("tab select 105 --session sess1")
    assert call_sequence[1].startswith("sync --session sess1 --tab-id 105")
    assert call_sequence[2].startswith("tab close 105 --session sess1")
    assert "--observation obs-999" in call_sequence[2]
    assert "--context ctx-888" in call_sequence[2]

@pytest.mark.asyncio
async def test_cli_close_tab_safe_tolerates_select_or_sync_failure(mock_runner):
    call_sequence = []
    async def mock_run(args, timeout=None):
        cmd = " ".join(args)
        call_sequence.append(cmd)
        if "select" in cmd:
            raise Exception("select failed")
        if "sync" in cmd:
            return BskResult(exit_code=1, stdout="{}", stderr="", data={})
        return BskResult(exit_code=0, stdout="", stderr="", data={})

    mock_runner.run = AsyncMock(side_effect=mock_run)
    cli = BskCli(mock_runner)

    res = await cli.close_tab_safe("sess1", 106)
    assert res.exit_code == 0
    # Even if select fails and sync fails, close_tab is still attempted
    assert any("tab close 106" in cmd for cmd in call_sequence)

def test_runner_has_cli_instance():
    from bsk.runner import BskRunner
    runner = BskRunner()
    assert hasattr(runner, "cli")
    assert isinstance(runner.cli, BskCli)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_wrapper.py -k "close_tab_safe or runner_has_cli" -v`
Expected: FAIL

- [ ] **Step 3: Implement `close_tab_safe` in `bsk/cli.py` and attach `self.cli = BskCli(self)` in `bsk/runner.py`**

- In `bsk/cli.py`: Add `close_tab_safe` method with select -> sync -> close sequence and error fallback.
- In `bsk/runner.py`: In `BskRunner.__init__`, initialize `self.cli = BskCli(self)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_wrapper.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bsk/cli.py bsk/runner.py tests/test_cli_wrapper.py
git commit -m "feat(cli): add close_tab_safe workflow and attach BskCli to BskRunner"
```

---

### Task 3: Refactor `SessionManager` in `bsk/session.py` to Use `BskCli` and Safe Multi-Tab Closure

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/session.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_session.py`

**Interfaces:**
- Consumes: `BskCli.list_tabs`, `BskCli.close_tab_safe`, `BskCli.list_sessions`, `BskCli.stop_session`
- Produces: `SessionManager._stop_entry` closing all session tabs cleanly and eliminating raw runner calls

- [ ] **Step 1: Write/update test verifying `_stop_entry` closes all session tabs via `close_tab_safe`**

Update `tests/test_tab_lifecycle_cleanup.py` to assert that when multiple tabs exist (e.g. Tab 101 and Tab 102), `_stop_entry` executes safe close for all tabs without leaving any orphaned tab:
```python
@pytest.mark.asyncio
async def test_stop_entry_safely_closes_all_tabs():
    from unittest.mock import AsyncMock, MagicMock
    from bsk.session import SessionManager, _Entry
    from bsk.models import BskSession, BskResult

    runner = MagicMock()
    calls = []
    async def mock_run(args, timeout=None):
        cmd = " ".join(args)
        calls.append(cmd)
        if "tab list" in cmd:
            return BskResult(exit_code=0, stdout="", stderr="", data={
                "tabs": [
                    {"tab_id": 101, "title": "Baidu", "active": False},
                    {"tab_id": 102, "title": "Tieba", "active": True},
                ]
            })
        elif "sync" in cmd:
            return BskResult(exit_code=0, stdout="", stderr="", data={"observation_id": "obs-1", "context_id": "ctx-1"})
        return BskResult(exit_code=0, stdout="", stderr="", data={})

    runner.run = AsyncMock(side_effect=mock_run)
    runner.run_or_raise = AsyncMock(side_effect=mock_run)
    sm = SessionManager(runner, MagicMock())

    session = BskSession(session_id="sess_multi", agent_window_id=1)
    entry = _Entry(key="k_multi", session=session, lock=asyncio.Lock(), last_used=100.0)

    success = await sm._stop_entry(entry)
    assert success is True

    # Check that both 101 and 102 received select, sync, and close calls
    close_calls = [c for c in calls if c.startswith("tab close")]
    assert len(close_calls) >= 2
    assert any("101" in c for c in close_calls)
    assert any("102" in c for c in close_calls)
```

- [ ] **Step 2: Run test to verify current behavior vs expected**

Run: `pytest tests/test_tab_lifecycle_cleanup.py -k test_stop_entry_safely_closes_all_tabs -v`
Expected: FAIL (currently only closes `tab_list[1:]` and doesn't run `select_tab`)

- [ ] **Step 3: Refactor `SessionManager` in `bsk/session.py`**

1. In `SessionManager.__init__`:
   `self._cli = getattr(runner, "cli", None) or BskCli(runner)`
2. In `_stop_entry(self, entry)`:
   - Call `await self._cli.list_tabs(session=entry.session.session_id, scope="agent", timeout=5.0)`.
   - Extract all valid `tid` from the tabs list.
   - For every `tid` in `tabs`:
     `await self._cli.close_tab_safe(entry.session.session_id, tid, timeout=5.0)`.
   - If Agent Window has closed automatically, finish; otherwise call `self._stop_session_id(entry.session.session_id)`.
3. In `SessionManager.list_sessions`, `stop_session`, `sweep_dead_sessions`:
   Replace raw `runner.run(...)` / `runner.run_or_raise(["session", "list", ...])` calls with `self._cli.list_sessions(...)` and `self._cli.stop_session(...)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tab_lifecycle_cleanup.py -v`
Expected: PASS

- [ ] **Step 5: Run existing `test_session.py` to ensure no regressions**

Run: `pytest tests/test_session.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add bsk/session.py tests/test_tab_lifecycle_cleanup.py
git commit -m "refactor(session): use BskCli for lifecycle and safely close all tabs on stop"
```

---

### Task 4: Refactor `BskService` in `bsk/service.py` to Use `BskCli`

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py`
- Test: `astrbot_plugin_bsk_browser/tests/verify_integration.py`

**Interfaces:**
- Consumes: `BskCli.get_version`, `BskCli.get_status`, `BskCli.close_tab_safe`
- Produces: `BskService.cli: BskCli` and clean semantic calls replacing bare `runner.run`

- [ ] **Step 1: Write/update test verifying `BskService` uses `BskCli`**

Add tests to `tests/test_cli_wrapper.py`:
```python
@pytest.mark.asyncio
async def test_service_ping_and_status_use_cli(mock_runner):
    from bsk.service import BskService
    service = BskService(settings=MagicMock(), runner=mock_runner, logger=MagicMock())
    await service.ping()
    mock_runner.run.assert_any_await(["version", "--json"], timeout=5.0)
    await service.status()
    mock_runner.run.assert_any_await(["status", "--json"], timeout=10.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_wrapper.py -k test_service_ping_and_status_use_cli -v`
Expected: FAIL

- [ ] **Step 3: Update `BskService` in `bsk/service.py`**

1. In `BskService.__init__`:
   Expose `self.cli = getattr(self.runner, "cli", None) or BskCli(self.runner)`.
2. In `ping()`:
   Replace raw `self.runner.run_or_raise(["version", "--json"])` with `await self.cli.get_version()`.
3. In `status()`:
   Replace raw `self.runner.run_or_raise(["status", "--json"])` with `await self.cli.get_status()`.
4. In `tabs(action="close", tab_id=...)`:
   Ensure `close` action calls `close_tab_safe` (or uses `cli.close_tab_safe`) to ensure active focus and fresh credentials before issuing close.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_cli_wrapper.py tests/test_tab_lifecycle_cleanup.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bsk/service.py tests/test_cli_wrapper.py
git commit -m "refactor(service): use BskCli for ping, status, and tab close delegation"
```

---

### Task 5: Update SKILL Documentation and Run Full Verification

**Files:**
- Modify: `astrbot_plugin_bsk_browser/skills/bsk-browser/SKILL.md`
- Test: Full pytest suite (`pytest -v`)
- Test: Local `./bsk` integration check

**Interfaces:**
- Consumes: All completed tasks
- Produces: Updated, accurate documentation complying with `AGENTS.md` and clean passing test suite

- [ ] **Step 1: Check and update `skills/bsk-browser/SKILL.md`**

Ensure `skills/bsk-browser/SKILL.md` concisely and accurately documents tab lifecycle and closing recommendations:
- Mention that tabs are safely managed and cleaned up upon session end.
- Mention that when browsing results, the user/robot can explicitly close tabs using `bsk_tabs(action="close", tab_id=...)`.

- [ ] **Step 2: Run documentation test**

Run: `pytest tests/test_skills_doc.py -v`
Expected: PASS

- [ ] **Step 3: Run full plugin test suite**

Run: `pytest -v`
Expected: All tests PASS.

- [ ] **Step 4: Run integration test against local `./bsk`**

Execute verification script against the live daemon and browser instance to confirm `close_tab_safe` and multi-tab cleanup work in real Chrome.

- [ ] **Step 5: Commit**

```bash
git add skills/bsk-browser/SKILL.md
git commit -m "docs(skills): update bsk-browser skill for safe tab lifecycle and cleanup"
```
