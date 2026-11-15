# 截图压缩配置、长截图截断防超时与网站白名单权限系统设计

## 1. 目标与背景 (Intent & Why)

当前 `astrbot_plugin_bsk_browser` 插件在实际使用中存在三个需要解决的问题与需求：
1. **截图体积与传输选择**：此前截图优化流水线无条件将所有截图转为 JPEG 格式，导致追求高清画质的原图需求被覆盖；用户需要能够自由选择“直发原始 PNG”或“压缩为指定质量的 JPEG”。
2. **瀑布流页面长截图死循环超时**：在 B 站（Bilibili）等包含无限滚动瀑布流的网站上执行 `full_page=True` 时，底层的 `bsk screenshot --full-page` 默认采用 `--scope follow`，持续滚动并动态加载更多内容，导致长截图永远无法触底直至 120 秒超时失败。需要提供模式选择（`--scope current`）以及最大长度截断保护（`fullpage_max_height`）。
3. **普通用户网站与细粒度工具权限控制**：在机器人主希望对外开放浏览器能力（关闭 `admin_only`）时，不能盲目放开所有网页与所有工具能力。必须建立网站白名单系统，由管理员指定普通用户可访问的域名及在该域名下允许使用的工具子操作（覆盖 `bsk_session`、`bsk_page`、`bsk_inspect`、`bsk_interact`、`bsk_tabs` 五大工具）；同时高危与内部工具（`bsk_load_tools`、`bsk_debug`、`bsk_assist`、`bsk_status`、`bsk_evaluate`）无条件对普通用户禁绝。

## 2. 目标、非目标与反目标 (Goals, Non-Goals, Anti-Goals)

### 目标 (Goals)
- **截图压缩可配置**：
  - 新增 `screenshot_compress_to_jpg`（布尔，默认 `false`，即默认不压缩直接发送原图 PNG）；
  - 新增 `screenshot_quality`（整数 1~100，默认 `85`，滑块可调）；
  - 仅在 `screenshot_compress_to_jpg=true` 时执行降采样和 JPEG 转换，关闭时保留原始 PNG。
- **长截图防超时与自动截断**：
  - 新增 `fullpage_scope`（字符串，可选 `current` / `follow`，默认 `current`）；在全页截图时向 `bsk screenshot --full-page` 传递 `--scope <scope>`；
  - 新增 `fullpage_max_height`（整数像素，默认 `8000`，`0` 表示不截断）；
  - 全页截图生成后，若图片实际高度超出 `fullpage_max_height`，使用 Pillow 自动进行垂直截断裁切，保留顶部内容并在回执与警告中明确提示“已截断至最大长度 {max_height}px”。
- **细粒度网站与工具白名单权限系统**：
  - 在 `_conf_schema.json` 中使用 `template_list` 引入 `site_whitelist`，每条规则包含 `domain` 与 `allowed_actions`；
  - 当 `admin_only=false` 且请求者非管理员时生效；
  - 硬性隔离：`bsk_load_tools`、`bsk_debug`、`bsk_assist`、`bsk_status`、`bsk_evaluate` 无论如何配置，对普通用户一律不可见、不可调用；在 `_dispatch` 前置硬拦截，同时在 `on_llm_request` 中针对非管理员动态剔除这些工具，节省上下文 Token；
  - 域名即导航权：将某域名加入白名单，即代表允许普通用户通过 `bsk_session.open` 或 `bsk_page.navigate` 访问该域名；`allowed_actions` 专精于控制进入该域名后的**页内具体操作**；
  - 基础生命周期无死锁放行：`bsk_session.start`、`bsk_session.stop`、`bsk_session.list`、`bsk_session.sync` 以及 `bsk_tabs.list`、`bsk_tabs.select`、`bsk_tabs.close` 作为会话运维与标签页管理的基础动作放行，确保状态可同步、异常与外链可关闭、资源可回收；
  - 页内操作与外链跳转校验：`bsk_interact.*`、`bsk_inspect.*` 等实时基于活动标签页 URL 校验域名与动作；任何可能引发页面跳转的操作后将当前 URL 缓存标记为失效，下次页内鉴权自动查询最新真实 URL，杜绝内联 302 重定向逃逸；
  - 权限审计日志：对每一次普通用户触发的白名单校验，均以 DEBUG 级别记录发送者、会话、当前域名、动作及判决结果。
- **文档与 SKILL 维护**：
  - 在 `SKILL.md` 及文档中详细列明 5 个允许工具的全部子操作及其具体作用；
  - 更新配置说明与架构文档。

### 非目标 (Non-Goals)
- 不修改 `bsk` 外部二进制命令源码（充分利用已有参数 `--scope` 及外部图片处理）。
- 不引入终端聊天的交互式授权弹窗（所有授权均由插件管理员在 WebUI 预先配置）。
- 不改变既有管理员在 `admin_only=true` 或在 `allowed_users` 中的不受限使用体验。

### 反目标 (Anti-Goals)
- 严禁因关闭 `admin_only` 而隐式向普通用户开放任何静默执行 JS、网络抓包拦截、或者窗口模拟等高危能力。
- 严禁点击搜索结果外链跳转到内网或非白名单网站后，普通用户仍能继续在该未授权网页上进行点击或读取操作。
- 严禁因拦截外链而导致标签页无法被 `tabs.close` 关闭，造成窗口死锁无法释放。
- 严禁在环境缺失 Pillow 时引发未捕获崩溃（必须安全降级，返回原图并记入日志）。

## 3. 架构方案抉择 (Approaches)

### 方案 A：WebUI 原生 `template_list` 配置 + 实时会话 URL 状态感知校验（选中）
- **实现方式**：
  - 配置采用 AstrBot 标准的 `template_list` 渲染，插件管理员在 WebUI 中可视化增删网站规则；
  - 在插件生命周期与会话管理中实时同步/缓存当前活动标签页的 URL，并在交互可能跳转后自动失效更新；
  - 在统一入口 `_dispatch` 前置执行权限门拦截，配合 `on_llm_request` 动态优化提示词。
- **优点**：界面体验优秀，具备动态外链跳转防御与死锁规避机制，审计完备。
- **缺点**：需在 `service.py` / `session.py` 中追踪活跃 URL。

### 方案 B：纯文本多行解析 + 静态导航会话标记（废弃）
- **废弃原因**：管理员手工输入容易语法出错，且会话一旦建立就打上静态标记，页面被跳转到未授权外部网页时无法识别，存在严重的越权漏洞。

## 4. 详细技术实现设计 (Detailed Implementation Specification)

### 4.1 配置系统扩展 (`_conf_schema.json` & `bsk/config.py`)

在 `_conf_schema.json` 增加以下配置项：
1. `screenshot_compress_to_jpg`：
   - 类型：`bool`，默认 `false`
   - 描述：“截图压缩为 JPG 格式”
   - 提示：“开启后会将截图压缩为指定质量的 JPEG 格式，以减小体积并加速发送；关闭时直接发送无损原始 PNG 截图（默认关闭，保持最高画质）。”
2. `screenshot_quality`：
   - 类型：`int`，默认 `85`，slider 范围 `1..100`，步长 `5`
   - 描述：“JPG 压缩质量”
   - 提示：“当开启「截图压缩为 JPG 格式」时生效。默认 85，可在 1~100 之间调节。”
3. `fullpage_scope`：
   - 类型：`string`，默认 `"current"`，options: `["current", "follow"]`
   - 描述：“全页截图高度策略”
   - 提示：“整页长截图时的滚动策略。current（默认）：仅截取触发截图时测得的初始文档高度，即便滚动到底部也不会无限加载新内容，可有效防止 B 站等瀑布流网站长截图超时卡死；follow：跟随页面滚动无限加载新内容直到自然触底，若页面为无限滚动可能导致超时。”
4. `fullpage_max_height`：
   - 类型：`int`，默认 `8000`，slider 范围 `0..30000`，步长 `500`
   - 描述：“全页截图最大长度限制（像素）”
   - 提示：“全页截图生成后的最大允许高度（像素）。若截图超过该高度，插件会自动将超出部分截断，避免生成几十 MB 的超大长图导致发送失败。设为 0 表示不限制最大高度。”
5. `site_whitelist`：
   - 类型：`template_list`
   - 模板定义：
     ```json
     {
       "type": "template_list",
       "description": "网站与工具操作白名单（非管理员）",
       "hint": "当关闭「只允许管理员使用」（admin_only）时生效。为普通用户配置可以浏览哪些网站，以及在访问这些网站时允许调用哪些具体工具操作。不在白名单内的网站将被禁止访问。",
       "templates": {
         "site_rule": {
           "name": "网站规则",
           "display_item": "domain",
           "items": {
             "domain": {
               "description": "允许的网站域名或主机名（例如 baidu.com、cn.bing.com）",
               "type": "string",
               "default": ""
             },
             "allowed_actions": {
               "description": "允许的具体页内操作（格式：工具.动作 如 bsk_interact.click，或简写 click，或通配符 bsk_interact.*；留空表示仅允许打开浏览但禁止点击/输入/截图等页内操作）",
               "type": "list",
               "items": { "type": "string" },
               "default": []
             }
           }
         }
       }
     }
     ```

在 `bsk/config.py` 的 `BskSettings` 中补充对应强类型字段、解析逻辑与校验规则。

### 4.2 截图处理流水线 (`bsk/shots.py` & `bsk/service.py`)

1. **CLI 传参增强**：
   在 `service.screenshot_ex` 中，若 `use_full_page` 为 True，构建参数：
   `bsk screenshot --full-page --scope <settings.fullpage_scope> ...`
2. **截断与压缩流程**：
   截图由 `bsk` 生成并校验通过（`ok=True`）后，在 `service.py` 中：
   - **高度截断**：
     若 `use_full_page` 且 `settings.fullpage_max_height > 0`：
     检查图片高度（通过 Pillow 打开读取），若 `height > settings.fullpage_max_height`：
     截取 `image.crop((0, 0, width, settings.fullpage_max_height))`，保存回原路径（或生成截断文件），更新 `shot.height`、`shot.byte_size`，并附加警告说明 `f"（截图已自动截断至最大长度 {settings.fullpage_max_height}px）"`。
   - **按需压缩**：
     若 `settings.screenshot_compress_to_jpg` 为 True：
     调用 `compress_and_optimize_image(shot.path, quality=settings.screenshot_quality)`；
     若为 False：不调用压缩转换，直接维持原始 PNG 格式输出。

### 4.3 细粒度白名单权限控制引擎 (`main.py`, `bsk/service.py`, `bsk/session.py`)

1. **生命周期基础操作放行（防死锁与保障正常使用）**：
   以下基础运维操作对普通用户默认放行，无需在 `allowed_actions` 中繁琐配置：
   - 会话控制：`bsk_session.start`、`bsk_session.stop`、`bsk_session.list`、`bsk_session.sync`（同步控制权）；
   - 标签页运维：`bsk_tabs.list`、`bsk_tabs.select`（切焦）、`bsk_tabs.close`（关闭当前标签页，包括误入的外链标签页）。
   > 注：`bsk_tabs.create`、`borrow`、`return` 仍受严格限制。
2. **域名即导航权**：
   - 当调用 `bsk_session.open` 或 `bsk_page.navigate` 时，提取目标 URL 域名；
   - 只要目标域名在 `site_whitelist` 中，即允许导航；
   - 若目标域名不在白名单中，立即拒绝：“目标网站（{target_domain}）不在允许访问的白名单中。”
3. **活动 URL 感知与防内联跳转逃逸**：
   - 在 `BskService` 中维护各会话的 `current_url: str` 与 `url_dirty: bool`；
   - 导航（`open`/`navigate`）成功时立即更新 `current_url` 并清空 dirty 标记；
   - 交互操作（`click`、`press`、`reload`、`back`、`forward`、`wait`）执行后，将 `url_dirty = True`；
   - 页内鉴权（`interact`、`inspect` 等）时，若 `url_dirty` 为 True，先调用轻量 `tab list` 刷新当前活动标签页的真实 URL 并重置 dirty；
   - 比对真实 URL 域名是否在 `site_whitelist` 中：
     - 若不在：拦截操作并提示“当前页面已跳转至未授权域名（{current_domain}），操作被拦截，请关闭当前标签页或后退。”
     - 若在：比对动作是否在 `allowed_actions` 中，不在则拒绝。
4. **硬性黑名单双层防护**：
   - 第一层（提示词层）：在 `main.py` 的 `@filter.on_llm_request()` 中，若当前调用者非管理员，从 `req.func_tool` 中动态移除 `bsk_load_tools`、`bsk_debug`、`bsk_assist`、`bsk_status`、`bsk_evaluate` 5 个工具定义；
   - 第二层（执行门禁）：在 `_dispatch` 前置硬拦截，直接拒绝并记录安全警告。
5. **审计日志输出**：
   在所有鉴权分支上，统一通过插件日志系统记录 DEBUG 日志：
   `[权限审计] sender={sender} session={key} domain={domain} tool={tool} action={action} result={ALLOW/DENY} reason={reason}`

### 4.4 5 大工具及其子操作详细定义（文档与 SKILL.md 规范）

在 `astrbot_plugin_bsk_browser/skill/bsk-browser/SKILL.md` 及文档中全面收录 5 大工具所有子操作的明确用途：

1. **`bsk_session`**（会话管理）：
   - `start`：启动全新的浏览器会话；
   - `stop`：关闭并彻底销毁当前浏览器会话及窗口；
   - `list`：列出当前运行中的会话清单；
   - `sync`：重新扫描并同步页面状态与控制权令牌（导航后必备）；
   - `open`：在会话中打开指定 URL 并自动建立控制权。
2. **`bsk_page`**（导航与加载）：
   - `navigate`：跳转到指定的网页 URL；
   - `back`：后退到上一页历史记录；
   - `forward`：前进到下一页历史记录；
   - `reload`：刷新当前页面（支持 `hard=True`）；
   - `wait`：等待当前页面加载完成（不做跳转）。
3. **`bsk_inspect`**（读取与捕获）：
   - `observe`：智能自适应读取页面结构大纲与元素列表（支持关键词搜索 `query` 与分页）；
   - `snapshot`：获取静态可达性无障碍树；
   - `html`：获取页面或特定元素的原始 HTML 源码；
   - `screenshot`：截取页面图像并发送给用户（支持 `full_page=True` 长截图及 `ref` 局部裁剪）；
   - `console`：读取浏览器控制台输出日志；
   - `network`：读取基础网络请求摘要。
4. **`bsk_interact`**（页面交互）：
   - `click`：点击指定的页面元素或按钮；
   - `fill`：在输入框内填入文本；
   - `press`：触发键盘按键（如回车、Esc、Tab 等）；
   - `wheel`：鼠标滚轮滚动页面；
   - `scroll-to`：平滑滚动至指定元素所在位置；
   - `hover`：鼠标悬停在指定元素上方；
   - `select`：在下拉选择框中选择指定的选项；
   - `focus`：使目标元素获取焦点；
   - `blur`：使目标元素失去焦点。
5. **`bsk_tabs`**（标签页管理）：
   - `list`：列出当前会话的所有标签页及标题、URL；
   - `create`：创建空白新标签页；
   - `select`：切换当前活动标签页焦点；
   - `close`：关闭指定标签页；
   - `borrow`：借调普通用户已有标签页到 Agent 窗口；
   - `return`：归还已借调的标签页。

## 5. 施工留白与裁决记录 (Builder Calls & Notes)
- **生命周期基础动作**：裁决将 `sync`、`session.start/stop/list`、`tabs.list/select/close` 纳入全局基础放行，保证工作流顺畅并不产生死锁。
- **域名即导航权**：域名配置在白名单即拥有打开与导航权限，`allowed_actions` 仅约束进入页面后的具体操作。
- **URL 脏标记刷新机制**：采用 `url_dirty` 机制，在可能触发页面跳转的交互后置标记，下一次页内鉴权前按需调用 `tab list` 获取真实 URL，兼顾高安全性与极低性能开销。
- **双层隔离**：5 个高危工具既在 `on_llm_request` 中向模型隐形（省 Token），又在 `_dispatch` 严密硬拦截（防手搓调用）。
