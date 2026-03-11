from __future__ import annotations

from collections import defaultdict
from typing import Any

from code_scan_agent.graph.state import Finding, GraphState


def _group_findings(findings: list[Finding]) -> tuple[dict[str, list[Finding]], dict[str, list[Finding]]]:
    grouped_by_file: dict[str, list[Finding]] = defaultdict(list)
    grouped_by_severity: dict[str, list[Finding]] = defaultdict(list)

    for finding in findings:
        grouped_by_file[str(finding.get("file", ""))].append(finding)
        grouped_by_severity[str(finding.get("severity", "info"))].append(finding)

    return dict(grouped_by_file), dict(grouped_by_severity)


def _build_summary(grouped_by_severity: dict[str, list[Finding]]) -> dict[str, int]:
    return {
        "total": sum(len(items) for items in grouped_by_severity.values()),
        "critical": len(grouped_by_severity.get("critical", [])),
        "high": len(grouped_by_severity.get("high", [])),
        "medium": len(grouped_by_severity.get("medium", [])),
        "low": len(grouped_by_severity.get("low", [])),
        "info": len(grouped_by_severity.get("info", [])),
    }


def _coerce_findings(raw: Any) -> list[Finding]:
    return list(raw) if isinstance(raw, list) else []


def _select_primary_findings(state: GraphState) -> list[Finding]:
    merged = _coerce_findings(state.get("merged_findings"))
    if merged:
        return merged
    triaged = _coerce_findings(state.get("triaged_findings"))
    if triaged:
        return triaged
    return _coerce_findings(state.get("normalized_findings"))


def build_report(state: GraphState) -> GraphState:
    static_findings = _coerce_findings(
        state.get("static_findings") or state.get("triaged_findings") or state.get("normalized_findings")
    )
    llm_review_findings = _coerce_findings(state.get("llm_review_findings"))
    merged_findings = _coerce_findings(state.get("merged_findings") or static_findings)
    primary_findings = _select_primary_findings(state)

    grouped_by_file, grouped_by_severity = _group_findings(primary_findings)
    static_grouped_by_file, static_grouped_by_severity = _group_findings(static_findings)
    llm_grouped_by_file, llm_grouped_by_severity = _group_findings(llm_review_findings)
    merged_grouped_by_file, merged_grouped_by_severity = _group_findings(merged_findings)

    summary = _build_summary(grouped_by_severity)
    static_summary = _build_summary(static_grouped_by_severity)
    llm_review_summary = _build_summary(llm_grouped_by_severity)
    merged_summary = _build_summary(merged_grouped_by_severity)

    state["report"] = {
        "summary": summary,
        "findings": primary_findings,
        "grouped_by_file": grouped_by_file,
        "grouped_by_severity": grouped_by_severity,
        "static_summary": static_summary,
        "llm_review_summary": llm_review_summary,
        "merged_summary": merged_summary,
        "static_findings": static_findings,
        "llm_review_findings": llm_review_findings,
        "merged_findings": merged_findings,
        "static_grouped_by_file": static_grouped_by_file,
        "static_grouped_by_severity": static_grouped_by_severity,
        "llm_review_grouped_by_file": llm_grouped_by_file,
        "llm_review_grouped_by_severity": llm_grouped_by_severity,
        "merged_grouped_by_file": merged_grouped_by_file,
        "merged_grouped_by_severity": merged_grouped_by_severity,
    }

    state.setdefault("logs", []).append(
        "build_report: "
        f"summary={summary}, static={static_summary}, llm_review={llm_review_summary}, merged={merged_summary}"
    )
    return state
