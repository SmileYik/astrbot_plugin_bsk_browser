# 外链新标签页回收修复与 SKILL 文档纯粹精简设计文档

**文档标识**：`2026-11-15-tab-reclaim-and-skill-simplification-design`  
**作者**：Antigravity  
**状态**：已批准并完成 (Approved & Implemented)  
**涉及模块**：
- `astrbot_plugin_bsk_browser/bsk/session.py`
- `astrbot_plugin_bsk_browser/bsk/service.py`
- `astrbot_plugin_bsk_browser/skill/bsk-browser/SKILL.md`
- `astrbot_plugin_bsk_browser/skill/browse-baidu.com/SKILL.md`
- `astrbot_plugin_bsk_browser/skill/browse-cn.bing.com/SKILL.md`
- `astrbot_plugin_bsk_browser/tests/test_tab_lifecycle_cleanup.py`
- `astrbot_plugin_bsk_browser/tests/test_skills_doc.py`

---

## 1. 意图与背景 (Intent & Why)

### 1.1 问题现状
在最新实际交互中，用户提出搜索并点击搜索结果、滚动并截图的需求：
```
严格按照我下面的操作进行：
先打开百度，在搜索框内输入gtnh，然后按下回车，等待界面加载完毕后在页面底部找到下一页按钮，点击这个按钮，然后等待页面加载完后点击第一个搜索结果。
然后查看你点击的那个搜索结果页面里的内容，再滚动这个页面到页面最下面 然后截图给我看看，在你点进去的结果页面中滚动时，得选中最长的那个元素进行滚动。
```
执行完毕后，点击搜索结果（包含 `target="_blank"`）弹出的贴吧新标签页在宿主机上残留长达半个多小时无法被回收。

### 1.2 根因分析
1. **载荷类型解析缺陷**：`bsk tab list --scope agent --session <sid> --json` 返回的标准载荷是字典 `{"tabs": [...]}`。在 `SessionManager._stop_entry` 中，标签清理代码使用了 `tab_list = res.data if isinstance(res.data, list) else []`，导致 `tab_list` 恒为空列表，没有执行任何标签关闭动作。
2. **BrowserSkill 的 `dropOnly` 保留机制**：因为外链标签页未被关闭，该标签页在 BrowserSkill 中属于 `observedTabs`（非 agent 显式创建）。当调用 `bsk session stop` 时，BrowserSkill 检测到 Agent Window 内存在未被关闭的观察/用户标签页，触发了 Step 5 的 `shouldRelease = true`（即 `dropOnly` 机制）：仅脱离对会话的控制，却保留了整个 Agent Window 和标签页在宿主机桌面上。
3. **SKILL 文档臃肿且暴露后台配置**：现有 `SKILL.md` 文档包含诸如 `screenshot_compress_to_jpg`、`screenshot_quality`、`fullpage_max_height`、`fullpage_scope` 以及后台白名单配置键等内部参数。根据用户明确要求，由后台管理员配置并由程序自动判断处理的内容，不应写入面向模型的 SKILL 文档中，以避免污染上下文并精炼提示词。

---

## 2. 目标、非目标与反向目标 (Goals, Non-Goals & Anti-Goals)

### 目标 (Goals)
1. **会话存续期保留多标签**：在会话保持活跃期间，允许外链打开的新标签页正常存留，以便模型后续连续多轮交互与查阅。
2. **生命周期终结彻底回收**：在所有会话终止路径（空闲超时 `reap_idle`、显式 `stop_session`/`close_session`、LRU 淘汰 `_evict_for_capacity`、进程退出 `release_all`/`shutdown`）中，确保底层可靠解析 Agent Window 内的标签列表，并在调用 `bsk session stop` 前将多余的外链/弹窗标签页安全关闭，打破 `dropOnly` 保护，保证宿主机桌面窗口 100% 彻底关闭销毁。
3. **SKILL 文档纯粹精简**：
   - 移除所有后台配置参数名与内部自动处理机制（如 JPEG 压缩配置、画质等级、长截图高度阈值、白名单具体配置字段等）。
   - 保留且精炼核心工具说明、搜索与滚动操作指引、分页技巧以及生命周期收尾建议。
   - 保持 `bsk-browser` 作为核心，`browse-baidu.com` 与 `browse-cn.bing.com` 专精于特定网站结构与分页，消除冗余重复。
4. **测试套件保障**：
   - 补充 `SessionManager._stop_entry` 对字典载荷 `{"tabs": [...]}` 清理的单元测试。
   - 调整 `test_skills_doc.py` 断言，适应精简后的纯粹 SKILL 文档。
   - 保证全部 1000+ 测试稳定通过。

### 非目标 (Non-Goals)
- 不修改 `bsk` 命令行工具的 Rust 源码。
- 不强制模型在单轮工具调用内部立即强行关闭正在阅读的标签页（允许在会话有效期内由模型按需或由超时机制兜底）。

### 反向目标 (Anti-Goals)
- 严禁会话超时或停止后宿主机仍残留孤儿浏览器窗口或孤儿标签页。
- 严禁将后台配置项（如压缩开关、画质参数等）暴露给大模型。

---

## 3. 方案权衡与决策 (Approaches)

在方案沟通阶段，我们对比了两种方案：

- **方案一：底层生命周期统一收敛销毁 + SKILL 纯粹精简（用户已选定）**：
  - 将 Agent Window 的标签清理完整收敛于 `SessionManager._stop_entry`，作为所有会话终止路径（超时、停止、淘汰、析构）的唯一防线，修复字典提取逻辑。
  - 对三份 SKILL 文档进行彻底瘦身，仅保留操控核心技能。
  - **权衡优势**：单点收敛，彻底杜绝漏关；SKILL 文档 Token 最优，模型注意力最聚焦。
- **方案二：服务层与底层双轨清理 + SKILL 局部精简**：
  - 在 `BskService` 和 `SessionManager` 两处分别维持独立清理账本。
  - **权衡劣势**：逻辑重复分散，容易出现“超时路径走底层、命令路径走服务层”的行为不一致。

用户已确认选用**方案一**。

---

## 4. 详细设计与实现细节 (Detailed Design)

### 4.1 `SessionManager._stop_entry` 标签清理修复
在 `astrbot_plugin_bsk_browser/bsk/session.py` 的 `_stop_entry` 方法中：
```python
# 停止会话前，清理 Agent Window 中多余的弹窗/外链标签页，避免触发 dropOnly 导致窗口留在宿主机
try:
    res = await self._runner.run(
        ["tab", "list", "--scope", "agent", "--session", entry.session.session_id, "--json"],
        timeout=5.0,
    )
    raw = res.data
    tab_list = raw.get("tabs", []) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])
    if isinstance(tab_list, list) and len(tab_list) > 1:
        # 保留首个初始标签页，将其余外链弹出的 observed 标签页全部关闭
        for t in tab_list[1:]:
            if isinstance(t, dict):
                tid = t.get("tab_id", t.get("id"))
                if tid is not None:
                    try:
                        await self._runner.run(
                            ["tab", "close", str(tid), "--session", entry.session.session_id, "--json"],
                            timeout=5.0,
                        )
                    except Exception:
                        pass
except Exception as exc:
    self._logger.debug("关闭多余标签页失败（忽略）：%r", exc)
```
- **核心保障**：
  1. 兼容字典 `{"tabs": [...]}` 与裸列表；
  2. 逆向或顺向关闭 `tab_list[1:]` 中的所有多余标签；
  3. 关闭后 Agent Window 内仅剩初始的 `agentCreatedTabs`（首个 tab），随后的 `bsk session stop` 将正常执行 Step 4 & Step 5，`shouldRelease` 判定为 False，驱动 Chromium 彻底关闭该窗口，消除一切宿主机残留。

### 4.2 `BskService.sweep_agent_tabs` 与会话管理统一
- 确保 `BskService.sweep_agent_tabs` 与 `SessionManager._stop_entry` 保持语义与载荷解析逻辑完全一致。

### 4.3 SKILL 文档纯粹精简
遵循“程序自动处理的配置不入 SKILL”原则进行精简：

1. **`skill/bsk-browser/SKILL.md`**：
   - **截图部分**：移除 `screenshot_compress_to_jpg`、`screenshot_quality`、`fullpage_max_height`、`fullpage_scope` 等配置参数说明，改为：“截图工具会自动将图像交付给用户；长截图传 `full_page=True`，图像处理与尺寸保护由底层自动完成。”
   - **权限部分**：移除具体后台白名单字段名与管理选项，改为：“如遇到未开放访问或受限域名提示，直接如实告知用户，切勿重复盲目重试。”
   - **标签页与生命周期**：明确模型可在交互中阅读新标签页；完成整个多步任务后，可调用 `bsk_session(action="stop")` 释放浏览器；空闲时底层具备全自动销毁与清理保障。
2. **`skill/browse-baidu.com/SKILL.md` 与 `skill/browse-cn.bing.com/SKILL.md`**：
   - 严格依赖核心 `bsk-browser`，专注描述两者的搜索输入框、搜索按钮、“上一页/下一页”与数字分页按钮特征、以及左侧结果区域精准滚动。
   - 移除与核心规范重复的配置或冗长描述。

### 4.4 测试验证方案
1. **`tests/test_tab_lifecycle_cleanup.py`**：
   - 增加测试用例覆盖 `SessionManager._stop_entry` 在接收字典载荷 `{"tabs": [...]}` 时能够触发关闭 `tab_id=102`。
   - 验证 `reap_idle` 超时路径下正确调用清理。
2. **`tests/test_skills_doc.py`**：
   - 调整断言，移除对旧版“压缩”配置文案的硬性断言，替换为对新版精炼规范的检查（如确保核心动作 `full_page`、`bsk_tabs`、`bsk_session` 存在，且不包含内部配置项字段名）。
3. **全量回归测试**：运行 1000+ pytest 套件，确保 100% 通过。

---

## 5. 待构建者实施事项 (Left to Builder)
- 具体日志输出在关键点位打出 DEBUG 级别的标签清理追踪日志。
- 文档用词追求精准严谨、精炼干脆。
