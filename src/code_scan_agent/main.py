from __future__ import annotations

import argparse
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


def _build_request_from_target(
    *,
    target: Path,
    mode: str,
    diff_base_ref: str,
    diff_head_ref: str,
    diff_commit: str,
    diff_staged: bool,
) -> dict[str, object]:
    if target.is_file():
        if mode in {"full", "diff"}:
            raise ValueError("File target only supports mode=selected or mode=auto")
        repo_root = _find_repo_root_for_file(target)
        selected = str(target.resolve())
        return {
            "repo_path": str(repo_root),
            "mode": "selected",
            "selected_paths": [selected],
            "enable_security_scan": True,
            "enable_fix_suggestion": False,
        }

    if mode == "selected":
        raise ValueError("Directory target does not support mode=selected")

    mode_for_repo = "full" if mode == "auto" else mode
    return {
        "repo_path": str(target),
        "mode": mode_for_repo,
        "enable_security_scan": True,
        "enable_fix_suggestion": False,
        "diff_base_ref": diff_base_ref,
        "diff_head_ref": diff_head_ref,
        "diff_commit": diff_commit,
        "diff_staged": diff_staged,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="python -m code_scan_agent.main",
        description="Code scan agent entry",
    )
    parser.add_argument("target", help="Repository path or single file path")
    parser.add_argument(
        "--mode",
        choices=["auto", "full", "selected", "diff"],
        default="auto",
        help="Scan mode. auto: file->selected, dir->full",
    )
    parser.add_argument(
        "--diff-base-ref",
        default="",
        help="Git base ref for diff mode (optional)",
    )
    parser.add_argument(
        "--diff-head-ref",
        default="",
        help="Git head ref for diff mode (optional)",
    )
    parser.add_argument(
        "--diff-commit",
        default="",
        help="Scan changes introduced by a single commit (only for mode=diff)",
    )
    parser.add_argument(
        "--diff-staged",
        action="store_true",
        help="Use staged changes only when mode=diff and no base/head refs",
    )
    args = parser.parse_args(sys.argv[1:])

    raw_target = Path(args.target).expanduser().resolve()
    if not raw_target.exists():
        print(f"Path not found: {raw_target}")
        return 1

    diff_base_ref = args.diff_base_ref.strip()
    diff_head_ref = args.diff_head_ref.strip()
    diff_commit = args.diff_commit.strip()
    if diff_commit and (diff_base_ref or diff_head_ref):
        print("Invalid arguments: --diff-commit cannot be used with --diff-base-ref/--diff-head-ref")
        return 1

    try:
        request = _build_request_from_target(
            target=raw_target,
            mode=args.mode,
            diff_base_ref=diff_base_ref,
            diff_head_ref=diff_head_ref,
            diff_commit=diff_commit,
            diff_staged=args.diff_staged,
        )
    except ValueError as e:
        print(f"Invalid arguments: {e}")
        return 1

    app = build_graph()

    init_state: GraphState = {
        "request": request,  # type: ignore[typeddict-item]
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
