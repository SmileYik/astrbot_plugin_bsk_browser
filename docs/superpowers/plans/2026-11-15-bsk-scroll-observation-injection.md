# 无目标滚动与操作观察令牌透明注入实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 astrbot_plugin_bsk_browser 中实现会话级 observation_id 缓存、无目标 wheel/press 操作透明注入 --observation 参数，并在遇到 observation_required、cooperation_sync_required 和 control_context_invalid 时自动执行 sync 补偿重试，彻底解决 Bot 无法滚动页面与交互权限受阻的问题。

**Architecture:** 在 BskService 中维护会话级的单次有效 observation_id 字典，扩展 INTERACT_SPECS 命令行规则；在 interact() 与 navigate() 中引入前置注入与响应式自愈重试机制，生命周期结束或发生页面导航跳转时主动清理缓存。

**Tech Stack:** Python 3.10+, asyncio, unittest.IsolatedAsyncioTestCase, AstrBot Plugin SDK.

**Spec:** `astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-bsk-scroll-observation-injection-design.md`

## Global Constraints
- 仅限修改 `astrbot_plugin_bsk_browser/` 目录代码；
- 日志输出严格遵循 `AGENTS.md`，使用 AstrBot 注入的日志系统以 DEBUG 等级记录 bsk 命令输入输出及工具调用信息；
- 保持外部工具 Schema 接口与现有 919 个单元测试向后兼容；
- 绝不在 `SessionManager`（`bsk/session.py`）中侵入业务载荷逻辑。

## Review Focus
- 连续多次无目标滚动：第一次滚动消耗令牌后，第二次无目标滚动必须能够自动触发 sync 补偿重试并成功执行；
- 带 target 的 wheel 操作：当传入 target（如 `@e1` 或 CSS 选择器）时，按 DOM 定向动作执行，绝不强制依赖 observation_id；
- 页面导航跳转后令牌清理：navigate 或 history 成功后旧令牌立即失效，防止旧页面令牌导致后续操作鉴权崩溃；
- 输入文本后立即无目标回车：捕获 `control_context_invalid` 并完成自动同步重试；
- 首次 navigate 遇到权限拒绝：捕获后自动 sync 并携带 `--observation` 重试成功。

---

### Task 1: PageObservation 数据模型扩展

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/models.py:190-250`
- Test: `astrbot_plugin_bsk_browser/tests/test_observation_model.py`

**Interfaces:**
- Produces: `PageObservation.observation_id: str`

- [ ] **Step 1: 编写失败的单元测试**

在 `astrbot_plugin_bsk_browser/tests/test_observation_model.py` 中编写测试：
```python
import unittest
from astrbot_plugin_bsk_browser.bsk.models import PageObservation

class TestPageObservationModel(unittest.TestCase):
    def test_observation_id_extracted_from_top_level(self) -> None:
        raw = {"observation_id": "uuid-obs-1", "tab_id": 1, "text": "hello"}
        obs = PageObservation.from_json(raw)
        self.assertEqual(obs.observation_id, "uuid-obs-1")

    def test_observation_id_extracted_from_obs_alias(self) -> None:
        raw = {"obs": "o15", "tab_id": 1, "text": "hello"}
        obs = PageObservation.from_json(raw)
        self.assertEqual(obs.observation_id, "o15")

    def test_observation_id_extracted_from_nested_dict(self) -> None:
        raw = {"observation": {"observation_id": "uuid-obs-2"}, "tab_id": 1, "text": "hello"}
        obs = PageObservation.from_json(raw)
        self.assertEqual(obs.observation_id, "uuid-obs-2")

    def test_observation_id_defaults_to_empty(self) -> None:
        raw = {"tab_id": 1, "text": "hello"}
        obs = PageObservation.from_json(raw)
        self.assertEqual(obs.observation_id, "")
```

- [ ] **Step 2: 运行测试验证失败**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_observation_model.py`
预期：FAIL（`AttributeError: 'PageObservation' object has no attribute 'observation_id'`）

- [ ] **Step 3: 实现 PageObservation.observation_id 字段及解析**

在 `astrbot_plugin_bsk_browser/bsk/models.py` 中：
1. 给 `PageObservation` 增加 `observation_id: str = ""` 字段；
2. 在 `PageObservation.from_json` 中增加解析逻辑：
   ```python
   observation_id = _as_str(
       raw.get("observation_id")
       or raw.get("obs")
       or (raw.get("observation", {}) if isinstance(raw.get("observation"), dict) else {}).get("observation_id")
   )
   ```
   并将 `observation_id=observation_id` 传给构造器。

- [ ] **Step 4: 运行测试验证通过**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_observation_model.py`
预期：PASS (4 tests)

- [ ] **Step 5: 提交**

```bash
git add astrbot_plugin_bsk_browser/bsk/models.py astrbot_plugin_bsk_browser/tests/test_observation_model.py
git commit -m "feat(bsk): add observation_id field to PageObservation model"
```

---

### Task 2: 命令行规范与参数构造扩展 (INTERACT_SPECS & _build_interact_args)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py:3460-3500,2870-2890`
- Test: `astrbot_plugin_bsk_browser/tests/test_interact_args.py`

**Interfaces:**
- Consumes: `PageObservation`
- Produces: 支持 `--observation` 标志与 `target` 位置参数的 `_build_interact_args`

- [ ] **Step 1: 编写失败的单元测试**

在 `astrbot_plugin_bsk_browser/tests/test_interact_args.py` 中编写测试：
```python
import unittest
from astrbot_plugin_bsk_browser.bsk.service import BskService

class TestInteractArgsBuilding(unittest.TestCase):
    def test_wheel_with_observation_id(self) -> None:
        argv, readonly = BskService._build_interact_args(
            "wheel", {"delta_x": 0, "delta_y": 500, "observation_id": "uuid-obs-1"}
        )
        self.assertTrue(readonly)
        self.assertIn("--observation", argv)
        idx = argv.index("--observation")
        self.assertEqual(argv[idx + 1], "uuid-obs-1")
        self.assertIn("--delta-y", argv)

    def test_wheel_with_target_and_no_observation(self) -> None:
        argv, readonly = BskService._build_interact_args(
            "wheel", {"target": "@e1", "delta_x": 0, "delta_y": 500}
        )
        self.assertTrue(readonly)
        self.assertEqual(argv[0], "wheel")
        self.assertEqual(argv[1], "@e1")
        self.assertNotIn("--observation", argv)

    def test_press_with_observation_id(self) -> None:
        argv, readonly = BskService._build_interact_args(
            "press", {"key": "Enter", "observation_id": "uuid-obs-2"}
        )
        self.assertFalse(readonly)
        self.assertEqual(argv[0], "press")
        self.assertEqual(argv[1], "Enter")
        self.assertIn("--observation", argv)
        idx = argv.index("--observation")
        self.assertEqual(argv[idx + 1], "uuid-obs-2")
```

- [ ] **Step 2: 运行测试验证失败**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_interact_args.py`
预期：FAIL（`--observation` 未在 argv 中生成）

- [ ] **Step 3: 修改 INTERACT_SPECS 与参数构造逻辑**

在 `astrbot_plugin_bsk_browser/bsk/service.py` 中：
1. 在 `INTERACT_SPECS["wheel"]` 的 `value_flags` 中追加 `("observation_id", "--observation")`；
2. 在 `INTERACT_SPECS["press"]` 的 `value_flags` 中追加 `("observation_id", "--observation")`；
3. 检查并确保当 `target` 存在时，`spec.allows_target` 正确将 `target` 加入 `argv`。

- [ ] **Step 4: 运行测试验证通过**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_interact_args.py`
预期：PASS (3 tests)

- [ ] **Step 5: 提交**

```bash
git add astrbot_plugin_bsk_browser/bsk/service.py astrbot_plugin_bsk_browser/tests/test_interact_args.py
git commit -m "feat(bsk): support observation_id and target in wheel and press interact specs"
```

---

### Task 3: BskService 观察令牌缓存与生命周期管理

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py:1850-1960,570-620,1300-1330`
- Test: `astrbot_plugin_bsk_browser/tests/test_service_observation_cache.py`

**Interfaces:**
- Produces: `service._session_observations: dict[str, str]` 及其自动同步和失效逻辑

- [ ] **Step 1: 编写失败的单元测试**

在 `astrbot_plugin_bsk_browser/tests/test_service_observation_cache.py` 中编写测试：
```python
import unittest
from unittest.mock import AsyncMock, MagicMock
from astrbot_plugin_bsk_browser.bsk.models import BskResult
from astrbot_plugin_bsk_browser.bsk.service import BskService

class TestServiceObservationCache(unittest.IsolatedAsyncioTestCase):
    async def test_sync_and_open_cache_observation_id(self) -> None:
        service = BskService(runner=MagicMock())
        service.sessions = MagicMock()
        
        # 模拟 sync_session 返回 observation_id
        service.sessions.execute = AsyncMock(return_value=BskResult(
            exit_code=0, stdout="", stderr="",
            data={"observation_id": "obs-sync-1", "tab_id": 1, "vom": "@vom 1\nL1 page"}
        ))
        obs = await service.sync_session("s1")
        self.assertEqual(obs.observation_id, "obs-sync-1")
        self.assertEqual(service._session_observations.get("s1"), "obs-sync-1")

        # 模拟 open_session 返回 obs 别名
        service.sessions.execute = AsyncMock(return_value=BskResult(
            exit_code=0, stdout="", stderr="",
            data={"obs": "o20", "tab_id": 1, "vom": "@vom 1\nL1 page"}
        ))
        obs2 = await service.open_session("s1", "https://example.com")
        self.assertEqual(obs2.observation_id, "o20")
        self.assertEqual(service._session_observations.get("s1"), "o20")

    async def test_navigate_and_history_clear_observation_cache(self) -> None:
        service = BskService(runner=MagicMock())
        service.sessions = MagicMock()
        service._session_observations["s1"] = "obs-old"
        
        service.sessions.execute = AsyncMock(return_value=BskResult(
            exit_code=0, stdout="", stderr="", data={"url": "https://example.com/2"}
        ))
        service.observe = AsyncMock()
        
        await service.navigate("s1", "https://example.com/2")
        self.assertNotIn("s1", service._session_observations)

    async def test_release_clears_observation_cache(self) -> None:
        service = BskService(runner=MagicMock())
        service.sessions = MagicMock()
        service.sessions.release = AsyncMock(return_value=True)
        service._session_observations["s1"] = "obs-1"
        
        await service.release_session("s1")
        self.assertNotIn("s1", service._session_observations)
```

- [ ] **Step 2: 运行测试验证失败**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_service_observation_cache.py`
预期：FAIL（`AttributeError: 'BskService' object has no attribute '_session_observations'`）

- [ ] **Step 3: 实现 BskService 中的缓存生命周期管理**

在 `astrbot_plugin_bsk_browser/bsk/service.py` 中：
1. `__init__` 中初始化 `self._session_observations: dict[str, str] = {}`；
2. 在 `sync_session` 中，解析 `result.data` 顶层的 `observation_id` 或 `obs`，若非空存入 `self._session_observations[session_key]`，并赋给 `observation.observation_id`；
3. 在 `open_session` 中，同样保存并在返回对象中设置 `observation.observation_id`；
4. 在 `navigate` 和 `history` 成功执行后，调用 `self._session_observations.pop(session_key, None)` 清理旧令牌；
5. 在 `release_session` 和 `release_all` 中清理对应缓存。

- [ ] **Step 4: 运行测试验证通过**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_service_observation_cache.py`
预期：PASS (3 tests)

- [ ] **Step 5: 提交**

```bash
git add astrbot_plugin_bsk_browser/bsk/service.py astrbot_plugin_bsk_browser/tests/test_service_observation_cache.py
git commit -m "feat(bsk): manage session observation_id cache lifecycle in BskService"
```

---

### Task 4: `interact` 无目标交互前置注入与自愈补偿重试

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py:2603-2750`
- Test: `astrbot_plugin_bsk_browser/tests/test_interact_observation_retry.py`

**Interfaces:**
- Consumes: `_session_observations` 缓存
- Produces: 自动注入 `--observation` 并自愈 `observation_required`、`cooperation_sync_required`、`control_context_invalid` 的 `interact` 方法

- [ ] **Step 1: 编写失败的单元测试**

在 `astrbot_plugin_bsk_browser/tests/test_interact_observation_retry.py` 中编写测试：
```python
import unittest
from unittest.mock import AsyncMock, MagicMock
from astrbot_plugin_bsk_browser.bsk.errors import BskError
from astrbot_plugin_bsk_browser.bsk.models import BskResult, PageObservation
from astrbot_plugin_bsk_browser.bsk.service import BskService

class TestInteractObservationRetry(unittest.IsolatedAsyncioTestCase):
    async def test_wheel_untargeted_pre_injects_and_pops_cached_token(self) -> None:
        service = BskService(runner=MagicMock())
        service.sessions = MagicMock()
        service._session_observations["s1"] = "obs-cached-1"
        
        executed_argv = []
        async def mock_execute(key, builder, **kwargs):
            argv = await builder("sid1") if callable(builder) else builder("sid1")
            executed_argv.append(argv)
            return BskResult(exit_code=0, stdout="", stderr="", data={"delta_y": 500})

        service.sessions.execute = mock_execute
        res = await service.interact("s1", "wheel", delta_y=500)
        
        self.assertIn("--observation", executed_argv[0])
        idx = executed_argv[0].index("--observation")
        self.assertEqual(executed_argv[0][idx + 1], "obs-cached-1")
        self.assertNotIn("s1", service._session_observations)
        self.assertFalse(res.get("auto_synced"))

    async def test_wheel_recovers_from_observation_required(self) -> None:
        service = BskService(runner=MagicMock())
        service.sessions = MagicMock()
        # 缓存为空，初次不带 token
        
        call_count = 0
        executed_argv = []
        async def mock_execute(key, builder, **kwargs):
            nonlocal call_count
            call_count += 1
            argv = builder("sid1")
            executed_argv.append(argv)
            if call_count == 1:
                err = BskError("observation required", code="permission_denied")
                err.reason = "observation_required"
                err.effect_state = "none"
                raise err
            return BskResult(exit_code=0, stdout="", stderr="", data={"delta_y": 500})

        service.sessions.execute = mock_execute
        service.sync_session = AsyncMock(return_value=PageObservation(observation_id="obs-fresh-2"))
        
        res = await service.interact("s1", "wheel", delta_y=500)
        
        self.assertEqual(call_count, 2)
        self.assertIn("--observation", executed_argv[1])
        idx = executed_argv[1].index("--observation")
        self.assertEqual(executed_argv[1][idx + 1], "obs-fresh-2")
        self.assertTrue(res.get("auto_synced"))
        self.assertNotIn("s1", service._session_observations)

    async def test_press_recovers_from_control_context_invalid(self) -> None:
        service = BskService(runner=MagicMock())
        service.sessions = MagicMock()
        
        call_count = 0
        executed_argv = []
        async def mock_execute(key, builder, **kwargs):
            nonlocal call_count
            call_count += 1
            argv = builder("sid1")
            executed_argv.append(argv)
            if call_count == 1:
                err = BskError("focus changed", code="permission_denied")
                err.reason = "control_context_invalid"
                err.effect_state = "none"
                raise err
            return BskResult(exit_code=0, stdout="", stderr="", data={"key": "Enter"})

        service.sessions.execute = mock_execute
        service.sync_session = AsyncMock(return_value=PageObservation(observation_id="obs-fresh-3"))
        
        res = await service.interact("s1", "press", press_key="Enter")
        
        self.assertEqual(call_count, 2)
        self.assertIn("--observation", executed_argv[1])
        idx = executed_argv[1].index("--observation")
        self.assertEqual(executed_argv[1][idx + 1], "obs-fresh-3")
        self.assertTrue(res.get("auto_synced"))
```

- [ ] **Step 2: 运行测试验证失败**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_interact_observation_retry.py`
预期：FAIL（执行初次未注入 `--observation` 或未捕获重试）

- [ ] **Step 3: 在 interact 中实现前置注入与自愈补偿重试**

在 `astrbot_plugin_bsk_browser/bsk/service.py` 的 `interact` 方法中：
1. **前置注入与消耗**：
   在执行 `_build_interact_args` 前：
   ```python
   if action in ("wheel", "press") and not target and session_key in self._session_observations:
       opts["observation_id"] = self._session_observations.pop(session_key, None)
       argv, readonly = self._build_interact_args(action, opts)
   ```
2. **异常捕获与重试升级**：
   捕获条件改为：
   ```python
   reason = getattr(exc, "reason", "")
   effect_state = getattr(exc, "effect_state", "")
   if reason in ("cooperation_sync_required", "observation_required", "control_context_invalid") and effect_state != "unknown":
       self._logger.info("检测到页面控制上下文或观察令牌需同步 (%s)，执行 sync_session 补救", reason)
       obs = await self.sync_session(session_key, tab_id=tab_id)
       auto_synced = True

       is_ref = target.startswith("@") or (target.lower().startswith("e") and target[1:].isdigit())
       if is_ref:
           rendered_vom = self.render_page(obs)
           from .errors import BskUserError
           raise BskUserError(...)
       
       if action in ("wheel", "press") and not target:
           opts["observation_id"] = obs.observation_id
           self._session_observations.pop(session_key, None)
           argv, readonly = self._build_interact_args(action, opts)

       try:
           result = await _run_action()
       except BskError as retry_exc:
           ...
   ```

- [ ] **Step 4: 运行测试验证通过**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_interact_observation_retry.py`
预期：PASS (3 tests)

- [ ] **Step 5: 提交**

```bash
git add astrbot_plugin_bsk_browser/bsk/service.py astrbot_plugin_bsk_browser/tests/test_interact_observation_retry.py
git commit -m "feat(bsk): pre-inject and auto-recover observation_id in interact wheel and press"
```

---

### Task 5: `navigate` 启动未同步自愈重试与端到端回归

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py:570-600`
- Test: `astrbot_plugin_bsk_browser/tests/test_navigate_resilience.py`

**Interfaces:**
- Produces: 遇到初始权限受阻时自动 sync 并带 `--observation` 成功重试的 `navigate` 方法

- [ ] **Step 1: 编写失败的单元测试**

在 `astrbot_plugin_bsk_browser/tests/test_navigate_resilience.py` 中编写测试：
```python
import unittest
from unittest.mock import AsyncMock, MagicMock
from astrbot_plugin_bsk_browser.bsk.errors import BskError
from astrbot_plugin_bsk_browser.bsk.models import BskResult, PageObservation
from astrbot_plugin_bsk_browser.bsk.service import BskService

class TestNavigateResilience(unittest.IsolatedAsyncioTestCase):
    async def test_navigate_recovers_from_observation_required(self) -> None:
        service = BskService(runner=MagicMock())
        service.sessions = MagicMock()
        service.observe = AsyncMock(return_value=PageObservation(title="Baidu"))
        
        call_count = 0
        executed_argv = []
        async def mock_execute(key, builder, **kwargs):
            nonlocal call_count
            call_count += 1
            argv = builder("sid1")
            executed_argv.append(argv)
            if call_count == 1:
                err = BskError("observation required", code="permission_denied")
                err.reason = "observation_required"
                err.effect_state = "none"
                raise err
            return BskResult(exit_code=0, stdout="", stderr="", data={"url": "https://www.baidu.com"})

        service.sessions.execute = mock_execute
        service.sync_session = AsyncMock(return_value=PageObservation(observation_id="obs-nav-1"))
        
        nav, obs = await service.navigate("s1", "https://www.baidu.com")
        self.assertEqual(call_count, 2)
        self.assertIn("--observation", executed_argv[1])
        idx = executed_argv[1].index("--observation")
        self.assertEqual(executed_argv[1][idx + 1], "obs-nav-1")
        self.assertEqual(nav.url, "https://www.baidu.com")
        self.assertNotIn("s1", service._session_observations)
```

- [ ] **Step 2: 运行测试验证失败**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_navigate_resilience.py`
预期：FAIL（`BskError: observation required` 未捕获）

- [ ] **Step 3: 实现 navigate 自愈重试逻辑**

在 `astrbot_plugin_bsk_browser/bsk/service.py` 的 `navigate` 方法中：
```python
        session_key = self._resolve_key(key)
        try:
            nav_result = await self.sessions.execute(
                session_key,
                lambda sid: ["navigate", url, "--session", sid, "--json"],
                timeout=self._timeout(TIMEOUT_NAVIGATE),
            )
        except BskError as exc:
            reason = getattr(exc, "reason", "")
            effect_state = getattr(exc, "effect_state", "")
            if reason in ("cooperation_sync_required", "observation_required") and effect_state != "unknown":
                self._logger.info("导航遭遇控制上下文未就绪 (%s)，执行 sync_session 补救", reason)
                obs = await self.sync_session(session_key, tab_id=tab_id)
                nav_result = await self.sessions.execute(
                    session_key,
                    lambda sid: ["navigate", url, "--observation", obs.observation_id, "--session", sid, "--json"],
                    timeout=self._timeout(TIMEOUT_NAVIGATE),
                )
            else:
                raise

        self._session_observations.pop(session_key, None)
        nav = NavigateResult.from_json(nav_result.data)
        observation = await self.observe(session_key)
        return nav, observation
```

- [ ] **Step 4: 运行测试验证通过**

运行：`python3 -m unittest astrbot_plugin_bsk_browser/tests/test_navigate_resilience.py`
预期：PASS (1 test)

- [ ] **Step 5: 运行全量测试回归**

运行：`python3 -m unittest discover astrbot_plugin_bsk_browser/tests`
预期：全部 920+ 个单测全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add astrbot_plugin_bsk_browser/bsk/service.py astrbot_plugin_bsk_browser/tests/test_navigate_resilience.py
git commit -m "feat(bsk): add auto-sync recovery to navigate and clear token cache"
```
