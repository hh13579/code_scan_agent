from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from code_scan_agent.graph.builder import build_graph
from code_scan_agent.graph.state import GraphState

_FAIL_ON_LEVELS = ("critical", "high", "medium", "low", "info")
_FAIL_ON_INDEX = {level: idx for idx, level in enumerate(_FAIL_ON_LEVELS)}


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
    diff_range_mode: str,
    diff_findings_filter: str,
    enable_llm_triage: bool | None,
) -> dict[str, object]:
    if target.is_file():
        if mode in {"full", "diff"}:
            raise ValueError("File target only supports mode=selected or mode=auto")
        repo_root = _find_repo_root_for_file(target)
        selected = str(target.resolve())
        request: dict[str, object] = {
            "repo_path": str(repo_root),
            "mode": "selected",
            "selected_paths": [selected],
            "enable_security_scan": True,
            "enable_fix_suggestion": False,
        }
        if enable_llm_triage is not None:
            request["enable_llm_triage"] = enable_llm_triage
        return request

    if mode == "selected":
        raise ValueError("Directory target does not support mode=selected")

    mode_for_repo = "full" if mode == "auto" else mode
    request = {
        "repo_path": str(target),
        "mode": mode_for_repo,
        "enable_security_scan": True,
        "enable_fix_suggestion": False,
        "diff_base_ref": diff_base_ref,
        "diff_head_ref": diff_head_ref,
        "base_ref": diff_base_ref,
        "head_ref": diff_head_ref,
        "diff_commit": diff_commit,
        "diff_staged": diff_staged,
        "diff_range_mode": diff_range_mode,
        "diff_findings_filter": diff_findings_filter,
    }
    if enable_llm_triage is not None:
        request["enable_llm_triage"] = enable_llm_triage
    return request


def _write_report(out_path: Path, report_text: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(f"{report_text}\n", encoding="utf-8")


def _count_failures_at_or_above(summary: dict[str, object], threshold: str) -> int:
    threshold_index = _FAIL_ON_INDEX[threshold]
    total = 0
    for level, index in _FAIL_ON_INDEX.items():
        if index > threshold_index:
            continue
        raw = summary.get(level, 0)
        try:
            total += int(raw)
        except (TypeError, ValueError):
            continue
    return total


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
        "--base",
        dest="diff_base_ref",
        default="",
        help="Git base ref for diff mode (optional)",
    )
    parser.add_argument(
        "--diff-head-ref",
        "--head",
        dest="diff_head_ref",
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
    parser.add_argument(
        "--diff-range-mode",
        choices=["triple", "double"],
        default="",
        help="Diff range mode for --diff-base-ref/--diff-head-ref: triple=base...head, double=base..head",
    )
    parser.add_argument(
        "--diff-findings-filter",
        choices=["only", "mark"],
        default="",
        help="Diff finding policy: only=keep findings on changed lines only; mark=keep all and tag in_diff",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable LLM triage and always use local triage",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Write JSON report to this file",
    )
    parser.add_argument(
        "--fail-on",
        choices=_FAIL_ON_LEVELS,
        default=None,
        help="Exit with code 2 if findings at or above this severity exist",
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
        print("Invalid arguments: --diff-commit cannot be used with --diff-base-ref/--base or --diff-head-ref/--head")
        return 1

    try:
        request = _build_request_from_target(
            target=raw_target,
            mode=args.mode,
            diff_base_ref=diff_base_ref,
            diff_head_ref=diff_head_ref,
            diff_commit=diff_commit,
            diff_staged=args.diff_staged,
            diff_range_mode=args.diff_range_mode.strip().lower(),
            diff_findings_filter=args.diff_findings_filter.strip().lower(),
            enable_llm_triage=False if args.no_llm else None,
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
    report = result.get("report", {})
    report_text = json.dumps(report, ensure_ascii=False, indent=2)

    print(report_text)

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        try:
            _write_report(out_path, report_text)
        except OSError as e:
            print(f"\nFailed to write report: {out_path}: {e}")
            return 1

    if result.get("errors"):
        print("\nErrors:")
        for e in result["errors"]:
            print(f"- {e}")

    print("\nLogs:")
    for line in result.get("logs", []):
        print(f"- {line}")

    if args.out:
        print(f"\nReport written to: {Path(args.out).expanduser().resolve()}")

    if args.fail_on:
        summary = report.get("summary", {})
        if isinstance(summary, dict):
            matched = _count_failures_at_or_above(summary, args.fail_on)
            if matched > 0:
                print(f"\nFail-on threshold hit: severity>={args.fail_on}, matched_findings={matched}")
                return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
