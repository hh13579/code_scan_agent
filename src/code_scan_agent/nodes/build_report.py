from __future__ import annotations

from collections import defaultdict

from code_scan_agent.graph.state import GraphState


def build_report(state: GraphState) -> GraphState:
    findings = state.get("triaged_findings", [])

    grouped_by_file = defaultdict(list)
    grouped_by_severity = defaultdict(list)

    for f in findings:
        grouped_by_file[f["file"]].append(f)
        grouped_by_severity[f["severity"]].append(f)

    summary = {
        "total": len(findings),
        "critical": len(grouped_by_severity["critical"]),
        "high": len(grouped_by_severity["high"]),
        "medium": len(grouped_by_severity["medium"]),
        "low": len(grouped_by_severity["low"]),
        "info": len(grouped_by_severity["info"]),
    }

    state["report"] = {
        "summary": summary,
        "findings": findings,
        "grouped_by_file": dict(grouped_by_file),
        "grouped_by_severity": dict(grouped_by_severity),
    }

    state.setdefault("logs", []).append(f"build_report: summary={summary}")
    return state