# BSK 全截屏自愈、发图统一与页面滚动引导实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复全截屏在 cooperate 模式下的观察令牌（`observation_id`）鉴权失败与自愈重试，打通 `bsk_inspect` 与 `bsk_screenshot` 的图片向用户直接发送能力，完善滚动方向与定位工具选型引导，并按规范编写 Baidu / Bing 搜索专属 SKILL 指南。

**Architecture:** 
1. 在服务层 `BskService` 中为 `screenshot` / `screenshot_ex` 补齐全屏截图令牌消费（`_session_observations`）与在 `observation_required` / `cooperation_sync_required` 下自动 `sync_session` 刷新重试机制；
2. 在工具层 `bsk/tools.py` 为 `bsk_inspect` 增加 `full_page(boolean)` 可选参数支持与校验，并在各工具 schema 中明确 `delta_y` 滚动方向与推荐 `scroll_to`；
3. 在入口层 `main.py` 将 `bsk_inspect` 重构成异步生成器，在 `action="screenshot"` 时先后 yield `event.image_result` 与文字描述；
4. 按 `AGENTS.md` 规范维护三份 SKILL 文档并完成全量回归。

**Tech Stack:** Python 3.10+, AstrBot plugin SDK, AsyncIO, Unittest/Pytest.

**Spec:** [2026-11-15-bsk-screenshot-and-scroll-resilience-design.md](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-bsk-screenshot-and-scroll-resilience-design.md)

## Global Constraints

- 不修改 `BrowserSkill` 外部工程源码或重新编译 `bsk` 二进制（`astrbot_plugin_bsk_browser` 是唯一要修改的仓库）。
- 不破坏已有工具的公共参数向后兼容性。
- 日志输出严格遵守 AGENTS.md 要求：以 DEBUG 等级输出 bsk 指令输入输出及工具调用会话与工具名。
- 每个 Task 完成后保持代码整洁并通过测试，最终确保代码全部提交到 git。

## Review Focus

1. **全页长图截屏后缓存污染**：全屏截图操作本身会触发页面滚动并消耗底层令牌，无论成功或失败都必须在 `finally` 中清空会话的 `_session_observations` 缓存。
2. **`effect_state: unknown` 禁止盲目重试**：遇到未决异常时绝不能重新发起截图指令，避免重复阻塞或状态污染。
3. **`bsk_inspect` 异步生成器兼容性**：改造为异步生成器后，`_trace_tool_call` 与其他 5 个只读 action（`observe`, `snapshot`, `html`, `console`, `network`）必须能够正常流式 yield 文本输出，不丢失工具结束日志。
4. **`tools.validate` 对 `full_page` 的放行**：模型通过 `bsk_inspect(action="screenshot", full_page=True)` 调用时，必须被合法放行，且当 action 不为 screenshot 时若传入 `full_page` 应被明确报错。
5. **发图异常不阻断文本回灌**：若 `event.image_result(...)` 因平台原因抛出异常，必须平稳降级为在文本中说明并正常 yield 文本给模型，不可抛出崩溃。

---

### Task 1: 服务层全屏截图令牌注入与自动自愈 (Service Layer Resilience)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/service.py:1186-1215`, `3355-3385`
- Test: `astrbot_plugin_bsk_browser/tests/test_screenshot_resilience.py`

**Interfaces:**
- Consumes: `self._session_observations: dict[str, str]`, `self.sync_session(session_key, tab_id)`
- Produces: `screenshot(key, *, full_page=False) -> ShotPayload`, `screenshot_ex(key, *, ref="", full_page=False, tab_id=None, observation=None) -> ShotPayload`

- [ ] **Step 1: 编写失败的单元测试**

在 `tests/test_screenshot_resilience.py` 中编写以下测试用例：
1. `test_screenshot_full_page_consumes_cached_observation_id`：验证全屏截图正常提取并消费 `_session_observations` 中的令牌，拼接到 `--observation <id>`；
2. `test_screenshot_full_page_recovers_from_observation_required`：验证当底层抛出 `BskError(reason="observation_required")` 时，自动触发 `sync_session` 获取新令牌并成功重试；
3. `test_screenshot_ex_full_page_supports_explicit_and_cached_observation`：验证 `screenshot_ex` 传入显式 `observation` 或走缓存时的行为与自愈。

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_screenshot_resilience.py -v`  
预期：FAIL（`screenshot` 未带 `--observation`，且抛出异常未被捕获重试）

- [ ] **Step 3: 实现 `BskService.screenshot` 与 `screenshot_ex` 的令牌注入与自愈逻辑**

在 `bsk/service.py` 中：
1. 在 `screenshot` 与 `screenshot_ex` 中，当 `use_full_page` 为 True 时，优先提取 `observation`（显式传入或从 `_session_observations.pop(session_key, None)` 取出）；若存在则向 `argv` 添加 `["--observation", obs_token]`；
2. 将 `sessions.execute` 包装在 try 块中；若捕获 `BskError`，且 `full_page` 为 True、`reason in ("cooperation_sync_required", "observation_required", "control_context_invalid")` 且 `effect_state != "unknown"`：
   - 记录 info 日志；
   - 调用 `obs = await self.sync_session(session_key, tab_id=tab_id)`；
   - 重新构建 `retry_argv` 并注入 `["--observation", obs.observation_id]`；
   - 重新执行命令；
3. 在 `finally` 块中，当 `full_page` 为 True 时，执行 `self._session_observations.pop(session_key, None)`。

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_screenshot_resilience.py -v`  
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add bsk/service.py tests/test_screenshot_resilience.py
git commit -m "feat(bsk): add observation injection and auto-sync retry to full-page screenshot"
```

---

### Task 2: 工具参数定义扩展与 Schema 提示词优化 (Tools Schema & Validation)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/bsk/tools.py:610-705`, `1400-1430`
- Test: `astrbot_plugin_bsk_browser/tests/test_tools.py`

**Interfaces:**
- Consumes: `TOOL_SCHEMAS["bsk_inspect"]`, `_validate_inspect`
- Produces: 支持 `full_page` 验证与归一化的 `validate("bsk_inspect", raw)`

- [ ] **Step 1: 编写失败的单元测试**

在 `tests/test_tools.py` 中增加对 `bsk_inspect` 参数校验的断言：
1. 验证 `validate("bsk_inspect", {"action": "screenshot", "full_page": True})` 解析通过且返回字典中包含 `full_page=True`；
2. 验证当 `action="observe"` 时传入 `full_page=True` 会抛出 `BskToolError` 提示不属于 observe。

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_tools.py -k "test_inspect_full_page" -v`  
预期：FAIL（`bsk_inspect 不认识以下参数：full_page`）

- [ ] **Step 3: 修改 `bsk/tools.py`**

1. 在 `TOOL_SCHEMAS["bsk_inspect"]["parameters"]["properties"]` 中添加 `full_page`:
   ```python
   "full_page": _p("boolean", "screenshot 专用：设为 true 截取整个长页面，默认只截视口。"),
   ```
2. 在 `_validate_inspect` 中：
   - 将 `full_page` 计入 `known` 白名单；
   - 在 `action == "screenshot"` 分支中解析 `full_page`：`out["full_page"] = ctx.as_bool("full_page", False)`；
   - 在非 screenshot 分支若提供 `full_page`，调用 `ctx.fail(...)` 拒绝；
3. 更新 `delta_y` 参数说明文字与工具顶层描述：
   - 强化明确：`"wheel：垂直滚动量，单位 CSS 像素。特别注意方向：想要页面【向下滚动】请务必传【正数】（如 delta_y=500）；想要页面【向上滚动】请务必传【负数】（如 delta_y=-500）。"`
   - 增加关于 `scroll_to` 的首选建议文案。

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_tools.py -v`  
预期：全部 PASS

- [ ] **Step 5: 提交代码**

```bash
git add bsk/tools.py tests/test_tools.py
git commit -m "feat(bsk): add full_page parameter to bsk_inspect schema and clarify delta_y scroll directions"
```

---

### Task 3: `bsk_inspect` 异步生成器支持与发图连通 (Streaming Image Delivery)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/main.py:1635-1670`, `1985-2015`, `2170-2210`
- Test: `astrbot_plugin_bsk_browser/tests/test_inspect_screenshot_image.py`

**Interfaces:**
- Consumes: `service.screenshot_ex`, `event.image_result`
- Produces: `async def bsk_inspect(...) -> AsyncGenerator`

- [ ] **Step 1: 编写失败的单元测试**

创建 `tests/test_inspect_screenshot_image.py`：
1. 模拟 `bsk_inspect(action="screenshot")` 调用，断言返回的 AsyncGenerator 先 yield 了 `event.image_result(path)`，随后 yield 了包含页面尺寸的文本描述；
2. 模拟 `bsk_inspect(action="observe")` 调用，断言返回的 AsyncGenerator 仅 yield 了一次字符串文本；
3. 模拟发图异常（`event.image_result` 抛出），断言未引发崩溃且文本中包含降级提示。

- [ ] **Step 2: 运行测试验证失败**

运行：`pytest tests/test_inspect_screenshot_image.py -v`  
预期：FAIL（`bsk_inspect` 是普通协程函数，不是 AsyncGenerator）

- [ ] **Step 3: 重构 `main.py` 中的 `bsk_inspect` 及相关 docstring**

1. 将 `bsk_inspect` 改造成异步生成器：
   - 检查权限 `_denied`，未通过时 yield 错误信息并退出；
   - 归一化参数，检查 `action == "screenshot"`；
   - 若是 `screenshot`，调用 `service.screenshot_ex`，成功后依次 `yield event.image_result(payload.path)` 和 `yield message`；发图异常时记录警告并降级处理；
   - 若是其他 action，调用 `await self._dispatch("bsk_inspect", event, kwargs)` 并 `yield result`；
2. 在 `main.py` 的 `bsk_interact` 函数签名 docstring 中同步更新 `delta_y` 方向和 `scroll_to` 优先建议说明。

- [ ] **Step 4: 运行测试验证通过**

运行：`pytest tests/test_inspect_screenshot_image.py -v`  
预期：PASS

- [ ] **Step 5: 提交代码**

```bash
git add main.py tests/test_inspect_screenshot_image.py
git commit -m "feat(bsk): enable streaming image delivery in bsk_inspect screenshot"
```

---

### Task 4: 编写与更新三份 SKILL 文档 (Documentation Suite)

**Files:**
- Modify: `astrbot_plugin_bsk_browser/skill/bsk-browser/SKILL.md`
- Create: `astrbot_plugin_bsk_browser/skill/browse-baidu.com/SKILL.md`
- Create: `astrbot_plugin_bsk_browser/skill/browse-cn.bing.com/SKILL.md`

**Interfaces:**
- Consumes: AGENTS.md 规范与工具实际参数机制
- Produces: 标准化的机器人自动化指南 Markdown 文件

- [ ] **Step 1: 完善 `skill/bsk-browser/SKILL.md`**

补充通用浏览器使用技巧：
1. 滚动技巧：精确元素定位优先用 `bsk_interact(action="scroll_to", target="@eN")`；滚轮 `wheel` 必须注意正负数方向（正数向下、负数向上），并推荐带上容器 `target`；
2. 截图技巧：`bsk_screenshot` 与 `bsk_inspect(action="screenshot")` 均能直接向聊天发送图片；截长图添加 `full_page=True`；
3. 资源管理：操作完毕必须及时调用 `bsk_session(action="stop")` 释放窗口与标签页。

- [ ] **Step 2: 创建 `skill/browse-baidu.com/SKILL.md`**

严格满足 AGENTS.md 要求：
1. 首页与搜索结果页结构特征（`#content_left` 主内容区与右侧推荐区分）；
2. 准确查找输入框与“百度一下”搜索按钮；
3. 正确滚动搜索页面（优先用卡片 `@eN` 或 `#content_left` 作为 wheel 的 target）；
4. 识别上一页、下一页及页码直达按钮，并指明使用 `scroll_to` 直达下一页按钮。

- [ ] **Step 3: 创建 `skill/browse-cn.bing.com/SKILL.md`**

严格满足 AGENTS.md 要求：
1. 必应首页与搜索结果页结构特征（`#b_results` 主内容区）；
2. 准确查找输入框与搜索按钮；
3. 正确滚动搜索页面（针对 `#b_results` 容器滚动）；
4. 识别底部分页栏、上一页与下一页按钮，指导使用 `scroll_to` 定位。

- [ ] **Step 4: 审查文档格式与完整性**

检查各 SKILL.md 的 YAML 前置元数据（name / description）、结构层次与可读性。

- [ ] **Step 5: 提交代码**

```bash
git add skill/
git commit -m "docs(skill): update bsk-browser guide and add browse-baidu.com and browse-cn.bing.com skills"
```

---

### Task 5: 全量回归测试与收尾验证 (Full Verification)

**Files:**
- Test: 全量单元测试套件

- [ ] **Step 1: 运行全量 pytest 单元测试**

运行：`pytest tests/ -v`  
预期：所有测试全部通过（0 failure, 0 error）

- [ ] **Step 2: 验证 Git 工作区状态**

运行：`git status`  
预期：工作区干净，无未暂存或未跟踪文件。

- [ ] **Step 3: 最终确认提交**

确保所有任务均已完整 commit 并在提交记录中反映。
