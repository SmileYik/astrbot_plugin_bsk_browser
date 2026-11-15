# 外链新标签页回收修复与 SKILL 文档纯粹精简实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复会话终结/超时时外链新标签页未被关闭导致宿主机窗口残留的缺陷，并精简三份 SKILL.md 文档以剥离程序自动控制的后台配置。

**Architecture:** 在底层 `SessionManager._stop_entry` 统一解析 `bsk tab list` 字典载荷并依次关闭所有外链多余标签，消除 `dropOnly` 诱因；同步整理 `BskService.sweep_agent_tabs`；精简 `bsk-browser`、`browse-baidu.com`、`browse-cn.bing.com`，更新对应单元测试。

**Tech Stack:** Python 3.12+, AsyncIO, pytest, AstrBot Plugin Framework, bsk CLI.

**Spec:** `astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-tab-reclaim-and-skill-simplification-design.md`

## Global Constraints

- 日志规范：以 DEBUG 等级记录 bsk 指令输入/输出及工具调用会话与名称。
- 工具与文档文本：在准确表达基础上精炼简洁，不得啰嗦，不得将后台配置项（如压缩、画质、视口截断等）写入 SKILL 文档。
- SKILL 依赖关系：`bsk-browser` 为核心基础，`browse-baidu.com` 与 `browse-cn.bing.com` 专精于各自站点的搜索框、分页及结果识别，不重复核心内容。
- 版本管理：每个 task 完成后提交 `astrbot_plugin_bsk_browser` 仓库 git commit。

## Review Focus

- `bsk tab list --json` 返回字典 `{"tabs": [...]}` 时，`_stop_entry` 能正确提取出标签列表并逐个关闭派生标签。
- Agent Window 只有一个标签页时，`_stop_entry` 不会抛异常且不会关闭这唯一的主标签（留给 `bsk session stop` 正常处理）。
- `SessionManager.reap_idle` 超时回收触发时，调用 `_stop_entry` 并成功关闭多余标签。
- SKILL 文档中不再包含 `screenshot_compress_to_jpg`、`screenshot_quality`、`fullpage_max_height` 等内部配置键名。
- 全部测试套件（1000+ tests）100% 通过无回归。

---

### Task 1: 修复 `SessionManager._stop_entry` 中的标签载荷解析与清理

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/session.py:1720-1745`
- Test: `astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py`

**Interfaces:**
- Consumes: `SessionManager._runner.run(["tab", "list", "--scope", "agent", ...])`
- Produces: `SessionManager._stop_entry(entry: _Entry) -> bool` 可靠清理除主标签外的所有标签页

- [ ] **Step 1: 编写针对 `_stop_entry` 字典载荷清理的失败测试**

在 `astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py` 中新增 `test_session_manager_stop_entry_sweeps_tabs_from_dict_payload`:
```python
@pytest.mark.asyncio
async def test_session_manager_stop_entry_sweeps_tabs_from_dict_payload():
    from unittest.mock import AsyncMock, MagicMock
    from bsk.session import SessionManager, _Entry
    from bsk.models import BskSession

    runner = MagicMock()
    # 模拟 tab list 返回字典载荷 {"tabs": [...]}
    async def mock_run(args, timeout=None):
        cmd = " ".join(args)
        if "tab list" in cmd:
            return MagicMock(data={
                "tabs": [
                    {"tab_id": 101, "title": "Baidu", "url": "https://www.baidu.com"},
                    {"tab_id": 102, "title": "Tieba", "url": "https://tieba.baidu.com"},
                ]
            })
        elif "tab close" in cmd:
            return MagicMock(data={"tab_id": 102})
        elif "session stop" in cmd:
            return MagicMock(data={}, exit_code=0)
        return MagicMock(data={})

    runner.run = AsyncMock(side_effect=mock_run)
    sm = SessionManager(runner=runner)
    
    session = BskSession(session_id="test_sess", raw={"agent_window_id": 1})
    entry = _Entry(key="k1", session=session, last_used=100.0)

    success = await sm._stop_entry(entry)
    assert success is True

    # 验证确实对 tab_id=102 发起了 tab close
    close_calls = [call for call in runner.run.call_args_list if "close" in call[0][0]]
    assert len(close_calls) == 1
    assert "102" in close_calls[0][0][0] or "102" in close_calls[0][0]
```

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py -k test_session_manager_stop_entry_sweeps_tabs_from_dict_payload -v`  
预期：FAIL（因为当前 `isinstance(res.data, list)` 为 False，未调用 `tab close`）

- [ ] **Step 3: 修复 `SessionManager._stop_entry` 中的载荷解析与关闭逻辑**

修改 `astrbot_plugin_bsk_browser/bsk/session.py`：
```python
        try:
            res = await self._runner.run(
                ["tab", "list", "--scope", "agent", "--session", entry.session.session_id, "--json"],
                timeout=5.0,
            )
            raw = res.data
            tab_list = raw.get("tabs", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
            if isinstance(tab_list, list) and len(tab_list) > 1:
                for t in tab_list[1:]:
                    if isinstance(t, dict):
                        tid = t.get("tab_id", t.get("id"))
                        if tid is not None:
                            try:
                                await self._runner.run(
                                    ["tab", "close", str(tid), "--session", entry.session.session_id, "--json"],
                                    timeout=5.0,
                                )
                            except Exception as exc:  # noqa: BLE001
                                self._logger.debug("关闭多余标签页 %s 失败（忽略）：%r", tid, exc)
        except Exception as exc:  # noqa: BLE001
            self._logger.debug("获取 Agent 标签页列表以清理失败（忽略）：%r", exc)
```

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py -v`  
预期：PASS

- [ ] **Step 5: 提交 Task 1 代码**

```bash
git add astrbot_plugin_bsk_browser/bsk/session.py astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py
git commit -m "fix(session): parse dict payload in _stop_entry to sweep extra agent tabs"
```

---

### Task 2: 统一完善 `BskService.sweep_agent_tabs` 与会话超时测试

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py:2974-3015`
- Test: `astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py`

**Interfaces:**
- Consumes: `BskService.tabs(session_key, "list", scope="agent")`
- Produces: `BskService.sweep_agent_tabs(key: str) -> None`

- [ ] **Step 1: 编写超时回收 `reap_idle` 清理多标签测试**

在 `astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py` 中新增 `test_session_manager_reap_idle_cleans_extra_tabs`:
```python
@pytest.mark.asyncio
async def test_session_manager_reap_idle_cleans_extra_tabs():
    from unittest.mock import AsyncMock, MagicMock
    from bsk.session import SessionManager, _Entry
    from bsk.models import BskSession

    runner = MagicMock()
    async def mock_run(args, timeout=None):
        cmd = " ".join(args)
        if "tab list" in cmd:
            return MagicMock(data={"tabs": [{"tab_id": 1}, {"tab_id": 2}]})
        elif "tab close" in cmd:
            return MagicMock(data={"tab_id": 2})
        elif "session stop" in cmd:
            return MagicMock(data={}, exit_code=0)
        return MagicMock(data={})

    runner.run = AsyncMock(side_effect=mock_run)
    clock_time = 1000.0
    sm = SessionManager(runner=runner, idle_release_sec=10.0, clock=lambda: clock_time)

    session = BskSession(session_id="idle_sess", raw={"agent_window_id": 1})
    entry = _Entry(key="k_idle", session=session, last_used=900.0)
    sm._entries["k_idle"] = entry

    count = await sm.reap_idle()
    assert count == 1
    assert "k_idle" not in sm._entries

    close_calls = [call for call in runner.run.call_args_list if "close" in call[0][0]]
    assert len(close_calls) == 1
    assert "2" in close_calls[0][0][0] or "2" in close_calls[0][0]
```

- [ ] **Step 2: 运行测试验证**

运行：`pytest astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py -k test_session_manager_reap_idle_cleans_extra_tabs -v`  
预期：PASS

- [ ] **Step 3: 完善 `BskService.sweep_agent_tabs` 的健壮性与日志**

检查并确保 `BskService.sweep_agent_tabs` 中同样兼容 `{"tabs": [...]}` 与裸列表，且日志以 DEBUG 输出 `[标签扫尾清理]`。

- [ ] **Step 4: 运行全部相关测试**

运行：`pytest astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py -v`  
预期：PASS

- [ ] **Step 5: 提交 Task 2 代码**

```bash
git add astrbot_plugin_bsk_browser/bsk/service.py astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py
git commit -m "test(session): verify reap_idle tab sweep and ensure service cleanup parity"
```

---

### Task 3: 纯粹精简 SKILL.md 文档并更新 `test_skills_doc.py`

**Files:**
- Modify: `astrbot_plugin_bsk_browser/skill/bsk-browser/SKILL.md`
- Modify: `astrbot_plugin_bsk_browser/skill/browse-baidu.com/SKILL.md`
- Modify: `astrbot_plugin_bsk_browser/skill/browse-cn.bing.com/SKILL.md`
- Modify: `astrbot_plugin_bsk_browser/tests/test_skills_doc.py`

**Interfaces:**
- Consumes: SKILL 编写规范与用户关于“后台配置不入 SKILL”的明确要求
- Produces: 精简后的三份 SKILL.md，严禁出现程序自动处理的配置项名称

- [ ] **Step 1: 精简 `skill/bsk-browser/SKILL.md`**

移除以下后台配置描述：
- `screenshot_compress_to_jpg`、`screenshot_quality`
- `fullpage_max_height`、`fullpage_scope`
- `site_whitelist`、`allowed_actions`

精炼截图说明：
- 说明 `screenshot` 直接将图片发送给用户，长图传 `full_page=True`，裁剪传 `ref="@eN"`；图片格式处理与尺寸控制由系统自动完成。

精炼权限说明：
- 说明若调用受到站点权限或工具限制，如实反馈用户，不得重复重试。

精炼会话生命周期说明：
- 说明任务进行中可保留新标签页以供查阅；整轮任务结束时，可调用 `bsk_session(action="stop")` 释放浏览器；空闲时底层具有全自动销毁保障。

- [ ] **Step 2: 精简 `skill/browse-baidu.com/SKILL.md` 与 `skill/browse-cn.bing.com/SKILL.md`**

保持两者专精于自身站点的特征：
- 百度：主页 vs 结果页结构（`#content_left`、`#page`）、搜索栏与“百度一下”按钮、底部分页识别（`上一页`、`下一页 >`、数字页码）、定向 `scroll-to` 与带卡片目标的 `wheel` 滚动。
- 必应：主页 vs 结果页结构（`#b_results`、`.b_pag`）、搜索栏与放大镜搜索按钮、底部分页识别（`<`、`>`、数字页码）、结果卡片滚动。
- 移除所有与通用核心重复的多余配置说明，明确依赖于 `bsk-browser`。

- [ ] **Step 3: 更新 `tests/test_skills_doc.py`**

将原先硬编码检查 `self.assertIn("压缩", bsk_content)` 移除，改为断言：
1. 三份文档均存在且满足结构要求；
2. 内部配置键名 `screenshot_compress_to_jpg`、`screenshot_quality`、`fullpage_max_height`、`site_whitelist` 绝不出现在任何 SKILL 文档中；
3. 核心工具 `bsk_session`、`bsk_inspect`、`bsk_interact`、`bsk_tabs`、`full_page` 等必要指引依然完备。

- [ ] **Step 4: 运行 `test_skills_doc.py` 验证**

运行：`pytest astrbot_plugin_bsk_browser/tests/test_skills_doc.py -v`  
预期：PASS

- [ ] **Step 5: 提交 Task 3 代码**

```bash
git add astrbot_plugin_bsk_browser/skill/ astrbot_plugin_bsk_browser/tests/test_skills_doc.py
git commit -m "docs(skill): streamline SKILL.md by removing programmatic backend configs"
```

---

### Task 4: 全量回归测试与文档状态同步

**Files:**
- Modify: `astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-tab-reclaim-and-skill-simplification-design.md` (标记为 Approved)

- [ ] **Step 1: 运行全量测试套件**

运行：`pytest astrbot_plugin_bsk_browser/tests`  
预期：1000+ passed

- [ ] **Step 2: 更新设计文档状态为已批准并完成**

将设计文档中的 `状态：待用户审批 (Pending Approval)` 更新为 `状态：已批准并完成 (Approved & Implemented)`。

- [ ] **Step 3: 提交 Task 4 代码**

```bash
git add astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-tab-reclaim-and-skill-simplification-design.md
git commit -m "chore(specs): update design doc status to approved"
```
