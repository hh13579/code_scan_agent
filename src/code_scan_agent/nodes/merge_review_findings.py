from __future__ import annotations

from typing import Any

from code_scan_agent.graph.state import GraphState


def _line_distance(lhs: object, rhs: object) -> int | None:
    try:
        left = int(lhs)  # type: ignore[arg-type]
        right = int(rhs)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return abs(left - right)


def _overlaps_static(llm_item: dict[str, Any], static_item: dict[str, Any]) -> bool:
    if str(llm_item.get("file", "")) != str(static_item.get("file", "")):
        return False

    llm_category = str(llm_item.get("category", "")).strip().lower()
    static_category = str(static_item.get("category", "")).strip().lower()
    if llm_category and static_category and llm_category != static_category:
        return False

    distance = _line_distance(llm_item.get("line"), static_item.get("line"))
    if distance is None:
        return not llm_category or not static_category or llm_category == static_category
    return distance <= 3


def merge_review_findings(state: GraphState) -> GraphState:
    static_findings = list(state.get("triaged_findings") or state.get("normalized_findings") or [])
    llm_review_findings = [dict(item) for item in state.get("llm_review_findings", [])]

    merged_findings = list(static_findings)
    overlap_count = 0

    for item in llm_review_findings:
        overlaps_static = any(_overlaps_static(item, static_item) for static_item in static_findings)
        if overlaps_static:
            overlap_count += 1
            item["overlaps_static"] = True
        merged_findings.append(item)

    state["static_findings"] = static_findings
    state["llm_review_findings"] = llm_review_findings
    state["merged_findings"] = merged_findings
    state.setdefault("logs", []).append(
        "merge_review_findings: "
        f"static={len(static_findings)}, llm_review={len(llm_review_findings)}, "
        f"merged={len(merged_findings)}, overlaps={overlap_count}"
    )
    return state
