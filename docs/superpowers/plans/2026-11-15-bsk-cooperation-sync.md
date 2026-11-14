# astrbot_plugin_bsk_browser 协同控制同步机制（Cooperation Sync）与交互自愈实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 `astrbot_plugin_bsk_browser` 对 BrowserSkill 协同控制策略（Cooperation Policy）的支持，在 `bsk_session` 中对齐暴露 `sync` 与 `open` 动作，并在 `bsk_interact` 中建立针对 `cooperation_sync_required` 的自动同步自愈重试与显式回显机制。

**Architecture:** 在 `bsk/errors.py` 精准映射 `cooperation_sync_required`；在 `bsk/tools.py` 扩充 `bsk_session` 支持 `sync` 和 `open`（含 `url` 校验）；在 `bsk/service.py` 实现 `sync_session` 与 `open_session`，并在 `interact` 中对 `cooperation_sync_required` 自动执行一次 `sync` 并在 `effect_state != "unknown"` 时安全重试；在 `main.py` 路由对应动作，并在回执中向大模型显式提示已执行后台补救及后续操作建议。

**Tech Stack:** Python 3.10+, `unittest`, AstrBot Plugin Framework, BrowserSkill CLI (`bsk`)

**Spec:** [docs/superpowers/specs/2026-11-15-bsk-cooperation-sync-design.md](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-bsk-cooperation-sync-design.md)

## Global Constraints

- 保持 8 个新工具与旧版兼容工具的既有参数 schema 完全向后兼容；
- `sync` 自愈补救重试严格限制为最多 1 次，严禁无限重试；
- 若交互错误包含 `effect_state == "unknown"`，绝对禁止重试写入操作；
- 自动 `sync` 补救重试成功后，必须在返回文本中显式附带给大模型的提示附注；
- 使用 Python 标准库 `unittest` 编写单元测试与集成测试，测试环境零网络依赖。

## Review Focus

- **不确定态拦截 (`effect_state == "unknown"`)**：当报错为 `cooperation_sync_required` 但其附带 `effect_state: "unknown"` 时，禁止重试，直接抛出 `BskOutcomeUnknown`；
- **重试仍失败即止**：自动补救 `sync` 后若第二次交互依然抛出 `cooperation_sync_required`，必须停止重试并抛出异常，杜绝循环；
- **自愈双重标记叠加**：单次交互若同时发生 `auto_synced` 与 `auto_scrolled`，两条提示附注必须整洁并存，不发生文本冲突；
- **`open` 动作缺少 URL 校验**：调用 `bsk_session(action="open")` 若未传 `url` 或为空串，需在参数校验阶段被拦截，返回清晰提示；
- **会话失效时调用 `sync`**：对已停止或不存在的会话调用 `sync` 时，走既有的 `SessionManager` 自动重建或 `BskSessionGone` 流程，不能抛出未捕获异常。

---

### Task 1: 错误分类识别 `cooperation_sync_required` (`bsk/errors.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/errors.py:331-350`
- Test: `astrbot_plugin_bsk_browser/tests/test_errors.py`

**Interfaces:**
- Consumes: `code="permission_denied"`, `reason="cooperation_sync_required"`
- Produces: `BskError` with `friendly="当前页面控制权未同步或已失效，请先调用 bsk_session(action='sync') 同步页面控制权后再操作。"`

- [ ] **Step 1: 编写错误细分的失败单元测试**

在 `astrbot_plugin_bsk_browser/tests/test_errors.py` 中增加用例：
```python
def test_cooperation_sync_required_friendly(self) -> None:
    err = errors.classify(
        exit_code=1,
        code=errors.CODE_PERMISSION_DENIED,
        message="This action requires the context returned by the latest cooperate sync",
        reason="cooperation_sync_required",
    )
    self.assertIn("页面控制权未同步或已失效", err.friendly)
    self.assertIn("bsk_session(action='sync')", err.friendly)
    self.assertEqual(err.reason, "cooperation_sync_required")
```

- [ ] **Step 2: 运行测试验证其失败**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_errors.py`
预期：FAIL（返回泛化的 `操作被浏览器权限策略拒绝（原因：cooperation_sync_required）。`）

- [ ] **Step 3: 在 `bsk/errors.py` 的 `classify` 中添加 `cooperation_sync_required` 分支**

在 `bsk/errors.py` 的 `code == CODE_PERMISSION_DENIED` 分支中添加：
```python
elif reason == "cooperation_sync_required":
    friendly = "当前页面控制权未同步或已失效，请先调用 bsk_session(action='sync') 同步页面控制权后再操作。"
```

- [ ] **Step 4: 运行测试验证其通过**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_errors.py`
预期：PASS

- [ ] **Step 5: 提交更改**

```bash
git add bsk/errors.py tests/test_errors.py
git commit -m "feat(errors): add cooperation_sync_required friendly message"
```

---

### Task 2: 工具层支持 `bsk_session` 的 `sync` 与 `open` 动作校验 (`bsk/tools.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/tools.py:120, 553-568, 2000-2020`
- Test: `astrbot_plugin_bsk_browser/tests/test_tools.py`

**Interfaces:**
- Consumes: raw arguments `action="sync"`, `action="open"`, `url="..."`
- Produces: `TOOL_ACTIONS["bsk_session"] = ("start", "stop", "list", "sync", "open")`, `TOOL_SCHEMAS["bsk_session"]` schema with `url`, validated options

- [ ] **Step 1: 编写 `sync` 与 `open` 动作校验的失败单元测试**

在 `astrbot_plugin_bsk_browser/tests/test_tools.py` 中添加用例：
```python
def test_session_sync_validation_success(self) -> None:
    res = tools.validate("bsk_session", {"action": "sync"})
    self.assertEqual(res["action"], "sync")

def test_session_open_requires_url(self) -> None:
    with self.assertRaises(tools.BskToolError) as ctx:
        tools.validate("bsk_session", {"action": "open"})
    self.assertIn("url", str(ctx.exception))

def test_session_open_validation_success(self) -> None:
    res = tools.validate("bsk_session", {"action": "open", "url": "https://example.com"})
    self.assertEqual(res["action"], "open")
    self.assertEqual(res["url"], "https://example.com")
```

- [ ] **Step 2: 运行测试验证其失败**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_tools.py`
预期：FAIL（`sync` 与 `open` 不是 `bsk_session` 的合法 action）

- [ ] **Step 3: 更新 `bsk/tools.py` 中的 `TOOL_ACTIONS`、`TOOL_SCHEMAS` 与 `_validate_session`**

1. 将 `TOOL_ACTIONS["bsk_session"]` 扩展为 `("start", "stop", "list", "sync", "open")`；
2. 在 `TOOL_SCHEMAS["bsk_session"]` 的 `properties` 中增加 `url` 参数描述（类型 string，用于 `action="open"`）；
3. 在 `_validate_session` 中增加对 `sync` 和 `open` 的参数校验（`open` 要求 `url` 必须是非空有效 URL/字符串）。

- [ ] **Step 4: 运行测试验证其通过**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_tools.py`
预期：PASS

- [ ] **Step 5: 提交更改**

```bash
git add bsk/tools.py tests/test_tools.py
git commit -m "feat(tools): add sync and open actions to bsk_session"
```

---

### Task 3: 服务层实现 `sync_session` 与 `open_session` (`bsk/service.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_service_sync.py`

**Interfaces:**
- Consumes: `SessionManager.execute`
- Produces: `sync_session(self, key: str, *, tab_id: int | None = None, ...) -> PageObservation`, `open_session(self, key: str, url: str, ...) -> PageObservation`

- [ ] **Step 1: 编写 `sync_session` 与 `open_session` 的失败单元测试**

新建 `astrbot_plugin_bsk_browser/tests/test_service_sync.py`：
```python
import unittest
from unittest.mock import AsyncMock, MagicMock
from bsk.service import BskService
from bsk.models import PageObservation

class TestServiceSync(unittest.IsolatedAsyncioTestCase):
    async def test_sync_session_calls_bsk_sync(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._with_tab_id = lambda args, tid: args
        service._timeout = lambda builtin: builtin
        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(return_value=MagicMock(data={"text": "Page content", "elements": []}))
        service.sessions.stats = MagicMock(return_value={"counters": {}})

        obs = await service.sync_session("s1")
        self.assertIsInstance(obs, PageObservation)
        service.sessions.execute.assert_called_once()
        # 验证传入的命令是 sync
        builder = service.sessions.execute.call_args[0][1]
        self.assertEqual(builder("sid")[:1], ["sync"])
```

- [ ] **Step 2: 运行测试验证其失败**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_service_sync.py`
预期：FAIL（`BskService` 没有 `sync_session` 方法）

- [ ] **Step 3: 在 `bsk/service.py` 中实现 `sync_session` 与 `open_session`**

1. `sync_session(self, key: str, *, tab_id: int | None = None, wait_for: str = "", wait_not: str = "", timeout_ms: int | None = None) -> PageObservation`：
   构造 `["sync"]` 参数，加上可选的 `--wait-for`、`--wait-not`、`--timeout-ms`，调用 `self.sessions.execute(session_key, ..., allow_uncertain=True)`，调用 `parse_observation` 并返回。
2. `open_session(self, key: str, url: str, *, browser: str | None = None, timeout_ms: int | None = None) -> PageObservation`：
   构造 `["open", url]` 参数，调用 `self.sessions.execute(session_key, ..., allow_uncertain=False)`，调用 `parse_observation` 并返回。

- [ ] **Step 4: 运行测试验证其通过**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_service_sync.py`
预期：PASS

- [ ] **Step 5: 提交更改**

```bash
git add bsk/service.py tests/test_service_sync.py
git commit -m "feat(service): implement sync_session and open_session"
```

---

### Task 4: 服务层交互捕获 `cooperation_sync_required` 并自愈重试 (`bsk/service.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py:2520-2560`
- Test: `astrbot_plugin_bsk_browser/tests/test_service_sync.py`

**Interfaces:**
- Consumes: `BskError` with `reason="cooperation_sync_required"`, `self.sync_session`
- Produces: `interact(...)` with auto-sync retry and `out["auto_synced"] = True`

- [ ] **Step 1: 编写 `interact` 自愈重试与不确定态拦截的失败单元测试**

在 `astrbot_plugin_bsk_browser/tests/test_service_sync.py` 中添加测试：
```python
    async def test_interact_auto_sync_on_cooperation_sync_required(self) -> None:
        service = BskService.__new__(BskService)
        service._resolve_key = MagicMock(return_value="s1")
        service._build_interact_args = MagicMock(return_value=(["fill", "@e1"], False))
        service._interact_timeout_builtin = MagicMock(return_value=30.0)
        service._timeout = lambda b: b
        service._logger = MagicMock()
        service._with_tab_id = lambda args, tid: args
        service._session_field = lambda k: "s1"
        service._payload_tab_id = lambda d: None
        service._interact_result = MagicMock(return_value={"value": "gtnh"})
        service.sync_session = AsyncMock()

        # 模拟第一次报 cooperation_sync_required，第二次成功
        from bsk.errors import BskError
        err = BskError("sync required", reason="cooperation_sync_required")
        success_res = MagicMock(data={"status": "ok"})
        service.sessions = MagicMock()
        service.sessions.execute = AsyncMock(side_effect=[err, success_res])

        res = await service.interact("s1", "fill", target="@e1", value="gtnh")
        self.assertTrue(res["auto_synced"])
        service.sync_session.assert_called_once_with("s1", tab_id=None)
        self.assertEqual(service.sessions.execute.call_count, 2)

    async def test_interact_unknown_effect_does_not_auto_sync(self) -> None:
        # 当 reason 是 outcome_unknown 相关时，不触发 auto_sync
        ...
```

- [ ] **Step 2: 运行测试验证其失败**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_service_sync.py`
预期：FAIL（`interact` 尚未捕获 `cooperation_sync_required`）

- [ ] **Step 3: 在 `bsk/service.py` 的 `interact` 中增加自动 `sync` 补救重试**

在 `interact` 的 `try-except` 块中捕获 `cooperation_sync_required`：
1. 记录日志：`[bsk.service] 页面交互触发 cooperation_sync_required，尝试自动 sync 后重试`；
2. 调用 `await self.sync_session(session_key, tab_id=tab_id)`；
3. 再次执行原交互指令；
4. 成功后设置 `auto_synced = True`；
5. 在 `out` 字典中加入 `"auto_synced": auto_synced`。

- [ ] **Step 4: 运行测试验证其通过**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_service_sync.py`
预期：PASS

- [ ] **Step 5: 提交更改**

```bash
git add bsk/service.py tests/test_service_sync.py
git commit -m "feat(service): auto-sync and retry on cooperation_sync_required in interact"
```

---

### Task 5: 调度层支持 `sync`/`open` 路由并显式回显补救提示 (`main.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/main.py:993-1045, 1260-1280, 1838-1850`
- Test: `astrbot_plugin_bsk_browser/tests/test_main_sync.py`

**Interfaces:**
- Consumes: `bsk_session` with `sync`/`open`, `ActionResult.auto_synced`
- Produces: `_run_session` routes `sync` and `open`, `_run_interact` renders `auto_synced` notice, updated tool docstrings

- [ ] **Step 1: 编写 `main.py` 路由与显式补救附注的失败测试**

新建 `astrbot_plugin_bsk_browser/tests/test_main_sync.py`：
```python
import unittest
from unittest.mock import AsyncMock, MagicMock
from astrbot_test_doubles import make_context, FakeEvent
from main import BskBrowserPlugin
from bsk.models import PageObservation

class TestMainSync(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.plugin = BskBrowserPlugin(make_context(), config={"admin_only": False})
        self.plugin.service = MagicMock()

    async def test_bsk_session_sync_dispatched(self) -> None:
        obs = PageObservation(url="https://example.com", title="Test", text="Sample", elements=[])
        self.plugin.service.sync_session = AsyncMock(return_value=obs)
        self.plugin.service.render_page = MagicMock(return_value="Rendered VOM")
        
        event = FakeEvent(message="test")
        res = await self.plugin.bsk_session(event, action="sync")
        self.assertIn("Rendered VOM", res)
        self.plugin.service.sync_session.assert_called_once()

    async def test_interact_renders_auto_synced_notice(self) -> None:
        self.plugin.service.interact = AsyncMock(return_value={
            "session": "s1", "action": "click", "auto_synced": True, "auto_scrolled": False, "target": "@e1"
        })
        event = FakeEvent(message="test")
        res = await self.plugin.bsk_interact(event, action="click", target="@e1")
        self.assertIn("已在后台自动执行 sync 补救重试", res)
        self.assertIn("优先主动调用 bsk_session(action='sync')", res)
```

- [ ] **Step 2: 运行测试验证其失败**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_main_sync.py`
预期：FAIL（`_run_session` 缺少 `sync` 分支，`bsk_interact` 未渲染 `auto_synced` 附注）

- [ ] **Step 3: 更新 `main.py` 的路由、附注渲染与工具 Docstrings**

1. 在 `_run_session` 中添加：
   - `action == "sync"`: 调用 `service.sync_session` 并 `render_page` 返回；
   - `action == "open"`: 调用 `service.open_session` 并 `render_page` 返回；
2. 在 `_run_interact` / `_render_action_result` 中检测 `result.get("auto_synced")`：
   若为 True，追加回显说明：
   `（提示：检测到页面控制上下文未同步，已在后台自动执行 sync 补救重试；注意：后续在页面跳转或导航后，请优先主动调用 bsk_session(action='sync') 同步页面。）`
3. 更新 `bsk_session`、`bsk_page`、`bsk_interact` 的函数 docstring，明确写明操作指引。

- [ ] **Step 4: 运行测试验证其通过**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_main_sync.py`
预期：PASS

- [ ] **Step 5: 提交更改**

```bash
git add main.py tests/test_main_sync.py
git commit -m "feat(main): dispatch session sync/open and render auto-synced notification"
```

---

### Task 6: 完整业务链路集成测试与全局回归验证

**Files:**
- Create: `astrbot_plugin_bsk_browser/tests/test_integration_sync.py`

**Interfaces:**
- Validates end-to-end tool execution chain for `bsk_session(open)` -> `bsk_interact(fill)` and `navigate` -> `observe` -> `fill` (with auto-sync recovery and notice).

- [ ] **Step 1: 编写集成验证测试用例**

在 `astrbot_plugin_bsk_browser/tests/test_integration_sync.py` 中编写复合场景测试：
1. 场景 1：模型使用标准链路 `bsk_session(open)` 直接打开并获取元素，然后成功 `fill` 与 `click`；
2. 场景 2：模型像用户日志那样 `start` -> `navigate` -> `observe` -> `fill`（未显式 sync），验证触发自动 `sync` 自愈补救重试，并正确在最终回复中返回提示附注；
3. 场景 3：验证叠加自愈（同时触发 `cooperation_sync_required` 与 `element_not_visible`），确保先同步再滚动最终成功，附注包含两条提示。

- [ ] **Step 2: 运行集成测试**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_integration_sync.py`
预期：PASS

- [ ] **Step 3: 运行全量测试套件验证 0 回归**

运行：`python3 -m unittest discover -s /run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/tests`
预期：全部通过（860+ 测试全部 PASS，0 失败）。

- [ ] **Step 4: 提交集成测试与收尾**

```bash
git add tests/test_integration_sync.py
git commit -m "test: add integration test suite for cooperation sync and resilient recovery"
```
