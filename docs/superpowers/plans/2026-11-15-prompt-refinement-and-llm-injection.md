# Prompt Refinement and LLM Prompt Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 精简插件中面向用户与模型的冗长提示文本，增加基于权限守卫的「LLM提示词注入」长文本配置项，统一收敛为单一 MIT 开源许可，署名增加 SmileYik，并同步更新 ARCHITECTURE 架构文档与合规测试。

**Architecture:** 
- 提示词注入：在 `main.py` 通过 `@filter.on_llm_request()` 挂钩，直接复用既有的 `self._denied(event)` 鉴权门；仅当用户具备浏览器操作权限且注入配置非空时，将提示词安全追加至 `req.system_prompt`。
- 配置体系：在 `_conf_schema.json` 与 `bsk/config.py` 的 `Settings` 增加强类型 `llm_prompt_injection: str`，严格保持两者默认值与字段 1:1 一致。
- 文本精炼：端到端精炼 `_conf_schema.json`、`metadata.yaml`、`bsk/tools.py`、`bsk/errors.py`、`main.py` 以及 `skills/` 文档，去除冗长背景与测试跑分，保持指令精准凝练。
- 许可与合规：移除 `LICENSE-AGPL`，仅保留纯 MIT，更新合规测试脚本及作者元数据。

**Tech Stack:** Python 3.12+, AstrBot API (`@filter.on_llm_request`, `ProviderRequest`, `AstrMessageEvent`), JSON Schema, unittest / pytest.

**Spec:** [2026-11-15-prompt-refinement-and-llm-injection-design.md](file:///run/media/smileyik/G/Workspace/ai/bsk/astrbot_plugin_bsk_browser/docs/superpowers/specs/2026-11-15-prompt-refinement-and-llm-injection-design.md)

## Global Constraints

- 仅允许修改 `./astrbot_plugin_bsk_browser/` 仓库，不得修改其他目录。
- 框架耦合仅允许出现在 `main.py`，`bsk/` 包保持纯 Python（零 astrbot、零 logging 依赖）。
- 日志输出严格使用 AstrBot 日志系统，工具调用与关键交互以 DEBUG 等级记录。
- `_conf_schema.json` 字段与 `bsk/config.py` 的 `Settings` 必须严格 1:1 对应（`INJECTED_FIELDS` 除外）。
- 仓库内仅保留 MIT 协议，删除 `LICENSE-AGPL`，作者署名添加 `SmileYik`（`JosephTian876, SmileYik`）。
- 每次任务完成后必须执行 git commit。

## Review Focus

1. **未授权用户提示词防泄漏**：当普通用户无浏览器权限（如 `admin_only=True` 且非白名单用户）发送消息触发大模型请求时，必须严格拦截注入，不得泄露浏览器系统提示词。
2. **空提示词或空白字符注入守卫**：当 `llm_prompt_injection` 未配置、为空字符串或仅含空格时，不得对 `req.system_prompt` 作任何改动（包括不得多追加换行符）。
3. **既有系统提示词拼接完备性**：当 `req.system_prompt` 已有内容（如人设预设）时，追加格式需为 `f"{curr}\n\n{prompt}"`；若既有为空，则直接赋值，避免出现前置多余换行。
4. **Schema 默认值与字段漂移**：`_conf_schema.json` 中的 `default: ""` 必须与 `bsk/config.py` 中的 `DEFAULT_LLM_PROMPT_INJECTION` 完全一致，且类型在 AstrBot 允许白名单内。
5. **合规测试断言回归**：删除 `LICENSE-AGPL` 后，`tests/verify_compliance.py` 与 `tests/verify_release_ready.py` 必须同步调整断言，防止 CI / 自检误报缺少 AGPL 文件。

---

### Task 1: LLM 提示词注入配置项扩展与校验

**Files:**
- Modify: `astrbot_plugin_bsk_browser/_conf_schema.json`
- Modify: `astrbot_plugin_bsk_browser/bsk/config.py`
- Test: `astrbot_plugin_bsk_browser/tests/test_config.py`

**Interfaces:**
- Consumes: `Settings` dataclass structure from `bsk/config.py`
- Produces: `DEFAULT_LLM_PROMPT_INJECTION = ""` and `Settings.llm_prompt_injection: str`

- [ ] **Step 1: Write the failing tests in `tests/test_config.py`**
  在 `TestDefaults` 中添加对 `s.llm_prompt_injection == ""` 的断言，并在 `TestFullValidConfig` 中测试解析自定义注入文本。

```python
    def test_default_prompt_injection(self) -> None:
        s = parse_settings(None)
        self.assertEqual(s.llm_prompt_injection, "")

    def test_prompt_injection_parsed_and_trimmed(self) -> None:
        s = parse_settings({"llm_prompt_injection": "  请优先使用浏览器搜索  "})
        self.assertEqual(s.llm_prompt_injection, "请优先使用浏览器搜索")
```

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest astrbot_plugin_bsk_browser/tests/test_config.py -k "prompt_injection" -v`
  Expected: FAIL (AttributeError: 'Settings' object has no attribute 'llm_prompt_injection')

- [ ] **Step 3: Update `_conf_schema.json` and `bsk/config.py`**
  1. 在 `_conf_schema.json` 中添加：
  ```json
  "llm_prompt_injection": {
    "description": "LLM提示词注入",
    "type": "text",
    "default": "",
    "hint": "当前用户具备浏览器操作权限时追加到系统提示词中；留空则不注入。"
  }
  ```
  2. 在 `bsk/config.py` 中导出 `DEFAULT_LLM_PROMPT_INJECTION = ""`，向 `Settings` 类增加字段 `llm_prompt_injection: str = DEFAULT_LLM_PROMPT_INJECTION`，并在 `parse_settings` 中解析：
  ```python
  raw_inj = raw.get("llm_prompt_injection")
  llm_prompt_injection = str(raw_inj).strip() if raw_inj is not None else DEFAULT_LLM_PROMPT_INJECTION
  ```

- [ ] **Step 4: Run test to verify it passes**
  Run: `pytest astrbot_plugin_bsk_browser/tests/test_config.py -v`
  Expected: PASS（包括字段一一对应检查与默认值比对）

- [ ] **Step 5: Commit**
  ```bash
  git -C astrbot_plugin_bsk_browser add _conf_schema.json bsk/config.py tests/test_config.py
  git -C astrbot_plugin_bsk_browser commit -m "feat(config): add llm_prompt_injection text configuration option"
  ```

---

### Task 2: 实现 `@filter.on_llm_request()` 钩子与鉴权守卫

**Files:**
- Modify: `astrbot_plugin_bsk_browser/main.py`
- Create: `astrbot_plugin_bsk_browser/tests/test_llm_request_injection.py`

**Interfaces:**
- Consumes: `ProviderRequest`, `AstrMessageEvent`, `filter.on_llm_request`, `self._denied(event)`
- Produces: `on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None`

- [ ] **Step 1: Write the failing tests in `tests/test_llm_request_injection.py`**
  编写单元测试覆盖以下 5 种场景：
  1. 提示词为空或空白字符时，不注入；
  2. 插件被全局禁用（`enabled=False`）时，不注入；
  3. 普通用户无管理员权限且 `admin_only=True` 时，不注入；
  4. 授权用户且既有 `req.system_prompt` 为空时，直接赋值注入提示词；
  5. 授权用户且既有 `req.system_prompt` 有预设内容时，以 `\n\n` 安全追加。

- [ ] **Step 2: Run test to verify it fails**
  Run: `pytest astrbot_plugin_bsk_browser/tests/test_llm_request_injection.py -v`
  Expected: FAIL (Plugin has no on_llm_request or hook not defined)

- [ ] **Step 3: Implement `on_llm_request` in `main.py`**
  从 `astrbot.api.provider` 引入 `ProviderRequest`，在 `BskBrowserPlugin` 类中定义：
  ```python
  @filter.on_llm_request()
  async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
      """当用户拥有浏览器操作权限且配置了注入内容时，向 system_prompt 注入自定义提示词。"""
      prompt = (getattr(self.settings, "llm_prompt_injection", "") or "").strip()
      if not prompt or self._denied(event) is not None:
          return

      curr = getattr(req, "system_prompt", "") or ""
      if curr:
          req.system_prompt = f"{curr}\n\n{prompt}"
      else:
          req.system_prompt = prompt
  ```

- [ ] **Step 4: Run tests to verify it passes**
  Run: `pytest astrbot_plugin_bsk_browser/tests/test_llm_request_injection.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git -C astrbot_plugin_bsk_browser add main.py tests/test_llm_request_injection.py
  git -C astrbot_plugin_bsk_browser commit -m "feat(plugin): implement on_llm_request hook for authorized prompt injection"
  ```

---

### Task 3: 仓库开源协议单一 MIT 化与作者署名补充

**Files:**
- Delete: `astrbot_plugin_bsk_browser/LICENSE-AGPL`
- Verify: `astrbot_plugin_bsk_browser/LICENSE`
- Modify: `astrbot_plugin_bsk_browser/metadata.yaml`
- Modify: `astrbot_plugin_bsk_browser/README.md`
- Modify: `astrbot_plugin_bsk_browser/CHANGELOG.md`
- Modify: `astrbot_plugin_bsk_browser/tests/verify_compliance.py`
- Modify: `astrbot_plugin_bsk_browser/tests/verify_release_ready.py`

**Interfaces:**
- Consumes: Single MIT license policy, dual authorship (`JosephTian876, SmileYik`)
- Produces: Clean license state passing `verify_compliance.py`

- [ ] **Step 1: Write / update tests for single MIT license in compliance scripts**
  修改 `tests/verify_compliance.py` 与 `tests/verify_release_ready.py`：
  - 移除对 `LICENSE-AGPL 存在` 及 `LICENSE-AGPL 是完整 AGPL-3.0 文本` 的断言；
  - 增加断言 `assert not (PROJECT / "LICENSE-AGPL").exists()`；
  - 将 README 许可检查项更新为 `README 声明 MIT 许可`；
  - 检查 `metadata.yaml` 中的 author 字段包含 `SmileYik` 与 `JosephTian876`。

- [ ] **Step 2: Run compliance check to verify failure**
  Run: `python astrbot_plugin_bsk_browser/tests/verify_compliance.py`
  Expected: FAIL (before deleting LICENSE-AGPL or before updating author)

- [ ] **Step 3: Execute license removal and metadata updates**
  1. 删除 `astrbot_plugin_bsk_browser/LICENSE-AGPL`；
  2. 确认 `LICENSE` 为标准 MIT 全文；
  3. 更新 `metadata.yaml`：
     - `author: JosephTian876, SmileYik`
     - 更新 `desc` 末尾的许可证描述为纯 MIT 声明；
  4. 更新 `README.md` 与 `CHANGELOG.md`：
     - 将第 12 节的双许可声明改为单一 MIT 声明；
     - 标注共同作者 SmileYik。

- [ ] **Step 4: Run compliance check to verify passes**
  Run: `python astrbot_plugin_bsk_browser/tests/verify_compliance.py`
  Expected: PASS（26 项或更新后的项全部通过）

- [ ] **Step 5: Commit**
  ```bash
  git -C astrbot_plugin_bsk_browser rm LICENSE-AGPL
  git -C astrbot_plugin_bsk_browser add metadata.yaml README.md CHANGELOG.md tests/verify_compliance.py tests/verify_release_ready.py LICENSE
  git -C astrbot_plugin_bsk_browser commit -m "chore(license): converge to pure MIT license and add SmileYik as author"
  ```

---

### Task 4: 面向用户与面向 LLM 的提示文本全量精简

**Files:**
- Modify: `astrbot_plugin_bsk_browser/_conf_schema.json`
- Modify: `astrbot_plugin_bsk_browser/metadata.yaml`
- Modify: `astrbot_plugin_bsk_browser/bsk/tools.py`
- Modify: `astrbot_plugin_bsk_browser/bsk/errors.py`
- Modify: `astrbot_plugin_bsk_browser/bsk/config.py`
- Modify: `astrbot_plugin_bsk_browser/main.py`
- Modify: `astrbot_plugin_bsk_browser/skills/bsk-browser/SKILL.md`
- Modify: `astrbot_plugin_bsk_browser/skills/bsk-browse-baidu/SKILL.md`
- Modify: `astrbot_plugin_bsk_browser/skills/bsk-browse-bingcn/SKILL.md`

**Interfaces:**
- Consumes: 精炼文本规范（准确明确、紧凑凝练、无多余解释与跑分）
- Produces: Streamlined schema, error messages, tool descriptions, and skills docs

- [ ] **Step 1: Check existing doc and schema tests**
  Run: `pytest astrbot_plugin_bsk_browser/tests/test_skills_doc.py astrbot_plugin_bsk_browser/tests/test_tools.py astrbot_plugin_bsk_browser/tests/test_config.py -v`
  Expected: PASS (establish baseline)

- [ ] **Step 2: Streamline `_conf_schema.json` & `metadata.yaml`**
  - 精简 `_conf_schema.json` 中全部 26 个配置项的 `hint` 与 `description`，去除诸如维基百科长条目11.7秒等无关跑分与长篇历史解释；
  - 精简 `metadata.yaml` 的 `desc`，结构紧凑清晰（概述、工具概览、前置条件、安全提醒、开源许可）。

- [ ] **Step 3: Streamline `bsk/tools.py` & `bsk/errors.py` & `main.py`**
  - 精简 `bsk/tools.py` 中 `TOOL_DESCRIPTIONS` 与 `_DEBUG_PROPERTY_DESCRIPTIONS`；
  - 精简 `bsk/errors.py` 中 `classify()` 的 `friendly` 文案，强化“原因 + 建议动作”；
  - 精简 `bsk/config.py` 中 `validate_settings()` 的提示文案；
  - 精简 `main.py` 中 `_denied` 与 `_evaluate_denied` 的提示文案。

- [ ] **Step 4: Refine `skills/` documents**
  - 检查并精简 `skills/bsk-browser/SKILL.md`，保持精炼但涵盖所有工具调用、截图与标签页关闭生命周期；
  - 检查并精简 `skills/bsk-browse-baidu/SKILL.md` 与 `skills/bsk-browse-bingcn/SKILL.md`，专精搜索交互。

- [ ] **Step 5: Run tests to verify all pass without regressions**
  Run: `pytest astrbot_plugin_bsk_browser/tests/ -v`
  Expected: PASS

- [ ] **Step 6: Commit**
  ```bash
  git -C astrbot_plugin_bsk_browser add _conf_schema.json metadata.yaml bsk/tools.py bsk/errors.py bsk/config.py main.py skills/
  git -C astrbot_plugin_bsk_browser commit -m "refactor(prompts): streamline user-facing and LLM-facing prompt texts"
  ```

---

### Task 5: 同步 `ARCHITECTURE.md` 架构文档与全量测试自检

**Files:**
- Modify: `astrbot_plugin_bsk_browser/ARCHITECTURE.md`

**Interfaces:**
- Consumes: Final codebase state from Tasks 1-4
- Produces: Up-to-date `ARCHITECTURE.md` matching implementation

- [ ] **Step 1: Update `ARCHITECTURE.md`**
  1. 更新顶部版本、日期与作者列表（补充 `SmileYik`）；
  2. 在架构图与分层责任表中加入 `on_llm_request` 提示词注入职责；
  3. 在配置清单章节中增加 `llm_prompt_injection` 配置项说明；
  4. 更新开源协议章节（移除双许可描述，明确为纯 MIT 协议）；
  5. 记录文本精炼与提示词 Token 控制原则。

- [ ] **Step 2: Run complete test suite and compliance checks**
  Run: `pytest astrbot_plugin_bsk_browser/tests -v`
  Run: `python astrbot_plugin_bsk_browser/tests/verify_compliance.py`
  Expected: PASS (所有单元测试与合规脚本 100% 成功)

- [ ] **Step 3: Check git status and commit**
  ```bash
  git -C astrbot_plugin_bsk_browser add ARCHITECTURE.md
  git -C astrbot_plugin_bsk_browser commit -m "docs: synchronize ARCHITECTURE.md with latest design, license, and features"
  ```
