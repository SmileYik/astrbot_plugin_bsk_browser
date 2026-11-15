"""网站白名单与普通用户工具动作权限匹配模块。"""

from __future__ import annotations

from typing import Any, Sequence
from urllib.parse import urlparse

__all__ = [
    "check_site_permission",
    "is_action_allowed",
    "is_domain_match",
    "normalize_domain",
]


def normalize_domain(url_or_host: str) -> str:
    """提取并归一化域名（小写、移除端口、剥离 www. 前缀）。"""
    s = str(url_or_host or "").strip()
    if not s:
        return ""
    if "://" not in s and not s.startswith("//"):
        s = f"http://{s}"
    try:
        parsed = urlparse(s)
        netloc = parsed.netloc or parsed.path.split("/")[0]
        host = netloc.split(":")[0].strip().lower()
        if host.startswith("www.") and len(host) > 4:
            host = host[4:]
        return host
    except Exception:
        return ""


def is_domain_match(pattern: str, target: str) -> bool:
    """判断 target 域名是否符合 pattern 规则（支持子域名匹配）。"""
    pat = normalize_domain(pattern)
    tgt = normalize_domain(target)
    if not pat or not tgt:
        return False
    if pat == tgt:
        return True
    if tgt.endswith(f".{pat}"):
        return True
    return False


def is_action_allowed(allowed_actions: Sequence[str], tool: str, action: str) -> bool:
    """判断 tool.action 是否在 allowed_actions 中。"""
    tool_clean = str(tool or "").strip().lower()
    action_clean = str(action or "").strip().lower()
    action_alt = action_clean.replace("-", "_") if "-" in action_clean else action_clean.replace("_", "-")
    full_act = f"{tool_clean}.{action_clean}"
    full_alt = f"{tool_clean}.{action_alt}"

    for rule in allowed_actions:
        r = str(rule or "").strip().lower()
        if not r:
            continue
        if r in ("*", "*.*"):
            return True
        if r in (full_act, full_alt):
            return True
        if r in (action_clean, action_alt, f"*.{action_clean}", f"*.{action_alt}"):
            return True
        if r in (tool_clean, f"{tool_clean}.*"):
            return True
    return False


def check_site_permission(
    site_whitelist: Sequence[dict[str, Any]],
    current_url: str,
    tool: str,
    action: str,
) -> tuple[bool, str]:
    """校验指定 URL 上执行 tool.action 是否被白名单允许。"""
    tool_clean = str(tool or "").strip().lower()
    action_clean = str(action or "").strip().lower()

    if not current_url:
        return False, "当前会话尚未打开任何网页，无法在该网站上执行此操作。"

    target_domain = normalize_domain(current_url)
    if not target_domain:
        return False, f"无法从当前网址（{current_url}）识别有效域名。"

    matched_rule: dict[str, Any] | None = None
    for rule in site_whitelist:
        if not isinstance(rule, dict):
            continue
        dom_pat = rule.get("domain", "")
        if is_domain_match(dom_pat, target_domain):
            matched_rule = rule
            break

    if not matched_rule:
        return False, f"目标网站（{target_domain}）不在允许访问的白名单中。"

    if (tool_clean == "bsk_page" and action_clean == "navigate") or (
        tool_clean == "bsk_session" and action_clean == "open"
    ):
        return True, ""

    allowed = matched_rule.get("allowed_actions") or ()
    if is_action_allowed(allowed, tool_clean, action_clean):
        return True, ""

    action_label = f"{tool_clean}(action='{action_clean}')"
    return (
        False,
        f"当前网站（{target_domain}）未向普通用户开放该操作（{action_label}）。",
    )
