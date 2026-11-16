# Session 文本注释精炼与彻底移除 Uncertain 逻辑设计

## 1. 背景与意图 (Intent and Why)

在 `astrbot_plugin_bsk_browser` 中：
1. **注释冗余臃肿**：`bsk/session.py`（超过 2300 行代码）充斥着原作者大量日记式、历史辩论式与个人情绪化的冗长注释（例如详细叙述历史版本缺陷、反复论证重试超时常量的背景、引用外部 DECISION 决策文件等）。这违背了项目 [AGENTS.md](file:///run/media/smileyik/G/Workspace/ai/bsk/AGENTS.md) 中关于“在正确表义基础上做到精炼简洁不啰嗦”的代码与文本规范。
2. **`uncertain` 逻辑的架构包袱与副作用**：
   - 原作者基于“对非幂等动作盲目重试可能产生破坏性后果（如重复点击付款/表单）”的顾虑，引入了一套悲观锁死机制：一旦底层通信出现未知结果（`BskOutcomeUnknown` 或 `OUTCOME_UNKNOWN_REASONS`），即通过 `_mark_uncertain()` 将会话标记为 `uncertain = True`。
   - 被标记后，后续所有未显式声明 `allow_uncertain=True` 的写入/操作类动作全部被硬性抛出 `session_uncertain` 拦截阻断。
   - 在由大模型（LLM）驱动的 AstrBot 实际场景中，这种永久性锁死机制严重破坏了 Agent 的自愈与多轮决策能力（模型在操作失败后完全可以通过 `observe` 查看页面状态后再作决定，而不需要代码层将整个会话锁死废弃）。
   - 同时，该机制对整个代码库形成了深层污染：`models.py` 维护状态字段、`session.py` 维护阻断与计数器、`service.py` 在 20 多处调用点繁琐区分并传递 `allow_uncertain`、`main.py` 在状态展示中增加分支，并产生了大量冗余测试。

本设计意图：
1. 依照 AGENTS.md 规范，全面重构并精炼 `session.py` 中的所有模块文档、常量文档、函数方法 docstring 以及行内注释，去除所有废话与历史包袱，保持表意准确、精炼易读；
2. 彻底移除全库范围内的 `uncertain` 机制（包括状态字段、拦截逻辑、死参数及相关测试），还原干净、自主的调用链路。

---

## 2. 目标、非目标与反目标 (Goals, Non-Goals, and Anti-Goals)

### 目标 (Goals)
1. **G1 (精炼 session.py 注释)**：
   - 遵循 AGENTS.md 规范，将 `session.py` 中所有原作者写的长篇大论精简为清晰、紧凑的技术说明；
   - 保留核心算法流程（如可恢复启动协议、有界 stop 重试预算推导、LRU 与空闲回收）的必要技术约束与关键参数含义，剔除叙事性与辩论文风。
2. **G2 (彻底清除 uncertain 机制)**：
   - 数据模型：从 `BskSession` 中彻底移除 `uncertain` 属性；
   - 会话管理器：从 `SessionManager` 中移除 `_mark_uncertain`、`_uncertain_error`、`uncertain_blocks` 计数器以及 `allow_uncertain` 形参；
   - 业务层：清理 `BskService` 中所有 `self.sessions.execute_action` 和 `self.sessions.execute` 调用点处的 `allow_uncertain=...` 实参；
   - 插件状态展示：清理 `main.py` `/bskstatus` 中关于 `uncertain` 的状态显示；
   - 测试用例：移除或重写 `test_session.py` 和 `test_service.py` 中测试 `uncertain` 阻断和 `allow_uncertain` 的用例。
3. **G3 (保持不可重试语义)**：
   - 在 `execute_action` / `execute` 中，当捕获到 `BskOutcomeUnknown` 或 `exc.reason in OUTCOME_UNKNOWN_REASONS` 时，依然确保**不进行自动重试**（即直接抛出异常给调用方/Agent），仅不再修改会话状态。
4. **G4 (测试与质量保障)**：
   - 确保修改后插件全部测试用例绿灯通过，无死代码残留。

### 非目标 (Non-Goals)
- **不改变 bsk 底层通信协议**：保留对 `OUTCOME_UNKNOWN_REASONS` 的分类识别能力（用于决定是否重试）；
- **不改变其他会话生命周期机制**：可恢复启动令牌协议（request_id）、崩溃孤儿恢复（journal/recover_orphans）、有界 stop 重试机制保持完全不变。

### 反目标 (Anti-Goals)
- **切忌保留死参数与空转兼容代码**：不采用保留 `allow_uncertain` 默认值或 `**kwargs` 兼容的做法，必须彻底从签名和调用链中删除；
- **切忌破坏异常传播**：发生未知结果时，必须如实抛出异常通知 Agent，绝不能为了移除 `uncertain` 而误把未知错误吞掉或视作成功。

---

## 3. 约束条件 (Constraints)

1. **修改范围限制**：仅修改 `astrbot_plugin_bsk_browser` 仓库；
2. **精炼简洁**：所有注释与文案依照 AGENTS.md 做到正确表义且精炼简洁；
3. **署名规范**：保留原作者，增补 `SmileYik`；
4. **测试维护**：不需要的测试用例及时清理或重构，保持测试套件 100% 通过；
5. **文档维护**：检查并同步维护 `skills` 下的文档。

---

## 4. 备选方案对比与抉择 (Approaches)

### 备选方案 1：彻底剥离 + 全链精简（选中）
- 彻底从数据模型、SessionManager、BskService、Main 和单元测试中删除 `uncertain` 概念及 `allow_uncertain` 参数。
- **优点**：最干净、无任何遗留死代码和无用参数，架构清晰。
- **缺点**：改动涉及多个文件（`session.py`, `models.py`, `service.py`, `main.py`, `test_session.py`, `test_service.py`）。

### 备选方案 2：内部软弃用（空转兼容）
- 在 `session.py` 中将 `allow_uncertain` 保留为忽略参数，仅删除内部锁死逻辑，不触碰 `service.py`。
- **优点**：改动集中在单个文件。
- **缺点**：遗留大量无用死参数，与“彻底移除”的要求不符。

### 抉择
采用 **方案 1**，由用户明确选定。

---

## 5. 详细设计与改动清单 (Detailed Design)

### 5.1 数据模型与实体 (`bsk/models.py`)
- 从 `BskSession` 类定义中删除 `uncertain: bool = False` 字段；
- `from_json` 与其他字典序列化不再处理 `uncertain`。

### 5.2 会话管理层 (`bsk/session.py`)
1. **移除 uncertain 相关逻辑**：
   - `_adopt(target, fresh)`：删除 `target.uncertain = False` 赋值；
   - `_counters`：删除 `"uncertain_blocks"` 计数项；
   - `execute_action(self, key: str, action: Any, *, timeout: float | None = None)`：
     - 删除形参 `allow_uncertain: bool = False`；
     - 删除状态检查：`if entry.session.uncertain and not allow_uncertain: ...`；
     - 异常处理：
       ```python
       except BskOutcomeUnknown:
           raise
       except BskError as exc:
           if exc.reason in OUTCOME_UNKNOWN_REASONS:
               raise
           # 后续 BskSessionGone 与 BskSessionBusy 重试保持不变
       ```
   - `execute(...)`：删除形参 `allow_uncertain: bool = False`，转调 `execute_action` 时不再传递；
   - `stats(self)`：
     - 从 `details` 列表中移除 `"uncertain"` 项；
     - 从返回字典顶层移除 `"uncertain_count"` 统计项；
   - 彻底删除方法：
     - 删除 `_mark_uncertain(self, entry: _Entry, why: str) -> None`；
     - 删除 `_uncertain_error(session: BskSession) -> BskOutcomeUnknown`。
2. **全面精炼注释 (AGENTS.md 风格)**：
   - **模块级 docstring (1-50行)**：
     - 压缩为 15-20 行：简述按 key 隔离的并发安全会话池定位，核心语义列表（串行执行、失效重建、空闲回收、有界停止重试、可恢复启动协议与 journal 孤儿回收），删除原作者与上层扯皮、吐槽 bsk 的冗长话术。
   - **常量注释 (118-250行、308-370行)**：
     - 去除自我反问式段落（如“全部有实测依据，改动前请先想清楚”、“为什么是 3 而不是 2”、“为什么这 5 秒给得起”、“为什么按文本而不是按异常类型判定”、“为什么宁大勿小”等）；
     - 将每个常量注释压缩为 1-2 句精准阐明其含义与设值考量即可。
   - **核心方法 docstring 与内部注释**：
     - `_is_transient_stop_error`：保留 5 条简洁判定顺序，删除冗长的心路历程说明；
     - `acquire` / `execute_action` / `execute` / `release` / `release_all` / `reap_idle` / `recover_orphans`：精简 docstring；
     - `_start_into`：精炼关于 request_id 协议步骤（落盘 -> prepare -> start -> claim）的说明，移除引用外部决策文档的冗余文字；
     - `_stop_session_id`：精炼关于截止时刻与重试预算分配的推导说明，保留数学约束逻辑（预算、超时、清理开销），删除大量日记式描述。

### 5.3 业务服务层 (`bsk/service.py`)
- 全面检索并删除所有 `self.sessions.execute_action` 与 `self.sessions.execute` 调用点处的 `allow_uncertain=True`、`allow_uncertain=False` 以及 `allow_uncertain=readonly` 传参；
- 清理相关方法 docstring 中关于“由于是只读所以 allow_uncertain=True”、“写类动作必须传 allow_uncertain=False”等说明。

### 5.4 插件状态展示 (`main.py`)
- 在 `/bskstatus` 的状态格式化方法中，删除对 `cur.get("uncertain")` 的判断以及 `"上一步结果不确定"` 标签。

### 5.5 单元测试维护
1. **`tests/test_session.py`**：
   - 移除测试用例 `test_allow_uncertain_permits_readonly_command`；
   - 移除测试用例 `test_release_clears_uncertain_state`；
   - 改造 `test_outcome_unknown_marks_session_and_blocks_next_action`：
     - 重命名为 `test_outcome_unknown_does_not_retry_and_raises`；
     - 验证动作遇到 `BskOutcomeUnknown` 或 `OUTCOME_UNKNOWN_REASONS` 时不会进行自动重试（只调用一次底层 runner），直接抛出异常；并且验证后续动作不会因为所谓的不确定态被死锁。
   - 调整其他引用 `allow_uncertain` 或 `uncertain` 字段的测试断言。
2. **`tests/test_service.py`**：
   - 清理测试用例中对 `allow_uncertain` 的断言或 mock 测试（例如 `test_console_works_while_session_is_uncertain`、`test_network_works_while_session_is_uncertain` 等，若不再有 uncertain 状态，则更新或移除该类专门测试）。

### 5.6 SKILL 文档检查
- 检查 `astrbot_plugin_bsk_browser/skills/` 下的 `bsk-browser`、`bsk-browse-baidu`、`bsk-browse-bingcn`，确认无 `uncertain` 依赖或残留概念，确保文档准确精炼。

---

## 6. 构建者自决边界 (What's Left to the Builder)

1. **注释精简的具体措辞**：只要符合 AGENTS.md“精炼简洁不啰嗦”原则，具体文字精简幅度由实施者自决；
2. **单元测试用例细节**：测试断言的微调与测试清理节奏由实施者负责，确保全套 pytest/unittest 完全通过。
