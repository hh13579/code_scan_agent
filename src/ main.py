from __future__ import annotations

import json
import sys

from code_scan_agent.graph.builder import build_graph
from code_scan_agent.graph.state import GraphState


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m code_scan_agent.main <repo_path>")
        return 1

    repo_path = sys.argv[1]

    app = build_graph()

    init_state: GraphState = {
        "request": {
            "repo_path": repo_path,
            "mode": "full",
            "enable_security_scan": True,
            "enable_fix_suggestion": False,
        },
        "errors": [],
        "logs": [],
        "raw_tool_results": [],
        "normalized_findings": [],
        "triaged_findings": [],
    }

    result = app.invoke(init_state)

    print(json.dumps(result.get("report", {}), ensure_ascii=False, indent=2))

    if result.get("errors"):
        print("\nErrors:")
        for e in result["errors"]:
            print(f"- {e}")

    print("\nLogs:")
    for line in result.get("logs", []):
        print(f"- {line}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())