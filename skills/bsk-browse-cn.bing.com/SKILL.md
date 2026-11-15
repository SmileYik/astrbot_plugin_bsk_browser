---
name: bsk-browse-cn.bing.com
description: 微软必应中国（cn.bing.com）搜索、页面结构识别、搜索结果精准滚动与分页导航指南。
---

# bsk-browse-cn.bing.com (必应中国搜索实战指南)

本技能依赖核心技能 `bsk-browser`，专精于在微软必应中国搜索（`https://cn.bing.com`）中执行页面结构区分、搜索提交、结果滚动、条目查阅与分页导航。

## 1. 主页结构与搜索结果页结构的区分

执行操作前，通过 `bsk_session(action="sync")` 或 `bsk_inspect(action="observe")` 判断当前页面结构：

### 结构 A：必应首页（未搜索）
- **特征**：URL 为 `https://cn.bing.com/`，全屏壁纸背景，页面视觉中心为大搜索框。
- **关键元素**：
  - 搜索输入框：提示通常为 `搜索`，role 为 `combobox` 或 `searchbox`。
  - 搜索按钮：放大镜图标或名为 `搜索` 的按钮（通常位于输入框右侧）。
- **说明**：此时无搜索结果，下方为资讯卡片与快捷应用。

### 结构 B：搜索结果列表页（已搜索）
- **特征**：URL 类似 `https://cn.bing.com/search?q=...`。
- **区域划分**：
  - **顶部**：紧凑型搜索栏与分类标签（网页、图片、视频等），支持二次检索。
  - **主结果区（`#b_results`）**：搜索结果卡片列表（`b_algo`）。每条包含标题外链、摘要正文与引用网址。
  - **右侧知识图谱区（`#b_context`）**：百科摘要、相关实体卡片或相关搜索。
  - **底部分页导航区（`.b_pag`）**：位于结果列表最下方，包含前一页、后一页与页码跳转按钮。

## 2. 搜索与结果查阅流程

1. **输入与提交搜索**：
   - 输入检索词：`bsk_interact(action="fill", target="@eInput", value="检索内容")`。
   - 提交搜索：按回车 `bsk_interact(action="press", target="@eInput", key="Enter")` 或点击放大镜按钮。
   - 同步新页面：提交后调用 `bsk_session(action="sync")` 获取搜索结果。
2. **查阅外链详情**：
   - 点击搜索结果卡片打开新标签页，系统会自动切焦。
   - 在新标签页中调用 `bsk_inspect(action="observe")` 阅读内容或 `screenshot` 截图。
   - 查阅完毕如需返回搜索结果列表，可调用 `bsk_tabs(action="close", tab_id=<ID>)` 关闭该标签页并自动切回搜索页。

## 3. 搜索结果滚动技巧

- **定向定位首选 `scroll-to`**：若已知目标元素（如底部分页按钮、指定卡片），优先使用 `bsk_interact(action="scroll-to", target="@eTarget")`，直接平滑滚入视口，最稳定。
- **定向滚轮滚动 `wheel`**：向下浏览时鼠标落点必须落在主结果列表卡片容器上，向下看传正数 `delta_y=600`，向上看传负数 `delta_y=-600`。严禁在空白边缘盲滚。

## 4. 分页导航与页码识别

底部分页按钮识别方法：
1. **上一页**：按钮通常为 `<` 符号或包含 `上一页`（第一页时该按钮通常不可见或禁用）。
2. **下一页**：按钮通常为 `>` 符号或包含 `下一页`，点击载入下一页结果。
3. **数字页码**：`1`、`2`、`3`、`4`... 等单项数字。当前所在页码为纯文本高亮（非链接），点击其他数字按钮可直接跳转至对应页码。
4. **翻页推荐步骤**：
   - 定位按钮：`bsk_inspect(action="observe", query="下一页")` 得到 `@eNext`。
   - 滚动到底部：`bsk_interact(action="scroll-to", target="@eNext")`。
   - 点击并同步：`bsk_interact(action="click", target="@eNext")`，然后调用 `bsk_session(action="sync")`。

## 5. 任务结束释放

完成全部检索与操作后，调用 `bsk_session(action="stop")` 释放浏览器资源。
