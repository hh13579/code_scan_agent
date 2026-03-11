from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from code_scan_agent.graph.builder import build_graph
from code_scan_agent.graph.state import GraphState
from code_scan_agent.tools.local_env import load_local_env

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


def _resolve_scan_mode(
    *,
    target: Path,
    requested_mode: str,
    diff_base_ref: str,
    diff_head_ref: str,
    diff_commit: str,
    diff_staged: bool,
) -> str:
    if requested_mode != "auto":
        return requested_mode
    if target.is_dir() and (diff_base_ref or diff_head_ref or diff_commit or diff_staged):
        return "diff"
    return requested_mode


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


def _render_run_output(
    *,
    report_text: str,
    errors: list[str],
    logs: list[str],
    report_out_path: Path | None,
) -> str:
    sections = [report_text]
    if errors:
        sections.append("Errors:\n" + "\n".join(f"- {item}" for item in errors))
    sections.append("Logs:\n" + "\n".join(f"- {item}" for item in logs))
    if report_out_path is not None:
        sections.append(f"Report written to: {report_out_path}")
    return "\n\n".join(sections) + "\n"


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
    load_local_env()

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
        "--branch1",
        dest="diff_base_ref",
        default="",
        help="Git base ref / branch1 for diff mode (optional)",
    )
    parser.add_argument(
        "--diff-head-ref",
        "--head",
        "--branch2",
        dest="diff_head_ref",
        default="",
        help="Git head ref / branch2 for diff mode (optional)",
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
        "--log-out",
        default="",
        help="Write full scan console output to this file",
    )
    parser.add_argument(
        "--cn-report-out",
        default="",
        help="Write second-stage Chinese Markdown report to this file",
    )
    parser.add_argument(
        "--cn-report-json-out",
        default="",
        help="Write structured Chinese report JSON to this file",
    )
    parser.add_argument(
        "--cn-report-local-fallback",
        action="store_true",
        help="Allow local heuristic Chinese report when DeepSeek is unavailable",
    )
    parser.add_argument(
        "--cn-report-context-lines",
        type=int,
        default=20,
        help="Code context lines per finding for Chinese report generation",
    )
    parser.add_argument(
        "--cn-report-diff-context",
        type=int,
        default=20,
        help="Diff context lines per finding for Chinese report generation",
    )
    parser.add_argument(
        "--cn-report-max-findings",
        type=int,
        default=20,
        help="Maximum findings included in the Chinese report prompt",
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
        print(
            "Invalid arguments: --diff-commit cannot be used with "
            "--diff-base-ref/--base/--branch1 or --diff-head-ref/--head/--branch2"
        )
        return 1

    resolved_mode = _resolve_scan_mode(
        target=raw_target,
        requested_mode=args.mode,
        diff_base_ref=diff_base_ref,
        diff_head_ref=diff_head_ref,
        diff_commit=diff_commit,
        diff_staged=args.diff_staged,
    )

    try:
        request = _build_request_from_target(
            target=raw_target,
            mode=resolved_mode,
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
    errors = list(result.get("errors", []))
    logs = list(result.get("logs", []))

    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        try:
            _write_report(out_path, report_text)
        except OSError as e:
            print(f"\nFailed to write report: {out_path}: {e}")
            return 1

    else:
        out_path = None

    run_output_text = _render_run_output(
        report_text=report_text,
        errors=errors,
        logs=logs,
        report_out_path=out_path,
    )
    print(run_output_text, end="")

    if args.log_out:
        log_out_path = Path(args.log_out).expanduser().resolve()
        try:
            _write_report(log_out_path, run_output_text.rstrip("\n"))
        except OSError as e:
            print(f"\nFailed to write log output: {log_out_path}: {e}")
            return 1
    else:
        log_out_path = None

    if args.cn_report_out:
        from code_scan_agent.tools.deepseek_cn_report import generate_cn_report_from_content

        repo_path = Path(str(request.get("repo_path", raw_target))).expanduser().resolve()
        base_ref = str(request.get("diff_base_ref") or request.get("base_ref") or "").strip()
        head_ref = str(request.get("diff_head_ref") or request.get("head_ref") or "").strip()
        cn_report_out = Path(args.cn_report_out).expanduser().resolve()
        cn_report_json_out = (
            Path(args.cn_report_json_out).expanduser().resolve()
            if args.cn_report_json_out
            else None
        )
        try:
            cn_result = generate_cn_report_from_content(
                report=report if isinstance(report, dict) else {},
                log_text=run_output_text,
                repo_path=repo_path,
                base_ref=base_ref,
                head_ref=head_ref,
                out_path=cn_report_out,
                raw_out_path=cn_report_json_out,
                context_lines=args.cn_report_context_lines,
                diff_context=args.cn_report_diff_context,
                max_findings=args.cn_report_max_findings,
                allow_local_fallback=args.cn_report_local_fallback,
            )
        except Exception as e:  # noqa: BLE001
            print(f"\nFailed to generate Chinese report: {e}")
            return 1

        print(f"\nChinese report written to: {cn_result['markdown_path']}")
        print(f"Chinese report JSON written to: {cn_result['json_path']}")
        print(f"Chinese report generated by: {cn_result['generated_by']}")

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
