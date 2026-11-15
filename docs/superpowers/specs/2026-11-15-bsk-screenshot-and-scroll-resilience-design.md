# 修复全截屏鉴权失效、统一发图体验与页面滚动引导设计文档

**文档标识**：`2026-11-15-bsk-screenshot-and-scroll-resilience-design`  
**作者**：Antigravity  
**状态**：待审批 (Pending Approval)  
**涉及模块**：
- `astrbot_plugin_bsk_browser/bsk/service.py`
- `astrbot_plugin_bsk_browser/main.py`
- `astrbot_plugin_bsk_browser/bsk/tools.py`
- `astrbot_plugin_bsk_browser/skill/bsk-browser/SKILL.md`
- `astrbot_plugin_bsk_browser/skill/browse-baidu.com/SKILL.md`
- `astrbot_plugin_bsk_browser/skill/browse-cn.bing.com/SKILL.md`
- `astrbot_plugin_bsk_browser/tests/`

---

## 1. 背景与问题定义 (Intent & Why)

在最近的线上实际运行日志（`astrbot-diagnostics-20261115-092934.zip`）中暴露了以下几个影响核心体验的缺陷：

1. **全截屏（Full-Page Screenshot）100% 失败**：
   - 当大模型调用 `bsk_screenshot(full_page=True)` 时，底层 `bsk` 均报错 `permission_denied: This action requires an unused strict observation from cooperate sync`。
   - 大模型在收到错误提示后，按照建议调用了 `bsk_session(action="sync")` 同步页面并成功生成了新的 `observation_id`；但随后再次调用 `bsk_screenshot(full_page=True)` 时，依然报错失败。
   - **根本原因**：普通视口截图是只读命令，但 `bsk screenshot --full-page` 涉及滚动页面与拼图，在 `cooperate` 模式下被视为页面修改动作，**必须携带 `--observation <id>` 令牌**。`BskService.screenshot` 和 `screenshot_ex` 均未消费 `self._session_observations` 缓存中的令牌，且未实现遇到 `observation_required` 时的自动 `sync` 重试自愈。
2. **两套截图工具均无法向用户聊天正常返回图片**：
   - 旧工具 `bsk_screenshot` 本身具备 `yield event.image_result(path)` 发图逻辑，但由于全屏截图报错，异常提前中断，从未执行到发图代码。
   - 新工具 `bsk_inspect(action="screenshot")` 在旧版架构中为普通异步函数，代码明确标注“新工具只返回文字描述，不把图片发给用户”，导致模型优先使用新工具时用户收不到图。
   - 在后台标签页中，视口截图触发了底层 CDP 10秒超时（`Viewport capture timed out`）。
3. **百度搜索与贴吧页面无法上下滚动**：
   - **方向混淆**：大模型在想要向下滚动时频繁传入负数（如 `delta_y: -800`、`-1000`、`-5000`）；而页面初始在顶部（`scrollY=0`），向上滚动没有任何位移。
   - **命中非滚动区域**：`wheel` 未指定 `target` 时，`bsk` 默认将滚轮事件打在视口中心 `(width/2, height/2)`。在 PC 端百度页面，主内容区 `#content_left` 位于左侧（宽约 650px），中心点落在右侧栏 `#content_right` 或空白处，滚轮事件被非滚动元素吸收。
   - **工具选型不当**：用户要求“滚动到下面的下一页按钮”，模型已经通过 `observe(query="下一页")` 找到了元素 `@eN`，却未使用专用的 `scroll_to` 工具（`scrollIntoViewIfNeeded`），而是盲目调用无目标 `wheel`。
   - **缺乏针对性 SKILL 文档**：未按 `AGENTS.md` 规范建立 `browse-baidu.com` 和 `browse-cn.bing.com` 技能指南。

---

## 2. 备选方案对比与决策 (Approaches)

在头脑风暴阶段，我们探讨了两种方案：

### 方案 A：保守修补方案（保持新旧工具职责隔离）
- **做法**：仅在 `service.py` 的全屏截图补齐 `--observation` 注入与自愈；`bsk_inspect` 保持纯文本返回，依赖提示词强行让模型切换到 `bsk_screenshot` 发图；补充 SKILL 文档。
- **权衡**：改动较少，但未能消除新工具无法发图的体验缺陷，模型经常习惯性调用新工具 `bsk_inspect` 导致用户仍然无法收到图片。

### 方案 B：全面协同方案（统一两套截图工具的发图体验，用户已选定）
- **做法**：
  1. **服务层自愈**：在 `BskService` 中统一为 `screenshot` 和 `screenshot_ex` 补齐全屏截图令牌注入（消费 `_session_observations`）与自动 `sync_session` 重试。
  2. **统一发图能力**：将 `bsk_inspect` 改造成异步生成器（AsyncGenerator），当 `action == "screenshot"` 时，通过 `yield event.image_result(payload.path)` 真正把图片发送到聊天中，彻底消除新工具“无法发图”的缺陷。
  3. **工具描述强化**：在 `main.py` 与 `bsk/tools.py` 中对 `delta_y` 进行正负方向的强提醒，并标明定位特定元素时优先选用 `scroll_to`。
  4. **完善三份 SKILL 文档**：维护 `skill/bsk-browser/SKILL.md`，新建 `skill/browse-baidu.com/SKILL.md` 与 `skill/browse-cn.bing.com/SKILL.md`。
- **决策理由**：彻底解决截图发不出图和模型滚动迷茫的问题，给用户和模型提供一致、健壮的交互体验。

---

## 3. 目标与非目标 (Goals & Non-Goals)

### Goals
1. `BskService.screenshot` 和 `BskService.screenshot_ex` 在 `full_page=True` 时自动注入缓存的 `observation_id`；若遭遇 `observation_required`、`cooperation_sync_required` 或 `control_context_invalid`（且 `effect_state != "unknown"`），自动调用 `sync_session` 刷新令牌并重试一次。
2. 任何全屏截图执行后（无论成功还是重试后），清空该会话在 `_session_observations` 中的缓存，避免过期的观察令牌残留。
3. `bsk_inspect` 支持异步生成器流式输出：在 `action == "screenshot"` 时，先 `yield event.image_result(payload.path)` 发送图片，再 `yield message` 交付文字说明；其他 action 正常 yield 文字。并在 `bsk/tools.py` 的 `bsk_inspect` schema 中正式补充可选参数 `full_page(boolean)`，使其通过标准的参数白名单校验（[Builder Check 决议]）。
4. 在 `main.py` 与 `bsk/tools.py` 中明确标注 `delta_y`：正数向下滚动，负数向上滚动；在相关描述中引导优先使用 `scroll_to` 配合目标 `@eN` 定位元素。
5. 按 `AGENTS.md` 规范维护三份 SKILL 文档：
   - `astrbot_plugin_bsk_browser/skill/bsk-browser/SKILL.md`（通用操作指南与滚动/截图选型）
   - `astrbot_plugin_bsk_browser/skill/browse-baidu.com/SKILL.md`（百度搜索、下一页定位与内容区滚动）
   - `astrbot_plugin_bsk_browser/skill/browse-cn.bing.com/SKILL.md`（必应搜索、下一页定位与内容区滚动）
6. 完善对应的单元测试，覆盖全屏截图令牌注入重试与 `bsk_inspect` 发图逻辑。

### Non-Goals
1. 不修改 `BrowserSkill` 外部工程源码或重新编译 `bsk` 二进制（所有修复均在 `astrbot_plugin_bsk_browser` 内完成）。
2. 不处理底层 Chromium Extension 对非激活后台标签页内置的 10 秒视口硬超时（[Builder Check 决议]：此项属于上游 `BrowserSkill` 扩展的既有设计限制，本期聚焦于全页截图自愈与发图连通性）。
3. 不在 `effect_state == "unknown"` 时进行盲目重试。

---

## 4. 详细设计与实现细节 (Detailed Design)

### 4.1 BskService 截图令牌注入与自动自愈 (`bsk/service.py`)

在 `screenshot` 和 `screenshot_ex` 中引入与 `interact` 对齐的观察令牌生命周期管理：

```python
# 1. 确定是否需要全屏截图
if full_page:
    # 前置尝试从缓存提取 observation 令牌
    obs_id = self._session_observations.pop(session_key, None)
    if obs_id:
        argv.extend(["--observation", obs_id])

# 2. 包装执行与错误捕获
async def _run_shot(current_argv: list[str]) -> BskResult:
    return await self.sessions.execute(
        session_key,
        lambda sid: self._with_tab_id(current_argv, tab_id) + ["--session", sid, "--json"],
        timeout=timeout,
        allow_uncertain=True,
    )

try:
    result = await _run_shot(argv)
except BskError as exc:
    reason = getattr(exc, "reason", "")
    effect_state = getattr(exc, "effect_state", "")
    if full_page and reason in ("cooperation_sync_required", "observation_required", "control_context_invalid") and effect_state != "unknown":
        self._logger.info("全页截图遇到控制上下文或令牌需同步 (%s)，执行 sync_session 补救", reason)
        obs = await self.sync_session(session_key, tab_id=tab_id)
        # 刷新令牌后重建 argv 并重试
        retry_argv = ["screenshot", "--out", str(out_path)]
        if ref:
            retry_argv.extend(["--ref", ref])
        retry_argv.append("--full-page")
        retry_argv.extend(["--observation", obs.observation_id])
        self._session_observations.pop(session_key, None)
        result = await _run_shot(retry_argv)
    else:
        raise
finally:
    if full_page:
        self._session_observations.pop(session_key, None)
```

### 4.2 bsk_inspect 异步生成器支持与发图 (`main.py`)

将 `bsk_inspect` 改造为支持流式返回图片和文字的异步生成器：

```python
@filter.llm_tool("bsk_inspect")
@_trace_tool_call("bsk_inspect")
async def bsk_inspect(self, event: AstrMessageEvent, **kwargs):
    denied = self._denied(event)
    if denied:
        yield self._fail(denied)
        return

    peek = tools_mod.normalize_args(kwargs)
    action = peek.get("action")

    if action == "screenshot":
        # 针对 screenshot 单独走截图并发送图片流程
        key = str(kwargs.get("session") or "").strip() or self._key(event)
        try:
            payload = await self.service.screenshot_ex(
                key,
                ref=peek.get("ref", ""),
                full_page=bool(peek.get("full_page", False)),
                tab_id=peek.get("tab_id"),
            )
        except BskError as exc:
            yield self._fail(f"截图失败：{exc.friendly}{exc.format_diagnostic()}")
            return
        except Exception as exc:
            astrbot_logger.exception("[bsk_browser] bsk_inspect screenshot 未预期错误")
            yield self._fail(f"截图时出现未预期的错误：{exc}")
            return

        message = payload.for_llm
        if payload.warning:
            message = f"{message}\n注意：{payload.warning}"

        try:
            yield event.image_result(payload.path)
        except Exception as exc:
            astrbot_logger.warning("[bsk_browser] bsk_inspect 发送截图失败：%r", exc)
            message = f"{message}\n（图片发送失败了，截图文件在：{payload.path}）"

        yield message
        return

    # 其他 5 个只读 action 正常走 _dispatch
    result = await self._dispatch("bsk_inspect", event, kwargs)
    yield result
```

> **兼容性说明**：`_trace_tool_call`（`main.py:356`）原生支持通过 `inspect.isasyncgenfunction` 自动包装异步生成器并统计耗时，无需改动切面装饰器。

### 4.3 工具文档与 Schema 提示优化 (`main.py` / `bsk/tools.py`)

1. **`bsk_inspect` 参数扩展与校验**：
   在 `bsk/tools.py` 的 `TOOL_SCHEMAS["bsk_inspect"]` 中正式增加可选属性 `full_page`（类型 boolean，说明：“当 action 为 screenshot 时生效：是否截取完整长页面”），并在 `_validate_inspect` 中将其与既有参数（`ref`、`tab_id` 等）一同解析并放行，避免未知参数报错。
2. **`delta_y` 参数提示**：
   明确文字：`"wheel：垂直滚动量，单位 CSS 像素。特别注意方向：【向下滚动】请务必传【正数】（如 delta_y=500）；【向上滚动】请务必传【负数】（如 delta_y=-500）。"`
3. **滚动工具选型提示**：
   在工具说明中强调：`"若目标是查看或点击页面中特定元素（如“下一页”按钮或搜索结果项），强烈推荐优先使用 action='scroll_to' 并传入目标 target='@eN'，比无目标的 wheel 更精确且不受页面布局拦截。"`

### 4.4 SKILL 文档体系构建

按 `AGENTS.md` 规范维护三份 SKILL 文档：

1. **`skill/bsk-browser/SKILL.md`**：
   - 增加**通用页面滚动技巧**章节：
     - 精确定位：先 `observe(query="关键词")` 获取 `@eN`，再 `scroll_to(target="@eN")` 将元素移入视口。
     - 区域滚动：调用 `wheel` 时尽量附带 `target="@eN"`，避免滚轮打在非滚动空白区域或固定悬浮窗上；牢记 `delta_y > 0` 为向下滚。
   - 增加**截图使用心智**章节：
     - 说明 `bsk_screenshot` 与 `bsk_inspect(action="screenshot")` 均会自动将图片发到聊天中。
     - 全屏长图请指定 `full_page=True`。
2. **`skill/browse-baidu.com/SKILL.md`**：
   - 导航与搜索：`bsk_page(navigate)` 进入 `https://www.baidu.com`，在输入框 fill 关键词并按回车或点击“百度一下”。
   - 结果结构说明：百度搜索结果集中在左侧容器 `#content_left`；右侧为热搜/广告。
   - 滚动与翻页实战：
     - 寻找下一页：调用 `bsk_inspect(action="observe", query="下一页")` 获取按钮的 `@eN`，随后直接调用 `bsk_interact(action="scroll_to", target="@eN")` 滚动到底部翻页区域。
     - 浏览结果：若需向下滚动，优先对结果卡片 `@eN` 执行 `wheel(target="@eN", delta_y=600)`。
3. **`skill/browse-cn.bing.com/SKILL.md`**：
   - 导航与搜索：`https://cn.bing.com`，输入框与提交按钮交互。
   - 结果结构说明：主搜索结果在 `#b_results`。
   - 滚动与翻页：使用 `scroll_to` 瞄准分页栏或下一页链接；滚轮滚动指定结果容器。

---

## 5. 验证与测试计划 (Verification Plan)

### 5.1 自动化单元测试
- **测试 1：全屏截图令牌注入与正常消费** (`tests/test_screenshot_observation.py`)
  - 构造包含 `self._session_observations["s1"] = "obs-123"` 的 Service；
  - 调用 `service.screenshot("s1", full_page=True)`，验证传给 bsk 的命令行包含 `--full-page` 和 `--observation obs-123`；
  - 验证调用后 `_session_observations` 中对应 session 的令牌已被清理。
- **测试 2：全屏截图遇到 observation_required 自动自愈重试**
  - 模拟首次执行抛出 `BskError(reason="observation_required", effect_state="none")`；
  - 验证 Service 自动调用 `sync_session` 并拿到 `obs-fresh`，随后以 `--observation obs-fresh` 重新发起命令行执行并最终成功返回。
- **测试 3：`bsk_inspect(action="screenshot")` 发图与文字回执**
  - 验证当 `action="screenshot"` 时，生成器先后 `yield` 了 `event.image_result(path)` 与文字描述；
  - 验证当 `action="observe"` 时，生成器仅 `yield` 字符串结果。

### 5.2 兼容性与回归测试
- 运行现有的全部测试套件（`pytest tests/`），确保既有工具逻辑、日志切面与会话管理不受破坏。
