# Design Document: Tab Leak Fix and Configuration Schema Refinement

- **Date**: 2026-11-15
- **Author**: Assistant & User
- **Status**: Draft / Proposed

---

## 1. Intent and Why

在实际运行与日志分析（`logs/astrbot-2026-11-15-17.54.log`）中，发现了若干亟待改进的问题：
1. **技能目录命名不规范**：`skills/` 目录下的百度与必应技能目录包含了域名后缀（如 `bsk-browse-baidu.com`），不符合 `AGENTS.md` 规范要求的 `bsk-browse-baidu` 与 `bsk-browse-bingcn`。
2. **网站白名单配置体验繁琐且文案啰嗦**：用户设置中关于 `site_whitelist` 的标题和描述冗长；同时普通用户白名单中的 `allowed_actions` 缺少下拉可选项，用户需手动输入字符串，缺乏层级感和易用性。
3. **点击外链弹出的标签页残留泄漏**：机器人在页面（如百度搜索）中点击带有 `target="_blank"` 的搜索结果时，浏览器弹出新标签页。会话退出或超时回收时，由于底层 BrowserSkill 协作控制机制对未带同步凭据（`observation_id`）的 `tab close` 命令进行权限拦截（`observation_required`），导致临时标签页未能关闭，进而触发扩展内部的 `dropOnly: true` 保护，使浏览器窗口无法销毁并残留于桌面（如 `logs/astrbot-2026-11-15-16.45.png`）。

本设计的目的是一次性规范技能命名、重构配置体验为层级化下拉菜单，并从根本上解决临时标签页关闭与会话销毁残留缺陷。

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **G1**: 将 `skills/` 下的技能目录规范重命名为 `bsk-browse-baidu` 与 `bsk-browse-bingcn`，同步更新 SKILL.md、相关测试与文档引用。
- **G2**: 精炼 `_conf_schema.json` 中网站规则与白名单的标题和描述文案，做到准确、简洁、表意清晰。
- **G3**: 为 `allowed_actions` 提供二级树形展示的下拉多选选项（`options`、`labels`、`subtitles`），父级为工具名称（如 `bsk_interact:`），子级为带 4 空格缩进的具体动作（如 `    fill`、`    press`），并保证与 AstrBot 原生 `<v-autocomplete chips multiple>` 完全兼容。
- **G4**: 修复外链弹出标签页泄漏缺陷：
  - 会话扫尾清理（`sweep_agent_tabs` 与 `SessionManager._stop_entry`）在关闭多余标签页前，先调用 `bsk sync` 获取最新 `context_id` 与 `observation_id`，并带参调用 `tab close`，突破 `observation_required` 限制；
  - 在 `detect_new_tabs_and_switch` 中引入状态同步机制，消除由于窗口控制状态滞后导致的 `tab select` 失败，保证点击后焦点顺利切换至新标签页。
- **G5**: 保持 `astrbot_plugin_bsk_browser` 全量单元测试 100% 通过，并为新增行为补充测试用例。

### Non-Goals
- 修改 AstrBot 核心仓库（`AstrBot/`）或前端 Dashboard 代码（仅在插件仓库内通过 `_conf_schema.json` 的标准能力实现）。
- 更改底层 `BrowserSkill` 二进制协议或修改 `bsk` 命令行源码。
- 改变管理员用户的直接放行权限模型。

### Anti-Goals
- 采用暴力强杀系统进程等危险方式关闭窗口，以免误杀宿主机用户正在日常使用的其他浏览器窗口。
- 引入破坏现有白名单历史配置的不兼容数据结构变更。

---

## 3. Constraints

1. **唯一修改主体**：根据 `AGENTS.md`，`./astrbot_plugin_bsk_browser/` 是唯一可修改的仓库。
2. **日志规范**：严格使用 AstrBot 日志系统，工具调用与 bsk 指令交互输出在 `DEBUG` 级别。
3. **前端渲染兼容性**：AstrBot Dashboard 的 `ConfigItemRenderer.vue` 对 `type: "list"` 且含有 `options` 的配置项采用 `<v-autocomplete multiple chips>` 渲染。HTML 规范默认会折叠连续普通空格，故二级缩进必须采用 Unicode 不折叠空格（`\u00A0\u00A0\u00A0\u00A0`）。
4. **Git 版本管理**：修改完成后必须执行 git commit。

---

## 4. Approaches

### 4.1 二级多选下拉呈现方式

- **方案 A（选中 - 不折叠空格缩进 + 单字段层级映射）**：
  保持 `site_rule.allowed_actions` 为单一 `list` 类型字段，配置完整的 `options`、`labels` 和 `subtitles`。
  `labels` 中：
  - 父分类项形如 `bsk_interact:`，对应值为 `bsk_interact.*`（选择后一键放行该模块所有动作）；
  - 子项形如 `\u00A0\u00A0\u00A0\u00A0click`、`\u00A0\u00A0\u00A0\u00A0fill`，对应值为 `bsk_interact.click`、`bsk_interact.fill` 等；
  - `subtitles` 补充中文操作说明与对应工具。
  *优点*：无需更改现有存储结构，向前兼容，完美利用 AstrBot 原生 Autocomplete 组件实现多选与搜索，视觉上具备清晰的父子树状缩进。
- **方案 B（拆分为多个独立的配置项）**：
  在 `site_rule` 中为交互、检查、导航、标签等工具分别开辟多选字段。
  *缺点*：严重破坏现有配置数据结构，且在模板列表中造成表单过长、视觉繁琐，违背用户直觉。

*决策*：采纳 **方案 A**。

### 4.2 标签页关闭与凭证闭环

- **方案 1（闭环主动同步换取凭证，选中）**：
  在需要执行 `tab close <tid>` 之前（包括 `BskService.sweep_agent_tabs`、`BskService.tabs("close")`、`SessionManager._stop_entry`），先调用 `bsk sync --session <sid> --tab-id <tid> --json` 获取专属 `context_id` 与 `observation_id`，再追加参数 `--context <context_id> --observation <observation_id>` 调用 `tab close`。成功关闭后，BrowserSkill 内部的 `ctx.observedTabs` 被清空，后续 `session stop` 执行时判定不再存在用户标签页，从而顺利销毁整个 Agent 窗口。
  *优点*：完全顺应 BrowserSkill 底层安全与协作状态机，彻底消除 `observation_required` 报错与 `dropOnly: true` 残留。
- **方案 2（忽略清理失败并依赖宿主机清理）**：
  仅记录日志而不解决凭证问题。
  *缺点*：问题依然存在，用户桌面将持续堆积无法自动关闭的空白或孤儿标签页窗口。

*决策*：采纳 **方案 1**。

---

## 5. Detailed Design & Changes

### 5.1 技能目录规范重命名与引用更新
1. 目录重命名：
   - `astrbot_plugin_bsk_browser/skills/bsk-browse-baidu.com` $\rightarrow$ `astrbot_plugin_bsk_browser/skills/bsk-browse-baidu`
   - `astrbot_plugin_bsk_browser/skills/bsk-browse-cn.bing.com` $\rightarrow$ `astrbot_plugin_bsk_browser/skills/bsk-browse-bingcn`
2. 技能文档维护：
   - 更新对应子目录下的 `SKILL.md`，检查 frontmatter 中的 `name`、`description` 字段。
   - 检查核心技能文档 `skills/bsk-browser/SKILL.md`，修正内部对这两个专精技能目录名称的引用与导引。
3. 单元测试同步：
   - 更新 `tests/test_skills_doc.py` 中对技能目录名称的断言与测试集合。

### 5.2 `_conf_schema.json` 文案精炼与树形多选
重构 `site_whitelist` 配置定义：
1. **文案精炼**：
   - `description`: "普通用户网站与操作白名单"
   - `hint`: "仅在关闭「只允许管理员使用」时生效。限制普通用户可访问的域名及其允许调用的页内操作。未在名单内的域名将被禁止访问。"
   - `templates.site_rule.name`: "网站授权规则"
   - `domain.description`: "允许访问的网站域名（例如 baidu.com、cn.bing.com）"
   - `allowed_actions.description`: "允许调用的页内操作（留空表示仅允许打开浏览，禁止一切页内操作）"
2. **二级树形下拉多选配置**：
   - 为 `allowed_actions` 添加 `options`、`labels`、`subtitles`：
   - 涵盖常用 4 大工具类别：
     - `bsk_interact:`（通配 `bsk_interact.*`）及其子动作：`click`、`fill`、`press`、`scroll`、`hover`、`drag`、`select`、`focus`、`blur`
     - `bsk_inspect:`（通配 `bsk_inspect.*`）及其子动作：`observe`、`text`、`search`、`screenshot`、`full_page`、`table`、`console`
     - `bsk_page:`（通配 `bsk_page.*`）及其子动作：`navigate`、`reload`、`back`、`forward`
     - `bsk_tabs:`（通配 `bsk_tabs.*`）及其子动作：`list`、`select`、`create`、`close`
   - `labels` 中父项使用顶格 `工具名:`，子项使用 `\u00A0\u00A0\u00A0\u00A0动作名`。

### 5.3 标签页安全清理与焦点切换闭环
1. **`BskService.tabs(action="close")` 与 `sweep_agent_tabs`**：
   - 在执行 `tab close <tid>` 前，先执行同步：
     ```python
     sync_res = await self.sync(session_key, tab_id=tid)
     ```
     获取其 `context_id` 与 `observation_id`。
   - 在构造 `tab close` 命令行时携带 `--context <context_id> --observation <observation_id>`。
2. **`SessionManager._stop_entry`**：
   - 在停止会话前扫描 Agent Window 标签页列表；
   - 对列表中所有除保留项以外的多余标签页，依次执行带凭证的关闭命令：
     ```python
     sync_res = await self._runner.run(
         ["sync", "--session", entry.session.session_id, "--tab-id", str(tid), "--json"],
         timeout=5.0,
     )
     # 提取 context_id 与 observation_id
     # 带参执行 tab close
     ```
   - 若同步或关闭失败，安全捕获并记录 DEBUG 日志，继续关闭下一个。
3. **`detect_new_tabs_and_switch`**：
   - 发现新增标签页时，先调用 `await self.sync(session_key, tab_id=new_tab_id)` 协调窗口与控制权状态；
   - 随后再执行 `await self.tabs(session_key, "select", tab_id=new_tab_id)`，消除因状态未同步引起的拒绝切换。

---

## 6. What's Left to the Builder

- 确保 `test_config.py` 与 `test_permissions_integration.py` 覆盖更新后的 `_conf_schema.json` 结构与 `allowed_actions` 选项值。
- 为 `test_tab_lifecycle_cleanup.py` 添加带凭据关闭标签页的单元测试（模拟 `sync` 返回凭据并传递给 `tab close`）。
- 确保所有相关文件和模块均遵守 `AGENTS.md` 中的规范（包括精炼表义、DEBUG 日志格式和 git commit 要求）。
