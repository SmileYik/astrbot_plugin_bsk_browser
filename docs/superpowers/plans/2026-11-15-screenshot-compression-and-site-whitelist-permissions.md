# 截图压缩配置、长截图截断防超时与网站白名单权限系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 `astrbot_plugin_bsk_browser` 增加截图压缩配置（默认直发原图）、全页长截图高度策略与超长自动截断保护、以及基于 `template_list` 的细粒度网站操作白名单权限系统与双层高危工具隔离。

**Architecture:** 在 `_conf_schema.json` 与 `config.py` 扩充压缩开关、质量滑块、长截图策略/最大高度及 `site_whitelist` 模板；在 `shots.py` 与 `service.py` 改造截图生成管线，支持按需转 JPEG 与 Pillow 垂直截断；在 `service.py` 增加 `current_url` 脏标记感知，并在独立模块 `bsk/permissions.py` 中实现域名与操作匹配器；在 `main.py` 的 `_dispatch` 前置实施细粒度鉴权审计，并配合 `on_llm_request` 动态隐藏 5 大禁用工具；全面更新 5 大工具子操作文档与 SKILL.md。

**Tech Stack:** Python 3.10+, AstrBot 4.x Plugin System, Pillow (PIL), pytest.

**Spec:** [`docs/superpowers/specs/2026-11-15-screenshot-compression-and-site-whitelist-permissions-design.md`](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-screenshot-compression-and-site-whitelist-permissions-design.md)

## Global Constraints

- 保持标准库与现有依赖范围，Pillow 可选依赖必须具备优雅降级（不可用时保留原图并记入日志，绝不抛出未捕获异常）。
- 截图压缩默认值必须为 `screenshot_compress_to_jpg=False`，即默认不压缩直接发送原图 PNG。
- 全页截图默认策略为 `fullpage_scope="current"`，默认最大截断高度 `fullpage_max_height=8000`。
- 高危与内部工具（`bsk_load_tools`, `bsk_debug`, `bsk_assist`, `bsk_status`, `bsk_evaluate`）对非管理员绝对不可见、不可调用。
- 基础生命周期与运维操作（`bsk_session.start`, `stop`, `list`, `sync`, `bsk_tabs.list`, `select`, `close`）对普通用户默认放行，防范死锁。
- 遵循 `AGENTS.md`：日志以 DEBUG 级别输出，涵盖 bsk 指令输入/输出、工具调用会话与名称、权限审计记录；每次 task 完成必须 commit。

## Review Focus

1. **白名单外部域名点击跳转越权**：用户在白名单网站（如百度）点击搜索结果或链接跳转到非白名单外网，后续 `observe`/`click` 必须被立即阻断，并提示当前域名未授权。
2. **长截图超出最大高度自动截断**：长截图实际高度超过 `fullpage_max_height` 时，必须干净截断至最大像素高度，并在回执中提示截断，不得生成超大图或报错。
3. **压缩开关关闭时保留原图**：当 `screenshot_compress_to_jpg=False` 时，即使图片很大，也不得调用转 JPEG 逻辑，必须输出原始 PNG 文件。
4. **外链死锁规避**：在已跳转至未授权外部网页时，普通用户调用 `bsk_tabs(action="close")` 必须成功放行，允许关闭该标签页。
5. **禁用工具 Prompt 动态过滤**：普通用户提问时，通过 `@filter.on_llm_request()` 动态将 5 个禁用工具从 `req.func_tool` 中剥离，确保模型看不到这些工具。

---

### Task 1: 配置项扩展与校验 (`_conf_schema.json` & `bsk/config.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/_conf_schema.json`
- Modify: `astrbot_plugin_bsk_browser/bsk/config.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_config.py`

**Interfaces:**
- Consumes: `bsk/config.py` 中的 `BskSettings` 与 `validate_settings`。
- Produces:
  - `BskSettings.screenshot_compress_to_jpg: bool = False`
  - `BskSettings.screenshot_quality: int = 85`
  - `BskSettings.fullpage_scope: str = "current"`
  - `BskSettings.fullpage_max_height: int = 8000`
  - `BskSettings.site_whitelist: list[dict] = []`

- [ ] **Step 1: Write the failing tests in `tests/test_config.py`**

```python
def test_screenshot_and_whitelist_settings_defaults():
    settings = load_settings({})
    assert settings.screenshot_compress_to_jpg is False
    assert settings.screenshot_quality == 85
    assert settings.fullpage_scope == "current"
    assert settings.fullpage_max_height == 8000
    assert settings.site_whitelist == []

def test_screenshot_and_whitelist_settings_custom():
    custom = {
        "screenshot_compress_to_jpg": True,
        "screenshot_quality": 60,
        "fullpage_scope": "follow",
        "fullpage_max_height": 5000,
        "site_whitelist": [
            {"domain": "baidu.com", "allowed_actions": ["click", "fill"]}
        ],
    }
    settings = load_settings(custom)
    assert settings.screenshot_compress_to_jpg is True
    assert settings.screenshot_quality == 60
    assert settings.fullpage_scope == "follow"
    assert settings.fullpage_max_height == 5000
    assert len(settings.site_whitelist) == 1
    assert settings.site_whitelist[0]["domain"] == "baidu.com"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py::test_screenshot_and_whitelist_settings_defaults -v`
Expected: FAIL with `AttributeError: 'BskSettings' object has no attribute 'screenshot_compress_to_jpg'`

- [ ] **Step 3: Update `_conf_schema.json` and `bsk/config.py`**

在 `_conf_schema.json` 中添加 `screenshot_compress_to_jpg`、`screenshot_quality`、`fullpage_scope`、`fullpage_max_height` 和 `site_whitelist`（`template_list`）。
在 `bsk/config.py` 中更新常量、`BskSettings` 字段、类型转换与钳制校验。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add _conf_schema.json bsk/config.py tests/test_config.py
git commit -m "feat(config): add screenshot compression, fullpage scope/max_height, and site_whitelist settings"
```

---

### Task 2: 截图生成流水线改造（压缩可选与超长截断）

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/shots.py`
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py`
- Modify: `astrbot_plugin_bsk_browser/tests/test_shot_compression.py`

**Interfaces:**
- Consumes: `BskSettings` 中的新字段。
- Produces:
  - `truncate_image_height(path: str | Path, max_height: int) -> tuple[Path, bool]`
  - `screenshot_ex(..., scope: str = "")` 支持向 `bsk screenshot` 传递 `--scope`
  - 按配置条件执行压缩和截断，生成符合预期的 `ShotPayload`。

- [ ] **Step 1: Write the failing tests in `tests/test_shot_compression.py`**

```python
def test_truncate_image_height_when_exceeding(tmp_path):
    from PIL import Image
    from bsk.shots import truncate_image_height
    img_path = tmp_path / "tall.png"
    Image.new("RGB", (800, 10000), color=(255, 0, 0)).save(img_path)
    truncated_path, did_truncate = truncate_image_height(img_path, max_height=6000)
    assert did_truncate is True
    with Image.open(truncated_path) as im:
        assert im.size == (800, 6000)

def test_truncate_image_height_when_under_limit(tmp_path):
    from PIL import Image
    from bsk.shots import truncate_image_height
    img_path = tmp_path / "short.png"
    Image.new("RGB", (800, 3000), color=(0, 255, 0)).save(img_path)
    truncated_path, did_truncate = truncate_image_height(img_path, max_height=6000)
    assert did_truncate is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_shot_compression.py::test_truncate_image_height_when_exceeding -v`
Expected: FAIL with `ImportError: cannot import name 'truncate_image_height'`

- [ ] **Step 3: Implement truncation & conditional compression**

1. 在 `bsk/shots.py` 中实现 `truncate_image_height(path, max_height)`；
2. 在 `bsk/service.py` 的 `screenshot_ex` 中：
   - 当 `use_full_page` 时，追加 `--scope <scope or settings.fullpage_scope>`；
   - 截图成功后，若 `use_full_page` 且 `settings.fullpage_max_height > 0`，调用 `truncate_image_height`，并在 `shot.warning` 附加上限提示；
   - 仅在 `settings.screenshot_compress_to_jpg` 为 True 时，调用 `compress_and_optimize_image`（传 `quality=settings.screenshot_quality`）；否则直接保留原图 PNG。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_shot_compression.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bsk/shots.py bsk/service.py tests/test_shot_compression.py
git commit -m "feat(shots): implement fullpage height truncation and configurable jpeg compression"
```

---

### Task 3: 域名与动作白名单匹配器及会话 URL 感知 (`bsk/permissions.py` & `bsk/service.py`)

**Files:**
- Create: `astrbot_plugin_bsk_browser/bsk/permissions.py`
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py`
- Create: `astrbot_plugin_bsk_browser/tests/test_site_permissions.py`

**Interfaces:**
- Produces:
  - `normalize_domain(url_or_host: str) -> str`
  - `is_domain_match(pattern: str, target: str) -> bool`
  - `is_action_allowed(allowed_actions: list[str], tool: str, action: str) -> bool`
  - `check_site_permission(site_whitelist: list[dict], current_url: str, tool: str, action: str) -> tuple[bool, str]`
  - `BskService.get_active_url(key: str) -> str`
  - `BskService.mark_url_dirty(key: str) -> None`

- [ ] **Step 1: Write the failing tests in `tests/test_site_permissions.py`**

```python
from bsk.permissions import normalize_domain, is_domain_match, is_action_allowed, check_site_permission

def test_normalize_domain():
    assert normalize_domain("https://www.baidu.com/s?wd=test") == "baidu.com"
    assert normalize_domain("http://tieba.baidu.com:8080/f") == "tieba.baidu.com"
    assert normalize_domain("cn.bing.com") == "cn.bing.com"

def test_domain_match():
    assert is_domain_match("baidu.com", "baidu.com") is True
    assert is_domain_match("baidu.com", "www.baidu.com") is True
    assert is_domain_match("baidu.com", "tieba.baidu.com") is True
    assert is_domain_match("baidu.com", "notbaidu.com") is False

def test_action_allowed():
    assert is_action_allowed(["click", "fill"], "bsk_interact", "click") is True
    assert is_action_allowed(["bsk_interact.click"], "bsk_interact", "click") is True
    assert is_action_allowed(["bsk_interact.*"], "bsk_interact", "fill") is True
    assert is_action_allowed(["click"], "bsk_inspect", "screenshot") is False

def test_check_site_permission_navigation_implied():
    rules = [{"domain": "baidu.com", "allowed_actions": ["click", "fill"]}]
    ok, _ = check_site_permission(rules, "https://www.baidu.com", "bsk_page", "navigate")
    assert ok is True

def test_check_site_permission_in_page_disallowed():
    rules = [{"domain": "baidu.com", "allowed_actions": ["click", "fill"]}]
    ok, reason = check_site_permission(rules, "https://www.baidu.com", "bsk_inspect", "screenshot")
    assert ok is False
    assert "未向普通用户开放" in reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_site_permissions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'bsk.permissions'`

- [ ] **Step 3: Implement `bsk/permissions.py` and URL tracking in `service.py`**

1. 创建 `bsk/permissions.py`，实现域名清洗、通配匹配与动作鉴权逻辑；
2. 在 `BskService` 中添加会话级 `_active_urls: dict[str, str]` 与 `_dirty_urls: set[str]`；
3. 在 `open` / `navigate` 后更新 `current_url` 并清除 dirty；在 `click` / `press` / `reload` / `back` / `forward` / `wait` 后标记 `mark_url_dirty`；
4. 实现 `get_active_url(key)`：脏时若存在会话则通过 `tab_list` 刷新真实 URL。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_site_permissions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bsk/permissions.py bsk/service.py tests/test_site_permissions.py
git commit -m "feat(permissions): add domain normalization, action matching, and active url tracking"
```

---

### Task 4: 鉴权门禁接入、高危工具硬隔离与提示词动态 Hook (`main.py`)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/main.py`
- Create: `astrbot_plugin_bsk_browser/tests/test_permissions_integration.py`

**Interfaces:**
- Consumes: `bsk/permissions.py`、`BskSettings.site_whitelist`、`BskService.get_active_url`。
- Produces:
  - `_dispatch` 前置细粒度普通用户白名单鉴权；
  - `[权限审计]` 结构化 DEBUG 日志；
  - `@filter.on_llm_request()` 动态剥离非管理员的高危工具。

- [ ] **Step 1: Write integration tests in `tests/test_permissions_integration.py`**

```python
import pytest
from bsk.config import BskSettings
from main import BskBrowserPlugin

class FakeEvent:
    def __init__(self, is_admin=False, sender_id="user_123", umo="umo_1"):
        self._is_admin = is_admin
        self._sender_id = sender_id
        self.unified_msg_origin = umo
    def is_admin(self):
        return self._is_admin
    def get_sender_id(self):
        return self._sender_id
    def get_session_id(self):
        return self.unified_msg_origin

@pytest.mark.asyncio
async def test_dangerous_tool_hard_blocked_for_non_admin(plugin):
    event = FakeEvent(is_admin=False)
    result = await plugin._dispatch("bsk_debug", event, {"action": "start"})
    assert "该高级浏览器工具仅限管理员使用" in result

@pytest.mark.asyncio
async def test_lifecycle_allowed_for_non_admin(plugin):
    event = FakeEvent(is_admin=False)
    # bsk_session.stop is always permitted
    res = await plugin._dispatch("bsk_session", event, {"action": "stop"})
    assert "没有权限" not in res

@pytest.mark.asyncio
async def test_non_whitelisted_domain_rejected(plugin):
    event = FakeEvent(is_admin=False)
    res = await plugin._dispatch("bsk_page", event, {"action": "navigate", "url": "https://evil.com"})
    assert "不在允许访问的白名单中" in res
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions_integration.py -v`
Expected: FAIL

- [ ] **Step 3: Implement permission check & prompt hook in `main.py`**

1. 在 `main.py` 的 `_dispatch` 中：
   - 检查 `is_admin`；若为管理员或在 `allowed_users` 中，直接放行；
   - 若 `settings.admin_only=True`，沿用既有拦截；
   - 若 `settings.admin_only=False`：
     - 若 `tool in ("bsk_load_tools", "bsk_debug", "bsk_assist", "bsk_status", "bsk_evaluate")`：拒绝并记录 `[权限审计]` 日志；
     - 若为基础生命周期动作（`session.start/stop/list/sync`, `tabs.list/select/close`），放行并记录；
     - 若为导航（`open`/`navigate`），取参数 `url` 校验白名单并记录；
     - 若为页内操作，取 `service.get_active_url(key)` 校验白名单与 `allowed_actions` 并记录；
2. 注册 `@filter.on_llm_request()` 监听器：
   - 若请求者非管理员且已开启浏览器功能，检查 `req.func_tool`，移除 5 个禁用工具定义。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_permissions_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_permissions_integration.py
git commit -m "feat(security): enforce site whitelist, dangerous tool isolation, and prompt filtering"
```

---

### Task 5: 5 大工具全部子操作文档化与 SKILL.md 深度维护

**Files:**
- Modify: `astrbot_plugin_bsk_browser/skill/bsk-browser/SKILL.md`
- Modify: `astrbot_plugin_bsk_browser/README.md`
- Modify: `astrbot_plugin_bsk_browser/ARCHITECTURE.md`

**Interfaces:**
- Consumes: 设计规范第 4.4 节所有 5 大工具所有动作的详细定义。
- Produces: 详尽规范的 SKILL.md、用户指南与架构更新。

- [ ] **Step 1: Update `skill/bsk-browser/SKILL.md`**

完善 `bsk_session` (start/stop/list/sync/open)、`bsk_page` (navigate/back/forward/reload/wait)、`bsk_inspect` (observe/snapshot/html/screenshot/console/network)、`bsk_interact` (click/fill/press/wheel/scroll-to/hover/select/focus/blur)、`bsk_tabs` (list/create/select/close/borrow/return) 的用途与调用准则；说明长截图与压缩配置及普通用户权限边界。

- [ ] **Step 2: Update `README.md` and `ARCHITECTURE.md`**

更新新增配置项说明表格、普通用户白名单配置范例、长截图策略说明。

- [ ] **Step 3: Run full test suite to verify no regressions**

Run: `pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add skill/ README.md ARCHITECTURE.md
git commit -m "docs: detail all tool subactions in SKILL.md and update configuration guides"
```
