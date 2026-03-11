from __future__ import annotations

from typing import Literal

try:
    from langgraph.graph import END, START, StateGraph
except Exception:  # noqa: BLE001
    END = "__end__"
    START = "__start__"
    StateGraph = None

from code_scan_agent.graph.state import GraphState
from code_scan_agent.nodes.build_report import build_report
from code_scan_agent.nodes.choose_toolchains import choose_toolchains
from code_scan_agent.nodes.collect_targets import collect_targets
from code_scan_agent.nodes.discover_repo import discover_repo
from code_scan_agent.nodes.finalize import finalize
from code_scan_agent.nodes.llm_triage import llm_triage
from code_scan_agent.nodes.merge_review_findings import merge_review_findings
from code_scan_agent.nodes.normalize_findings import normalize_findings
from code_scan_agent.nodes.review_diff_with_llm import review_diff_with_llm
from code_scan_agent.nodes.run_cpp_scanners import run_cpp_scanners
from code_scan_agent.nodes.run_java_scanners import run_java_scanners
from code_scan_agent.nodes.run_security_scanners import run_security_scanners
from code_scan_agent.nodes.run_ts_scanners import run_ts_scanners


def _route_after_choose_toolchains(
    state: GraphState,
) -> Literal["run_cpp_scanners", "run_java_scanners", "run_ts_scanners", "run_security_scanners", "normalize_findings"]:
    """
    第一版：按优先顺序进入一个扫描节点。
    扫完后每个节点再决定下一个去哪。
    """
    toolchains = state.get("selected_toolchains", {})

    if "cpp" in toolchains and _has_language_targets(state, "cpp") and not _has_scanned(state, "cpp_scanners"):
        return "run_cpp_scanners"
    if "java" in toolchains and _has_language_targets(state, "java") and not _has_scanned(state, "java_scanners"):
        return "run_java_scanners"
    if "ts" in toolchains and _has_language_targets(state, "ts") and not _has_scanned(state, "ts_scanners"):
        return "run_ts_scanners"
    if "security" in toolchains and not _has_scanned(state, "semgrep"):
        return "run_security_scanners"

    return "normalize_findings"


def _route_after_any_scan(
    state: GraphState,
) -> Literal["run_cpp_scanners", "run_java_scanners", "run_ts_scanners", "run_security_scanners", "normalize_findings"]:
    return _route_after_choose_toolchains(state)


def _has_scanned(state: GraphState, tool_name: str) -> bool:
    for item in state.get("raw_tool_results", []):
        if item.get("tool") == tool_name:
            return True
    return False


def _has_language_targets(state: GraphState, language: str) -> bool:
    for item in state.get("targets", []):
        if item.get("language") == language:
            return True
    return False


def build_graph():
    if StateGraph is None:
        return _build_fallback_graph()

    graph = StateGraph(GraphState)

    graph.add_node("discover_repo", discover_repo)
    graph.add_node("collect_targets", collect_targets)
    graph.add_node("choose_toolchains", choose_toolchains)
    graph.add_node("run_cpp_scanners", run_cpp_scanners)
    graph.add_node("run_java_scanners", run_java_scanners)
    graph.add_node("run_ts_scanners", run_ts_scanners)
    graph.add_node("run_security_scanners", run_security_scanners)
    graph.add_node("normalize_findings", normalize_findings)
    graph.add_node("llm_triage", llm_triage)
    graph.add_node("review_diff_with_llm", review_diff_with_llm)
    graph.add_node("merge_review_findings", merge_review_findings)
    graph.add_node("build_report", build_report)
    graph.add_node("finalize", finalize)

    graph.add_edge(START, "discover_repo")
    graph.add_edge("discover_repo", "collect_targets")
    graph.add_edge("collect_targets", "choose_toolchains")

    graph.add_conditional_edges(
        "choose_toolchains",
        _route_after_choose_toolchains,
        {
            "run_cpp_scanners": "run_cpp_scanners",
            "run_java_scanners": "run_java_scanners",
            "run_ts_scanners": "run_ts_scanners",
            "run_security_scanners": "run_security_scanners",
            "normalize_findings": "normalize_findings",
        },
    )

    # 每个扫描节点扫完后，继续决定是否还有下一个扫描节点
    graph.add_conditional_edges(
        "run_cpp_scanners",
        _route_after_any_scan,
        {
            "run_cpp_scanners": "run_cpp_scanners",
            "run_java_scanners": "run_java_scanners",
            "run_ts_scanners": "run_ts_scanners",
            "run_security_scanners": "run_security_scanners",
            "normalize_findings": "normalize_findings",
        },
    )

    graph.add_conditional_edges(
        "run_java_scanners",
        _route_after_any_scan,
        {
            "run_cpp_scanners": "run_cpp_scanners",
            "run_java_scanners": "run_java_scanners",
            "run_ts_scanners": "run_ts_scanners",
            "run_security_scanners": "run_security_scanners",
            "normalize_findings": "normalize_findings",
        },
    )

    graph.add_conditional_edges(
        "run_ts_scanners",
        _route_after_any_scan,
        {
            "run_cpp_scanners": "run_cpp_scanners",
            "run_java_scanners": "run_java_scanners",
            "run_ts_scanners": "run_ts_scanners",
            "run_security_scanners": "run_security_scanners",
            "normalize_findings": "normalize_findings",
        },
    )

    graph.add_conditional_edges(
        "run_security_scanners",
        _route_after_any_scan,
        {
            "run_cpp_scanners": "run_cpp_scanners",
            "run_java_scanners": "run_java_scanners",
            "run_ts_scanners": "run_ts_scanners",
            "run_security_scanners": "run_security_scanners",
            "normalize_findings": "normalize_findings",
        },
    )

    graph.add_edge("normalize_findings", "llm_triage")
    graph.add_edge("llm_triage", "review_diff_with_llm")
    graph.add_edge("review_diff_with_llm", "merge_review_findings")
    graph.add_edge("merge_review_findings", "build_report")
    graph.add_edge("build_report", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()


class _FallbackGraph:
    def invoke(self, state: GraphState) -> GraphState:
        state = discover_repo(state)
        state = collect_targets(state)
        state = choose_toolchains(state)

        node_map = {
            "run_cpp_scanners": run_cpp_scanners,
            "run_java_scanners": run_java_scanners,
            "run_ts_scanners": run_ts_scanners,
            "run_security_scanners": run_security_scanners,
        }

        while True:
            nxt = _route_after_choose_toolchains(state)
            if nxt == "normalize_findings":
                break
            state = node_map[nxt](state)

        state = normalize_findings(state)
        state = llm_triage(state)
        state = review_diff_with_llm(state)
        state = merge_review_findings(state)
        state = build_report(state)
        state = finalize(state)
        return state


def _build_fallback_graph() -> _FallbackGraph:
    return _FallbackGraph()
