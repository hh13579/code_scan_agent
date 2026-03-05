from __future__ import annotations

import json
import sys
from pathlib import Path

from code_scan_agent.graph.builder import build_graph
from code_scan_agent.graph.state import GraphState


def _find_repo_root_for_file(file_path: Path) -> Path:
    """
    优先使用 git root；找不到则使用文件所在目录。
    """
    current = file_path.resolve().parent
    for p in [current, *current.parents]:
        if (p / ".git").exists():
            return p
    return current


def _build_request_from_target(target: Path) -> dict[str, object]:
    if target.is_file():
        repo_root = _find_repo_root_for_file(target)
        selected = str(target.resolve())
        return {
            "repo_path": str(repo_root),
            "mode": "selected",
            "selected_paths": [selected],
            "enable_security_scan": True,
            "enable_fix_suggestion": False,
        }

    return {
        "repo_path": str(target),
        "mode": "full",
        "enable_security_scan": True,
        "enable_fix_suggestion": False,
    }


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python -m code_scan_agent.main <repo_path_or_file_path>")
        return 1

    raw_target = Path(sys.argv[1]).expanduser().resolve()
    if not raw_target.exists():
        print(f"Path not found: {raw_target}")
        return 1

    app = build_graph()

    init_state: GraphState = {
        "request": _build_request_from_target(raw_target),  # type: ignore[typeddict-item]
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
