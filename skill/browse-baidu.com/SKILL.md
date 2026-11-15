---
name: browse-baidu.com
description: 百度（baidu.com）搜索、页面结构识别、搜索结果精准滚动、分页导航与外链标签页闭环操作指南。
---

# browse-baidu.com (百度搜索与结果浏览实战指南)

本技能供机器人使用 `astrbot_plugin_bsk_browser` 控制浏览器在百度搜索（`https://www.baidu.com`）中执行搜索、高效翻阅结果、阅读外链条目与分页导航。

## 1. 主页结构与搜索结果页结构的区分

在执行操作前，通过 `bsk_session(action="sync")` 或 `bsk_inspect(action="observe")` 判断当前结构：

### 结构 A：百度首页（未搜索）
- **特征**：URL 为 `https://www.baidu.com/`，中央呈现百度 Logo 和独立搜索框。
- **关键元素**：
  - 搜索输入框：role 为 `combobox` 或 `searchbox`（输入框带有 `@eInput`）。
  - 搜索按钮：“百度一下”（role 为 `button`，带有 `@eButton`）。
- **注意**：此时无搜索结果，只有热搜榜单与快捷导航。

### 结构 B：搜索结果列表页（已搜索）
- **特征**：URL 为 `https://www.baidu.com/s?wd=...`。
- **区域划分**：
  - **顶部**：紧凑型搜索栏与“百度一下”按钮，用于换词重搜。
  - **左侧结果区（`#content_left`）**：真正的搜索结果卡片列表。每条包含标题外链、正文快照摘要与来源标签。
  - **右侧侧边栏（`#content_right`）**：相关推荐与热搜，属于辅助信息。
  - **底部分页区（`#page`）**：位于左侧列表底部，包含“上一页”、“下一页”以及数字跳转按钮。

## 2. 搜索与外链浏览的标准流程（含标签页闭环）

1. **输入与提交搜索**：
   - 输入关键词：`bsk_interact(action="fill", target="@eInput", value="你要检索的内容")`。
   - 提交搜索：直接按回车 `bsk_interact(action="press", target="@eInput", key="Enter")` 或点击“百度一下”按钮。
   - 同步新页面：提交后调用 `bsk_session(action="sync")` 获取搜索结果。
2. **点击条目进入外链详情（新标签页）**：
   - 百度搜索结果链接均带有 `target="_blank"`，点击后会在浏览器中打开**新标签页**。
   - 插件会自动检测新标签页并自动切换焦点，回执会提示：`【检测到新标签页】... 标签 ID: <ID>`。
   - 在新页面中调用 `bsk_inspect(action="observe")` 阅读详情或截屏。
3. **关键收尾：主动关闭外链标签页**：
   - **阅读完成后，务必调用 `bsk_tabs(action="close", tab_id=<ID>)` 关闭该外链标签页**。
   - 关闭后焦点会自动切回百度搜索结果页，以便继续浏览其它结果或翻页。
   - 切勿让外链标签页在后台一直残留堆积。

## 3. 搜索结果滚动技巧（核心防坑）

- **定向定位首选 `scroll-to`**：
  若已知目标元素（例如底部分页按钮、第 5 条卡片），**优先使用 `bsk_interact(action="scroll-to", target="@eCard")`**，直接平滑滚入视口，100% 稳定可靠。
- **带目标的滚轮滚动 `wheel`**：
  若需向下浏览，**鼠标落点必须落在左侧结果卡片上**（严禁在无目标的状态下盲滚空白边距）：
  `bsk_interact(action="wheel", target="@eCard", delta_y=600)`。
- **滚动方向规则**：
  - **向下滚动（看下方内容）**：必须传【**正数**】（如 `delta_y=600`）。
  - **向上滚动（回上方内容）**：传【**负数**】（如 `delta_y=-600`）。
  - 严禁为了向下滚动而传负数！

## 4. 分页导航与页码识别

底部分页按钮识别方法：
1. **上一页**：按钮文本为 `< 上一页` 或包含 `上一页`。位于首页时该按钮通常隐藏或不存在。
2. **下一页**：按钮文本为 `下一页 >`，点击将载入下一页结果。
3. **数字页码**：`1`、`2`、`3`、`4`... 等单项数字。当前所在页码为纯文本高亮（非链接），点击其他数字按钮可直接跳转至对应页码。
4. **翻页三步法**：
   - 定位按钮：`bsk_inspect(action="observe", query="下一页")` 得到 `@eNext`。
   - 滚动到底部：`bsk_interact(action="scroll-to", target="@eNext")`。
   - 点击并同步：`bsk_interact(action="click", target="@eNext")`，然后调用 `bsk_session(action="sync")`。

## 5. 任务结束彻底释放

完成检索后，务必调用 `bsk_session(action="stop")` 彻底关闭会话并清理所有标签页，确保宿主机零残留。
