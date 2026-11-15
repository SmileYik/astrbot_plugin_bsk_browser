# Tab Leak Fix and Configuration Schema Refinement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 规范技能目录命名为 `bsk-browse-baidu` 与 `bsk-browse-bingcn`，精炼网站规则 Schema 并提供父子二级树形多选下拉，并为标签页关闭注入同步凭证彻底解决外链弹窗导致的窗口泄漏问题。

**Architecture:** 在 `skills/` 下重命名子目录并同步修正文档与测试；在 `_conf_schema.json` 中配置以不折叠空格缩进的父子层级 `options` / `labels` / `subtitles`；在 `detect_new_tabs_and_switch` 中先同步新标签状态再切换焦点；在 `SessionManager._stop_entry` 与 `BskService.sweep_agent_tabs` 中为 `tab close` 闭环补充 `sync` 凭据（`context_id` / `observation_id`），消除 `observation_required` 拦截与 `dropOnly: true` 窗口残留。

**Tech Stack:** Python 3.10+, AstrBot Plugin Framework, asyncio, pytest, bsk CLI.

**Spec:** [docs/superpowers/specs/2026-11-15-tab-leak-fix-and-schema-refinement-design.md](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-tab-leak-fix-and-schema-refinement-design.md)

## Global Constraints

- 唯一修改仓库：`./astrbot_plugin_bsk_browser/`
- 日志输出规范：使用 AstrBot 日志系统，工具调用及 bsk 命令输入输出采用 DEBUG 级别记录
- 版本管理要求：每个 Task 完成后必须执行 git commit
- 文本风格：用户可见文本在表意准确前提下保持精炼易读
- SKILL 文档规范：核心文档为 `bsk-browser`，专精拓展文档为 `bsk-browse-baidu` 与 `bsk-browse-bingcn`

## Review Focus

1. `_conf_schema.json` 中 `options`、`labels` 与 `subtitles` 数组长度严格一致且 JSON 语法完全合法。
2. 标签页关闭前执行 `sync` 时若目标 Tab 已被用户手动关闭或处于不可同步状态，必须安全捕获异常并继续执行清理，严禁阻断后续 `session stop`。
3. `detect_new_tabs_and_switch` 在新标签尚未完成加载时执行 `sync` 若超时，不能中断用户主流程，降级标记脏 URL 并保留控制权。
4. `bsk/permissions.py` 对新型下拉项值 `bsk_interact.click` 及通配符 `bsk_interact.*` 能够 100% 正确匹配并放行。
5. `labels` 中的 Unicode 不折叠空格（`\u00A0`）在读取配置文件与 schema 序列化时不会发生转义或解码异常。

---

### Task 1: 规范化技能目录命名与相关引用测试

**Files:**
- Move: `skills/bsk-browse-baidu.com` $\rightarrow$ `skills/bsk-browse-baidu`
- Move: `skills/bsk-browse-cn.bing.com` $\rightarrow$ `skills/bsk-browse-bingcn`
- Modify: `skills/bsk-browse-baidu/SKILL.md`
- Modify: `skills/bsk-browse-bingcn/SKILL.md`
- Modify: `skills/bsk-browser/SKILL.md`
- Modify: `tests/test_skills_doc.py`

**Interfaces:**
- Consumes: `skills/` 下现有的三个技能文档与 `tests/test_skills_doc.py`
- Produces: 符合 `AGENTS.md` 命名规范的技能目录体系

- [ ] **Step 1: Write failing test in `tests/test_skills_doc.py` for new skill directory names**

```python
def test_skill_directory_names_match_agents_md():
    skills_root = Path(__file__).resolve().parent.parent / "skills"
    assert (skills_root / "bsk-browser").is_dir()
    assert (skills_root / "bsk-browse-baidu").is_dir()
    assert (skills_root / "bsk-browse-bingcn").is_dir()
    assert not (skills_root / "bsk-browse-baidu.com").exists()
    assert not (skills_root / "bsk-browse-cn.bing.com").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_skills_doc.py -k test_skill_directory_names_match_agents_md -v`
Expected: FAIL with `AssertionError: assert not (skills_root / 'bsk-browse-baidu.com').exists()`

- [ ] **Step 3: Rename skill directories and update references**

1. 执行 `git mv skills/bsk-browse-baidu.com skills/bsk-browse-baidu`
2. 执行 `git mv skills/bsk-browse-cn.bing.com skills/bsk-browse-bingcn`
3. 更新 `skills/bsk-browse-baidu/SKILL.md` 的 frontmatter `name: bsk-browse-baidu`
4. 更新 `skills/bsk-browse-bingcn/SKILL.md` 的 frontmatter `name: bsk-browse-bingcn`
5. 更新 `skills/bsk-browser/SKILL.md` 中对于百度/必应扩展技能的引用名称
6. 更新 `tests/test_skills_doc.py` 中所有的旧目录名断言

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_skills_doc.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/ tests/test_skills_doc.py
git commit -m "refactor(skills): rename baidu and bing skill directories to match AGENTS.md"
```

---

### Task 2: 用户配置 Schema 文案精炼与父子二级树形多选下拉

**Files:**
- Modify: `_conf_schema.json:192-218`
- Modify: `tests/test_config.py`
- Modify: `tests/test_permissions_integration.py`

**Interfaces:**
- Consumes: `bsk/permissions.py:is_action_allowed`
- Produces: `_conf_schema.json` 中带有层级结构 `options`, `labels`, `subtitles` 的 `allowed_actions`

- [ ] **Step 1: Write failing test in `tests/test_config.py` for schema options, labels, and text refinement**

```python
def test_site_whitelist_schema_hierarchical_options(self):
    schema_path = Path(__file__).resolve().parent.parent / "_conf_schema.json"
    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)
    site_rule = schema["site_whitelist"]["templates"]["site_rule"]
    assert site_rule["name"] == "网站授权规则"
    actions_meta = site_rule["items"]["allowed_actions"]
    assert "options" in actions_meta
    assert "labels" in actions_meta
    assert "subtitles" in actions_meta
    assert len(actions_meta["options"]) == len(actions_meta["labels"]) == len(actions_meta["subtitles"])
    assert "bsk_interact.*" in actions_meta["options"]
    assert "bsk_interact.click" in actions_meta["options"]
    idx_parent = actions_meta["options"].index("bsk_interact.*")
    idx_child = actions_meta["options"].index("bsk_interact.click")
    assert actions_meta["labels"][idx_parent] == "bsk_interact:"
    assert actions_meta["labels"][idx_child].startswith("\u00a0\u00a0\u00a0\u00a0click")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -k test_site_whitelist_schema_hierarchical_options -v`
Expected: FAIL with `AssertionError: assert site_rule["name"] == "网站授权规则"`

- [ ] **Step 3: Update `_conf_schema.json` and sync permissions test fixtures**

1. 精炼 `site_whitelist` 文案与标题：
   - 描述：“普通用户网站与操作白名单”
   - hint：“仅在关闭「只允许管理员使用」时生效。配置普通用户可访问的域名及允许调用的页内操作。未在名单内的域名将被禁止访问。”
   - 模板名：“网站授权规则”
   - domain 描述：“允许访问的网站域名（例如 baidu.com、cn.bing.com）”
   - allowed_actions 描述：“允许调用的页内操作（留空表示仅允许打开浏览，禁止一切页内操作）”
2. 配置 `allowed_actions` 的 `options`、`labels`（带 `\u00A0\u00A0\u00A0\u00A0` 缩进）与 `subtitles`，涵盖：
   - `bsk_interact:`（`bsk_interact.*`）及其子动作：`click`, `fill`, `press`, `scroll`, `hover`, `drag`, `select`, `focus`, `blur`
   - `bsk_inspect:`（`bsk_inspect.*`）及其子动作：`observe`, `text`, `search`, `screenshot`, `full_page`, `table`, `console`
   - `bsk_page:`（`bsk_page.*`）及其子动作：`navigate`, `reload`, `back`, `forward`
   - `bsk_tabs:`（`bsk_tabs.*`）及其子动作：`list`, `select`, `create`, `close`
3. 检查 `test_config.py` 与 `test_permissions_integration.py`，确保配置项加载与权限校验测试通过。

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py tests/test_permissions_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add _conf_schema.json tests/test_config.py tests/test_permissions_integration.py
git commit -m "feat(config): refine site_whitelist schema and add hierarchical multi-select options"
```

---

### Task 3: 点击新标签焦点切换状态同步与弹性重试

**Files:**
- Modify: `bsk/service.py:2901-2973`
- Test: `tests/test_tab_lifecycle_cleanup.py`

**Interfaces:**
- Consumes: `BskService.tabs`, `BskService.sync`
- Produces: `detect_new_tabs_and_switch(key: str) -> dict[str, Any] | None`（切换前进行状态同步与重试）

- [ ] **Step 1: Write failing unit test in `tests/test_tab_lifecycle_cleanup.py`**

```python
@pytest.mark.asyncio
async def test_detect_new_tabs_syncs_before_select():
    # 模拟在 detect_new_tabs_and_switch 发现新 tab 时，必须先调用 sync 同步新 tab 状态，然后再发起 tab select
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tab_lifecycle_cleanup.py -k test_detect_new_tabs_syncs_before_select -v`
Expected: FAIL

- [ ] **Step 3: Implement state sync and resilient select in `detect_new_tabs_and_switch`**

在 `bsk/service.py` 的 `detect_new_tabs_and_switch` 中：
1. 确定 `new_tab_id` 后，先尝试调用 `await self.sync(session_key, tab_id=new_tab_id)` 建立控制权并拉齐 epoch；
2. 再执行 `await self.tabs(session_key, "select", tab_id=new_tab_id)` 切换焦点；
3. 若 `tabs("select")` 仍遇到 `cooperation_sync_required`，安全记录 warning 并降级，同时保存 active_url，确保后续 `observe` 准确命中新标签页。

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tab_lifecycle_cleanup.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add bsk/service.py tests/test_tab_lifecycle_cleanup.py
git commit -m "fix(service): synchronize tab state before switching focus to new tabs"
```

---

### Task 4: 外链弹窗标签页带凭据闭环清理与防泄漏

**Files:**
- Modify: `bsk/session.py:1722-1745`
- Modify: `bsk/service.py:2974-3004`
- Modify: `bsk/service.py:3156-3240`
- Test: `tests/test_tab_lifecycle_cleanup.py`

**Interfaces:**
- Consumes: `SessionManager._stop_entry`, `BskService.sweep_agent_tabs`, `BskRunner.run`
- Produces: 带 `--context` 与 `--observation` 的 `tab close` 执行命令，彻底消除 `dropOnly: true` 残留

- [ ] **Step 1: Write failing unit tests in `tests/test_tab_lifecycle_cleanup.py` for credential-backed tab close**

```python
@pytest.mark.asyncio
async def test_stop_entry_fetches_sync_credentials_for_tab_close():
    # 模拟 session stop 扫尾时，执行 tab close 必须带有 --context 与 --observation 凭据
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tab_lifecycle_cleanup.py -k test_stop_entry_fetches_sync_credentials_for_tab_close -v`
Expected: FAIL

- [ ] **Step 3: Implement credential injection in `_stop_entry`, `sweep_agent_tabs` and `tabs`**

1. 在 `bsk/session.py` 的 `_stop_entry`：
   遍历 `tab_list[1:]` 时，对每个多余 `tid`：
   - 执行 `res_sync = await self._runner.run(["sync", "--session", sid, "--tab-id", str(tid), "--json"], timeout=5.0)`
   - 从 `res_sync.data` 提取 `context_id` 与 `observation_id`；
   - 构造 `["tab", "close", str(tid), "--session", sid, "--context", ctx, "--observation", obs, "--json"]` 并执行；
   - try/except 吞掉单次异常，保证后续正常 stop。
2. 在 `bsk/service.py` 的 `sweep_agent_tabs`：
   关闭每个 `tid` 前，通过 `await self.sync(session_key, tab_id=int(tid))` 获取最新 `observation_id`，传给 `tabs("close", tab_id=tid)`。
3. 在 `bsk/service.py` 的 `tabs(action="close")`：
   检查是否存在或补全 `--context` / `--observation` 选项。

- [ ] **Step 4: Run all tests to verify they pass**

Run: `pytest tests/test_tab_lifecycle_cleanup.py -v`
Expected: PASS

- [ ] **Step 5: Run full plugin test suite**

Run: `pytest -v`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add bsk/session.py bsk/service.py tests/test_tab_lifecycle_cleanup.py
git commit -m "fix(session): attach sync credentials to tab close commands to prevent tab leak"
```
