from __future__ import annotations

from code_scan_agent.graph.state import GraphState


def finalize(state: GraphState) -> GraphState:
    state.setdefault("logs", []).append("finalize: graph execution completed")
    return state