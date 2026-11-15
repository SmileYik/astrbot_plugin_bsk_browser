# Design Document: Plugin Refinement and LLM Prompt Injection

- **Date**: 2026-11-15
- **Author**: Assistant & User (SmileYik)
- **Status**: Draft / Proposed

---

## 1. Intent and Why

当前 `astrbot_plugin_bsk_browser` 插件在实际使用和维护中存在以下改进空间：
1. **文案冗长繁复**：面向用户（WebUI 配置项、操作报错、权限拦截文案）以及面向 LLM（工具描述、参数说明 Schema、操作回执）的提示文本均包含过多历史背景、性能跑分与解释性长句，增加了用户的理解成本，并不必要地消耗了模型调用的上下文 Token。
2. **缺少灵活的提示词注入通道**：当机器人拥有浏览器操作工具时，模型往往需要特定的浏览器操控引导或行为准则（System Prompt）；目前缺乏让管理员自定义针对有浏览器权限用户进行系统提示词注入的配置项。
3. **协议与作者信息需统一规范**：历史版本采用 MIT / AGPL-3.0 双许可并伴随双文件结构（`LICENSE` 与 `LICENSE-AGPL`），现需收敛为单一 MIT 许可证，去除冗余许可文件，并在保留原作者署名的基础上新增共同作者 `SmileYik`。
4. **架构文档需同步最新形态**：随着文案精简、新配置引入与许可证调整，`ARCHITECTURE.md` 需同步更新。

---

## 2. Goals, Non-Goals, and Anti-Goals

### Goals
- **G1（全面精炼提示文本）**：在确保原意准确、明确指导的前提下，精简压缩 `_conf_schema.json`、`metadata.yaml`、`bsk/tools.py`、`bsk/config.py`、`bsk/errors.py`、`main.py` 以及 `skills/` 下所有面向用户与模型的提示文本，消除冗长啰嗦表述。
- **G2（LLM提示词注入配置）**：在 `_conf_schema.json` 与 `Settings` 中新增长文本配置项 `llm_prompt_injection`（展示名：“LLM提示词注入”，默认值为空字符串 `""`）；在 `main.py` 中通过 `@filter.on_llm_request()` 挂钩，**仅当当前用户具备浏览器操作权限**且该配置非空时，将该提示词追加至 `req.system_prompt`。
- **G3（仓库协议单一 MIT 化）**：删除 `LICENSE-AGPL`，全仓库仅保留单一 MIT 协议；同步清理 `README.md`、`metadata.yaml`、`ARCHITECTURE.md`、`CHANGELOG.md` 以及合规校验脚本 `tests/verify_compliance.py`、`tests/verify_release_ready.py` 中的双许可断言与引用。
- **G4（作者署名更新）**：在 `metadata.yaml`、`README.md` 及相关文档中保留原作者 `JosephTian876`，新增作者 `SmileYik`（如 `JosephTian876, SmileYik`）。
- **G5（架构文档同步）**：全面更新 `ARCHITECTURE.md`，记录新的配置项、`on_llm_request` 扩展点、纯 MIT 布局与作者信息。
- **G6（测试与向后兼容）**：保持全量单元测试（`test_config.py`、`test_tools.py` 等）100% 通过，并补充针对 `llm_prompt_injection` 与 `on_llm_request` 权限守卫的测试用例。

### Non-Goals
- 不修改 AstrBot 框架核心代码（`AstrBot/`）。
- 不更改底层 BrowserSkill 协议格式或新增其它浏览器动作。
- 不影响未配置提示词注入时的原有默认大模型请求。

### Anti-Goals
- 严禁越权注入：无浏览器操作权限的普通用户聊天时，不得注入该提示词。
- 严禁粗暴删除关键参数语义或校验提示：精简必须以“准确且明确”为底线，不能破坏模型对工具参数格式的理解。

---

## 3. Constraints

1. **唯一修改主体**：根据 `AGENTS.md`，`./astrbot_plugin_bsk_browser/` 是唯一可修改的仓库。
2. **框架钩子约束**：根据 AstrBot 机制，`@filter.on_llm_request()` 接收 `(self, event: AstrMessageEvent, req: ProviderRequest)`，且该钩子内禁止调用 `yield`。
3. **配置与设置强绑定**：`_conf_schema.json` 中的每一个配置项必须与 `bsk/config.py` 中的 `Settings` 字段严格一一对应（`test_config.py` 严格校验）。
4. **日志规范**：调试与重要运行日志使用 AstrBot 日志系统并在 DEBUG 等级输出。
5. **Git 管理**：所有变更在完成后需进行规范提交。

---

## 4. Approaches

### 4.1 提示词注入实现方式

- **方案 A（复用原生 `_denied` 权限门，推荐并采纳）**：
  在 `main.py` 的 `BskBrowserPlugin` 中实现 `@filter.on_llm_request()` 处理函数，直接调用既有的 `self._denied(event)`。若返回值不为 `None`（表示被插件停用、管理员策略或白名单拦截），则直接返回；若放行且 `llm_prompt_injection` 配置非空，则将注入文本以双换行 `\n\n` 追加到 `req.system_prompt`（若原 system_prompt 为空则直接赋值）。
  *优势*：权限逻辑单点维护，完全与实际工具调用鉴权保持 100% 一致，无漂移风险。
- **方案 B（独立重写简易权限检查）**：
  在钩子内部重新判断 `is_admin` 或 `allowed_users`。
  *劣势*：重复实现逻辑，未来修改权限策略容易漏改，导致鉴权与注入脱节。

*决策*：采纳 **方案 A**。

### 4.2 文本精简范围与策略

- **方案 A（端到端系统化精简，推荐并采纳）**：
  覆盖 `_conf_schema.json`（去除长篇大论、历史背景与 Wikipedia 跑分，保留准确指导与默认建议）、`metadata.yaml`（紧凑概述）、`bsk/tools.py`（凝炼工具描述与属性描述）、`bsk/errors.py`（直击根因与行动指南）、`main.py`（简洁明了的拒绝与提示文案）、`skills/`（精简主核心技能与专精技能文档）。
  *优势*：全面降低人机认知开销，显著节约 Token。
- **方案 B（仅精简用户界面文案）**：
  仅精简 `_conf_schema.json`，保留其他代码中的冗长描述。
  *劣势*：工具 Schema 依然臃肿，无法达到“全面紧凑凝练”的目标。

*决策*：采纳 **方案 A**。

---

## 5. Detailed Design & Changes

### 5.1 配置项与设置扩展
1. **`_conf_schema.json`**：
   新增字段 `llm_prompt_injection`：
   ```json
   "llm_prompt_injection": {
     "description": "LLM提示词注入",
     "type": "text",
     "default": "",
     "hint": "当前用户具备浏览器操作权限时追加到系统提示词中；留空则不注入。"
   }
   ```
2. **`bsk/config.py`**：
   - 定义默认值常量：`DEFAULT_LLM_PROMPT_INJECTION = ""` 并导出到 `__all__`。
   - `Settings` 类增加字段：`llm_prompt_injection: str = DEFAULT_LLM_PROMPT_INJECTION`。
   - `parse_settings` 中进行字符串解析与首尾空白截除：
     `llm_prompt_injection = str(raw.get("llm_prompt_injection", DEFAULT_LLM_PROMPT_INJECTION) or "").strip()`
3. **`tests/test_config.py`**：
   - 增加对 `llm_prompt_injection` 的字段解析、默认值、类型与空值容错测试。

### 5.2 `@filter.on_llm_request()` 提示词注入
在 `main.py` 的 `BskBrowserPlugin` 类中定义：
```python
from astrbot.api.provider import ProviderRequest

@filter.on_llm_request()
async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
    """当用户拥有浏览器操作权限且配置了注入内容时，向 system_prompt 注入自定义提示词。"""
    prompt = (self.settings.llm_prompt_injection or "").strip()
    if not prompt or self._denied(event) is not None:
        return

    curr = getattr(req, "system_prompt", "") or ""
    if curr:
        req.system_prompt = f"{curr}\n\n{prompt}"
    else:
        req.system_prompt = prompt
```

### 5.3 提示文本精简重构
1. **`_conf_schema.json`**：
   - 全面审视 25 个既有配置项的 `description` 与 `hint`。
   - 剔除历史故事、跑分数据（如维基百科长条目11.7秒等无关细节），直接给出该项的作用、推荐取值与注意事项。
2. **`metadata.yaml`**：
   - 将 40 余行的 `desc` 重构为结构紧凑、表意清晰的模块（功能简介、主要工具组、前置要求、安全提醒、开源许可）。
3. **`bsk/tools.py`**：
   - 审阅 `TOOL_DESCRIPTIONS` 中的 8 个工具描述，删除多余修饰词，直接列出该工具负责的核心动作及典型调用推荐。
   - 精简 `_DEBUG_PROPERTY_DESCRIPTIONS` 中调试参数的文字长度。
4. **`bsk/errors.py`**：
   - 精炼 `classify()` 中的友好报错文本（`friendly`），突出“错误原因”与“建议下一步操作”。
5. **`main.py`**：
   - 精炼权限拦截消息（`_denied`、`_evaluate_denied`）与工具回执文案。
6. **`skills/` 文档**：
   - 检查 `skills/bsk-browser/SKILL.md`，去除赘述，保留所有工具调用要点与截图、生命周期关闭指引。
   - 检查 `skills/bsk-browse-baidu/SKILL.md` 与 `skills/bsk-browse-bingcn/SKILL.md`，确保保持专精且精简。

### 5.4 协议纯化与作者信息更新
1. **删除 `LICENSE-AGPL`** 文件。
2. **确认 `LICENSE`** 为标准完整的 MIT License 全文。
3. **`metadata.yaml`**：
   - `author: JosephTian876, SmileYik`
   - 移除关于 AGPL 双许可的声明，明确为 MIT 许可。
4. **`README.md` 与 `CHANGELOG.md`**：
   - 将“双许可声明”修改为“MIT 开源许可”，说明由 JosephTian876 与 SmileYik 共同维护。
5. **合规测试脚本同步**：
   - 更新 `tests/verify_compliance.py`：移除对 `LICENSE-AGPL` 存在的检查，断言仅存在标准 MIT 许可。
   - 更新 `tests/verify_release_ready.py`：移除 AGPL 相关检查项。

### 5.5 `ARCHITECTURE.md` 更新
更新 `ARCHITECTURE.md` 中的以下章节：
- 顶部版本与作者信息：增加 `SmileYik`。
- 架构图与分层描述：引入 `on_llm_request` 钩子职责。
- 配置项清单：补充 `llm_prompt_injection` 配置说明。
- 开源许可章节：说明单一 MIT 协议设计原则。

---

## 6. What's Left to the Builder

- 注入时的具体空白连接符（采用标准的 `\n\n` 隔离段落）。
- 具体每个配置项 hint 的字词精简润色（保持精简凝练、语言通顺）。
- 各测试用例中对应提示词与 Schema 断言的比对细节。
