from __future__ import annotations

from collections import defaultdict
from typing import Any

from code_scan_agent.graph.state import GraphState


_SEVERITIES = ("critical", "high", "medium", "low", "info")
_SEV_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}
_REVIEW_ACTION_ORDER = {
    "block": 0,
    "should_fix": 1,
    "follow_up": 2,
    "": 3,
}
_VERIFICATION_ORDER = {
    "strengthened": 0,
    "unchanged": 1,
    "weak": 2,
    "": 3,
}
_EVIDENCE_COMPLETENESS_ORDER = {
    "complete": 0,
    "strong": 1,
    "partial": 2,
    "": 3,
}


def _safe_findings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [x for x in value if isinstance(x, dict)]


def _severity_of(f: dict[str, Any]) -> str:
    sev = str(f.get("severity", "info")).lower()
    if sev not in _SEVERITIES:
        return "info"
    return sev


def _group_by_file(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = defaultdict(list)
    for f in findings:
        grouped[str(f.get("file", ""))].append(f)
    return dict(grouped)


def _group_by_severity(findings: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped = defaultdict(list)
    for f in findings:
        grouped[_severity_of(f)].append(f)
    return {sev: grouped.get(sev, []) for sev in _SEVERITIES}


def _bug_class_of(f: dict[str, Any]) -> str:
    bug_class = str(f.get("bug_class", "")).strip().lower()
    if bug_class:
        return bug_class
    return str(f.get("category", "other")).strip().lower() or "other"


def _build_bug_class_summary(findings: list[dict[str, Any]]) -> dict[str, int]:
    grouped: dict[str, int] = {}
    for finding in findings:
        bug_class = _bug_class_of(finding)
        grouped[bug_class] = grouped.get(bug_class, 0) + 1
    return dict(sorted(grouped.items(), key=lambda item: (-item[1], item[0])))


def _build_evidence_completeness_summary(findings: list[dict[str, Any]]) -> dict[str, int]:
    grouped = {"complete": 0, "strong": 0, "partial": 0, "": 0}
    for finding in findings:
        key = str(finding.get("evidence_completeness", "")).strip().lower()
        grouped[key if key in grouped else ""] += 1
    return grouped


def _build_summary(findings: list[dict[str, Any]]) -> dict[str, int]:
    grouped = _group_by_severity(findings)
    return {
        "total": len(findings),
        "critical": len(grouped["critical"]),
        "high": len(grouped["high"]),
        "medium": len(grouped["medium"]),
        "low": len(grouped["low"]),
        "info": len(grouped["info"]),
    }


def _line_of(f: dict[str, Any]) -> int:
    try:
        line = f.get("line")
        if line is None:
            return 10**9
        return int(line)
    except Exception:
        return 10**9


def _is_llm_review_finding(f: dict[str, Any]) -> bool:
    source = str(f.get("source", "")).strip().lower()
    tool = str(f.get("tool", "")).strip().lower()
    return source == "llm_diff_review" or tool == "llm_diff_review"


def _has_impact(f: dict[str, Any]) -> bool:
    return bool(str(f.get("impact", "")).strip())


def _has_evidence(f: dict[str, Any]) -> bool:
    evidence = f.get("evidence", [])
    if isinstance(evidence, list):
        return any(str(item).strip() for item in evidence)
    if isinstance(evidence, str):
        return bool(evidence.strip())
    return False


def _top_issue_sort_key(f: dict[str, Any]):
    """
    top_issues 的排序逻辑（从最值得关注到较次要）：
    1. review_action: block > should_fix > follow_up
    2. severity: critical > high > medium > low > info
    3. LLM semantic finding 稍微优先（因为通常是“静态扫描补充”的高价值风险）
    4. 有 impact 的优先
    5. 有 evidence 的优先
    6. file / line 稳定排序
    """
    review_action = str(f.get("review_action", "")).strip().lower()
    severity = _severity_of(f)
    verification_status = str(f.get("verification_status", "")).strip().lower()

    return (
        _REVIEW_ACTION_ORDER.get(review_action, 99),
        _SEV_ORDER.get(severity, 99),
        _VERIFICATION_ORDER.get(verification_status, 99),
        _EVIDENCE_COMPLETENESS_ORDER.get(str(f.get("evidence_completeness", "")).strip().lower(), 99),
        0 if _is_llm_review_finding(f) else 1,
        0 if _has_impact(f) else 1,
        0 if _has_evidence(f) else 1,
        str(f.get("file", "")),
        _line_of(f),
    )


def _build_top_issues(findings: list[dict[str, Any]], max_items: int = 5) -> list[dict[str, Any]]:
    """
    选出最值得报告首页展示的问题。
    规则：
    - 优先 block / high-risk
    - 去掉明显过于弱的信息类项
    - 尽量避免同一 file+line 重复过多
    """
    if not findings:
        return []

    sorted_findings = sorted(findings, key=_top_issue_sort_key)

    picked: list[dict[str, Any]] = []
    seen_locs: set[tuple[str, int]] = set()

    for f in sorted_findings:
        severity = _severity_of(f)
        review_action = str(f.get("review_action", "")).strip().lower()

        # 极弱信息项不进 top_issues
        if severity == "info" and review_action not in {"block", "should_fix"}:
            continue

        loc_key = (str(f.get("file", "")), _line_of(f))
        # 避免同一 file+line 塞太多相似问题
        if loc_key in seen_locs and review_action != "block":
            continue

        picked.append(f)
        seen_locs.add(loc_key)

        if len(picked) >= max_items:
            break

    return picked


def build_report(state: GraphState) -> GraphState:
    """
    优先级：
    1. merged_findings / llm_review_findings（主报告默认只展示 LLM 审查结果）
    2. triaged_findings（仅作为旧流程兼容 fallback）
    3. normalized_findings

    额外输出：
    - static_summary
    - llm_review_summary
    - merged_summary
    - top_issues
    """
    static_findings = _safe_findings(
        state.get("static_findings")
        or state.get("triaged_findings")
        or state.get("normalized_findings")
        or []
    )
    llm_review_findings = _safe_findings(state.get("llm_review_findings") or [])
    merged_findings = _safe_findings(
        state.get("merged_findings")
        or []
    )
    display_findings = merged_findings or llm_review_findings
    has_llm_pipeline_fields = "merged_findings" in state or "llm_review_findings" in state
    if not has_llm_pipeline_fields:
        display_findings = _safe_findings(
            state.get("triaged_findings")
            or state.get("normalized_findings")
            or []
        )

    grouped_by_file = _group_by_file(display_findings)
    grouped_by_severity = _group_by_severity(display_findings)

    static_grouped_by_file = _group_by_file(static_findings)
    static_grouped_by_severity = _group_by_severity(static_findings)

    llm_grouped_by_file = _group_by_file(llm_review_findings)
    llm_grouped_by_severity = _group_by_severity(llm_review_findings)
    merged_grouped_by_file = _group_by_file(display_findings)
    merged_grouped_by_severity = _group_by_severity(display_findings)

    merged_summary = _build_summary(display_findings)
    static_summary = _build_summary(static_findings)
    llm_review_summary = _build_summary(llm_review_findings)
    bug_class_summary = _build_bug_class_summary(display_findings)
    evidence_completeness_summary = _build_evidence_completeness_summary(display_findings)

    top_issues = _build_top_issues(display_findings, max_items=5)

    report = {
        # 默认主视图 = 可报告结果（优先 LLM 审查）
        "summary": merged_summary,
        "findings": display_findings,
        "grouped_by_file": grouped_by_file,
        "grouped_by_severity": grouped_by_severity,
        "bug_class_summary": bug_class_summary,
        "evidence_completeness_summary": evidence_completeness_summary,

        # 新增：首页摘要可直接消费
        "top_issues": top_issues,

        # 分来源统计
        "static_summary": static_summary,
        "llm_review_summary": llm_review_summary,
        "merged_summary": merged_summary,

        "static_findings": static_findings,
        "llm_review_findings": llm_review_findings,
        "merged_findings": display_findings,

        "static_grouped_by_file": static_grouped_by_file,
        "static_grouped_by_severity": static_grouped_by_severity,

        "llm_review_grouped_by_file": llm_grouped_by_file,
        "llm_review_grouped_by_severity": llm_grouped_by_severity,
        "merged_grouped_by_file": merged_grouped_by_file,
        "merged_grouped_by_severity": merged_grouped_by_severity,
    }

    state["report"] = report
    state.setdefault("logs", []).append(
        "build_report: "
        f"static={static_summary['total']}, "
        f"llm_review={llm_review_summary['total']}, "
        f"reportable={merged_summary['total']}, "
        f"top_issues={len(top_issues)}"
    )
    return state
