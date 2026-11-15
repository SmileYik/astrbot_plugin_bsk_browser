---
name: bsk-browse-baidu
description: 百度（baidu.com）搜索、页面结构识别、搜索结果精准滚动与分页导航指南。
---

# bsk-browse-baidu (百度搜索实战指南)

本技能依赖核心技能 `bsk-browser`，专精于在百度搜索（`https://www.baidu.com`）中执行页面结构区分、搜索提交、结果滚动、条目查阅与分页导航。

## 1. 主页结构与搜索结果页结构的区分

执行操作前，通过 `bsk_session(action="sync")` 或 `bsk_inspect(action="observe")` 判断当前页面结构：

### 结构 A：百度首页（未搜索）
- **特征**：URL 为 `https://www.baidu.com/`，页面中央呈现百度 Logo 和独立搜索框。
- **关键元素**：
  - 搜索输入框：role 为 `combobox` 或 `searchbox`（输入框带有 `@eInput`）。
  - 搜索按钮：“百度一下”（role 为 `button`，带有 `@eButton`）。
- **说明**：此时无搜索结果，仅有热搜榜单与快捷导航。

### 结构 B：搜索结果列表页（已搜索）
- **特征**：URL 为 `https://www.baidu.com/s?wd=...`。
- **区域划分**：
  - **顶部**：紧凑型搜索栏与“百度一下”按钮，用于换词重搜。
  - **左侧结果区（`#content_left`）**：真正的搜索结果卡片列表。每条包含标题外链、正文快照摘要与来源标签。
  - **右侧侧边栏（`#content_right`）**：相关推荐与热搜，属于辅助信息。
  - **底部分页区（`#page`）**：位于左侧列表底部，包含“上一页”、“下一页”以及数字跳转按钮。

## 2. 搜索与结果查阅流程

1. **输入与提交搜索**：
   - 输入检索词：`bsk_interact(action="fill", target="@eInput", value="检索内容")`。
   - 提交搜索：按回车 `bsk_interact(action="press", target="@eInput", key="Enter")` 或点击“百度一下”按钮。
   - 同步新页面：提交后调用 `bsk_session(action="sync")` 获取搜索结果。
2. **查阅外链详情**：
   - 点击搜索结果卡片打开新标签页，系统会自动切焦。
   - 在新标签页中调用 `bsk_inspect(action="observe")` 阅读内容或 `screenshot` 截图。
   - 查阅完毕如需返回搜索结果列表，可调用 `bsk_tabs(action="close", tab_id=<ID>)` 关闭该标签页并自动切回搜索页。

## 3. 搜索结果滚动技巧

- **定向定位首选 `scroll-to`**：若已知目标元素（例如底部分页按钮、指定卡片），优先使用 `bsk_interact(action="scroll-to", target="@eTarget")`，直接平滑滚入视口，最稳定。
- **定向滚轮滚动 `wheel`**：向下浏览时鼠标落点必须落在左侧结果卡片容器上，向下看传正数 `delta_y=600`，向上看传负数 `delta_y=-600`。严禁在空白边缘盲滚。

## 4. 分页导航与页码识别

底部分页按钮识别方法：
1. **上一页**：按钮文本为 `< 上一页` 或包含 `上一页`（首页通常隐藏或不存在）。
2. **下一页**：按钮文本为 `下一页 >`，点击载入下一页结果。
3. **数字页码**：`1`、`2`、`3`、`4`... 等单项数字。当前所在页码为纯文本高亮（非链接），点击其他数字按钮可直接跳转至对应页码。
4. **翻页推荐步骤**：
   - 定位按钮：`bsk_inspect(action="observe", query="下一页")` 得到 `@eNext`。
   - 滚动到底部：`bsk_interact(action="scroll-to", target="@eNext")`。
   - 点击并同步：`bsk_interact(action="click", target="@eNext")`，然后调用 `bsk_session(action="sync")`。

## 5. 任务结束释放

完成全部检索与操作后，调用 `bsk_session(action="stop")` 释放浏览器资源。
