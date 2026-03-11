#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def _bootstrap() -> None:
    root = Path(__file__).resolve().parents[1]
    src_dir = root / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))


_bootstrap()

from code_scan_agent.tools.deepseek_cn_report import _call_deepseek_with_retry  # noqa: E402
from code_scan_agent.tools.local_env import load_local_env  # noqa: E402


_CODE_EXTS = {
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".java",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".py",
    ".go",
    ".rs",
    ".kt",
    ".swift",
}
_SKIP_PREFIXES = (
    ".git/",
    "build/",
    "build_scan/",
    "dist/",
    "out/",
    "node_modules/",
    "vendor/",
    "third_party/",
    "3rdparty/",
)
_SKIP_SEGMENTS = {
    "3rdparty",
    "deps",
    "external",
    "externals",
    "node_modules",
    "pods",
    "rn_dependencies",
    "submodules",
    "third_party",
    "vendor",
}
_SKIP_SUFFIXES = (
    ".pb.cc",
    ".pb.h",
    ".pb.hpp",
    ".pb.cxx",
)


def _run_git(repo_path: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git exited with {proc.returncode}")
    return proc.stdout


def _normalize_path(path_text: str) -> str:
    return path_text.strip().replace("\\", "/").lstrip("./")


def _is_code_path(rel_path: str) -> bool:
    if not rel_path:
        return False
    normalized = rel_path.replace("\\", "/").lstrip("./")
    if any(normalized.startswith(prefix) for prefix in _SKIP_PREFIXES):
        return False
    path_parts = {part.lower() for part in Path(normalized).parts}
    if path_parts & _SKIP_SEGMENTS:
        return False
    if normalized.lower().endswith(_SKIP_SUFFIXES):
        return False
    return Path(normalized).suffix.lower() in _CODE_EXTS


def _build_range_expr(branch1: str, branch2: str, range_mode: str) -> str:
    return f"{branch1}...{branch2}" if range_mode == "triple" else f"{branch1}..{branch2}"


def _parse_name_status(name_status_text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in name_status_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        status_field = parts[0]
        if not status_field:
            continue
        status = status_field[0]
        old_path = ""
        new_path = ""
        if status in {"R", "C"} and len(parts) >= 3:
            old_path = _normalize_path(parts[1])
            new_path = _normalize_path(parts[2])
        elif len(parts) >= 2:
            new_path = _normalize_path(parts[1])
        path_for_filter = new_path or old_path
        if not _is_code_path(path_for_filter):
            continue
        items.append(
            {
                "status": status,
                "old_path": old_path,
                "new_path": new_path,
                "path": path_for_filter,
            }
        )
    return items


def _parse_hunk_header(header_line: str) -> tuple[int, int, int, int]:
    # @@ -a,b +c,d @@
    before, _, after = header_line.partition("+")
    old_part = before.split("-")[-1].strip()
    new_part = after.split("@@")[0].strip()
    old_start_s, _, old_count_s = old_part.partition(",")
    new_start_s, _, new_count_s = new_part.partition(",")
    old_start = int(old_start_s or "0")
    old_count = int(old_count_s or "1")
    new_start = int(new_start_s or "0")
    new_count = int(new_count_s or "1")
    return old_start, old_count, new_start, new_count


def _truncate_lines(lines: list[str], max_lines: int) -> list[str]:
    if len(lines) <= max_lines:
        return lines
    keep_head = max_lines // 2
    keep_tail = max_lines - keep_head - 1
    return lines[:keep_head] + [f"... truncated {len(lines) - max_lines} lines ..."] + lines[-keep_tail:]


def _parse_file_diff(diff_text: str, max_hunk_lines: int) -> list[dict[str, Any]]:
    lines = diff_text.splitlines()
    if not lines:
        return []
    header: list[str] = []
    hunks: list[dict[str, Any]] = []
    current_lines: list[str] = []
    current_meta: tuple[int, int, int, int] | None = None

    def flush_current() -> None:
        if current_meta is None or not current_lines:
            return
        old_start, old_count, new_start, new_count = current_meta
        added = sum(1 for line in current_lines if line.startswith("+") and not line.startswith("+++"))
        deleted = sum(1 for line in current_lines if line.startswith("-") and not line.startswith("---"))
        body = _truncate_lines(current_lines, max_hunk_lines)
        hunks.append(
            {
                "old_start": old_start,
                "old_count": old_count,
                "new_start": new_start,
                "new_count": new_count,
                "added_lines": added,
                "deleted_lines": deleted,
                "changed_lines": added + deleted,
                "diff_text": "\n".join(header + body),
            }
        )

    for line in lines:
        if line.startswith("@@"):
            flush_current()
            current_meta = _parse_hunk_header(line)
            current_lines = [line]
        elif current_meta is None:
            header.append(line)
        else:
            current_lines.append(line)
    flush_current()
    return hunks


def _read_file_at_ref(repo_path: Path, git_ref: str, rel_path: str) -> str | None:
    if not rel_path or not git_ref:
        return None
    proc = subprocess.run(
        ["git", "-C", str(repo_path), "show", f"{git_ref}:{rel_path}"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def _build_code_context(file_text: str | None, line_number: int, context_lines: int) -> str:
    if not file_text:
        return "(code context unavailable)"
    lines = file_text.splitlines()
    if not lines:
        return "(code context unavailable)"
    start = max(1, line_number - context_lines)
    end = min(len(lines), line_number + context_lines)
    rendered = []
    for idx in range(start, end + 1):
        marker = ">" if idx == line_number else " "
        rendered.append(f"{marker}{idx:5d} | {lines[idx - 1]}")
    return "\n".join(rendered)


def _collect_diff_chunks(
    *,
    repo_path: Path,
    branch1: str,
    branch2: str,
    range_mode: str,
    diff_context: int,
    context_lines: int,
    max_files: int,
    max_hunks: int,
    max_hunk_lines: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    range_expr = _build_range_expr(branch1, branch2, range_mode)
    name_status_text = _run_git(repo_path, ["diff", "--name-status", "--find-renames", range_expr, "--"])
    files = _parse_name_status(name_status_text)

    file_entries: list[dict[str, Any]] = []
    hunks_total = 0
    for item in files:
        rel_path = item["path"]
        diff_text = _run_git(
            repo_path,
            ["diff", "--no-color", f"--unified={diff_context}", range_expr, "--", rel_path],
        )
        hunks = _parse_file_diff(diff_text, max_hunk_lines=max_hunk_lines)
        if not hunks:
            continue
        changed_lines_total = sum(hunk["changed_lines"] for hunk in hunks)
        item = dict(item)
        item["hunks"] = hunks
        item["changed_lines_total"] = changed_lines_total
        hunks_total += len(hunks)
        file_entries.append(item)

    file_entries.sort(key=lambda item: (-int(item["changed_lines_total"]), item["path"]))
    selected_files = file_entries[:max_files]

    chunks: list[dict[str, Any]] = []
    for file_index, item in enumerate(selected_files, 1):
        status = str(item["status"])
        rel_path = str(item["path"])
        source_ref = branch1 if status == "D" else branch2
        source_text = _read_file_at_ref(repo_path, source_ref, rel_path)
        for hunk_index, hunk in enumerate(item["hunks"], 1):
            if len(chunks) >= max_hunks:
                break
            line_number = int(hunk["old_start"] if status == "D" else hunk["new_start"] or 1)
            chunks.append(
                {
                    "file": rel_path,
                    "status": status,
                    "source_ref": source_ref,
                    "line": line_number,
                    "hunk_id": f"{file_index}.{hunk_index}",
                    "changed_lines": int(hunk["changed_lines"]),
                    "added_lines": int(hunk["added_lines"]),
                    "deleted_lines": int(hunk["deleted_lines"]),
                    "diff_text": hunk["diff_text"],
                    "code_context": _build_code_context(source_text, max(line_number, 1), context_lines),
                }
            )
        if len(chunks) >= max_hunks:
            break

    meta = {
        "range_expr": range_expr,
        "files_total": len(file_entries),
        "files_reviewed": len(selected_files),
        "hunks_total": hunks_total,
        "hunks_reviewed": len(chunks),
        "truncated": len(selected_files) < len(file_entries) or len(chunks) < hunks_total,
    }
    return chunks, meta


def _build_chunk_messages(scan_meta: dict[str, Any], chunk: dict[str, Any]) -> list[dict[str, str]]:
    system_prompt = (
        "你是资深代码审查工程师。"
        "你只根据提供的 diff 和代码上下文识别真实的 bug、行为回归、空指针/越界、并发、资源管理、API 误用、明显性能退化。"
        "除非影响正确性或维护风险明显，否则不要把纯样式问题当成主要问题。"
        "输出必须是严格 JSON。"
    )
    user_prompt = (
        "请审查下面这个 diff chunk，输出严格 JSON。\n"
        "JSON 顶层字段只能包含：chunk_summary(string), issues(array)。\n"
        "issues 每项字段必须且只能包含：severity, confidence, category, title, why, evidence, suggestion, line, is_likely_false_positive。\n"
        "约束：\n"
        "1. severity 只能是 critical/high/medium/low/info。\n"
        "2. confidence 只能是 high/medium/low。\n"
        "3. 最多返回 3 条问题。\n"
        "4. 如果没有值得报告的问题，返回 issues=[]。\n"
        "5. 不要复述无关上下文。\n\n"
        f"scan_meta={json.dumps(scan_meta, ensure_ascii=False)}\n"
        f"chunk={json.dumps(chunk, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _review_chunk(scan_meta: dict[str, Any], chunk: dict[str, Any]) -> dict[str, Any]:
    raw = _call_deepseek_with_retry(_build_chunk_messages(scan_meta, chunk))
    issues = raw.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    cleaned_issues: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        cleaned = {
            "severity": str(issue.get("severity", "info")).lower(),
            "confidence": str(issue.get("confidence", "low")).lower(),
            "category": str(issue.get("category", "")).strip(),
            "title": str(issue.get("title", "")).strip(),
            "why": str(issue.get("why", "")).strip(),
            "evidence": str(issue.get("evidence", "")).strip(),
            "suggestion": str(issue.get("suggestion", "")).strip(),
            "line": issue.get("line") if isinstance(issue.get("line"), int) else chunk["line"],
            "is_likely_false_positive": bool(issue.get("is_likely_false_positive", False)),
        }
        cleaned_issues.append(cleaned)
    return {
        "chunk_summary": str(raw.get("chunk_summary", "")).strip(),
        "issues": cleaned_issues,
    }


def _build_summary_messages(scan_meta: dict[str, Any], review_meta: dict[str, Any], issues: list[dict[str, Any]], chunk_notes: list[dict[str, Any]]) -> list[dict[str, str]]:
    system_prompt = (
        "你是资深代码审查工程师。"
        "请基于汇总后的 chunk 审查结果输出一份中文总结。"
        "输出必须是严格 JSON。"
    )
    payload = {
        "scan_meta": scan_meta,
        "review_meta": review_meta,
        "issues": issues,
        "chunk_notes": chunk_notes,
    }
    user_prompt = (
        "请输出严格 JSON，顶层字段只能包含："
        "title, overall_risk, conclusion, review_observations, coverage_limits, next_actions。\n"
        "约束：\n"
        "1. overall_risk 只能是 低/中/高。\n"
        "2. review_observations, coverage_limits, next_actions 都是 string 数组。\n"
        "3. 结论要聚焦增量代码审查。\n"
        "4. 如果问题很轻微，要明确说明。\n\n"
        f"input={json.dumps(payload, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _local_summary(scan_meta: dict[str, Any], review_meta: dict[str, Any], issues: list[dict[str, Any]]) -> dict[str, Any]:
    severities = [str(item.get("severity", "info")).lower() for item in issues]
    if any(sev in {"critical", "high"} for sev in severities):
        overall_risk = "高"
    elif any(sev == "medium" for sev in severities):
        overall_risk = "中"
    else:
        overall_risk = "低"

    if not issues:
        conclusion = "本次基于 diff 的 DeepSeek 审查未识别出值得报告的增量问题。"
    else:
        conclusion = f"本次基于 diff 的 DeepSeek 审查共识别出 {len(issues)} 个候选问题，需优先关注行为回归和真实缺陷信号。"

    coverage_limits = []
    if review_meta.get("truncated"):
        coverage_limits.append("本次审查因 max-files/max-hunks 限制只覆盖了部分 diff chunk。")
    coverage_limits.append("该模式不依赖静态分析工具，结论完全基于 diff 与代码上下文。")

    return {
        "title": "DeepSeek Diff 代码审查报告",
        "overall_risk": overall_risk,
        "conclusion": conclusion,
        "review_observations": [
            f"范围：{scan_meta['range_expr']}",
            f"已审查 {review_meta['hunks_reviewed']} / {review_meta['hunks_total']} 个 hunk。",
        ],
        "coverage_limits": coverage_limits,
        "next_actions": [
            "优先人工确认 high/medium 问题是否真实成立。",
            "如需更高覆盖度，可提高 max-files/max-hunks 后重跑。",
            "如需工具级补充，可再叠加静态分析模式。",
        ],
    }


def _summarize_review(scan_meta: dict[str, Any], review_meta: dict[str, Any], issues: list[dict[str, Any]], chunk_notes: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        raw = _call_deepseek_with_retry(_build_summary_messages(scan_meta, review_meta, issues, chunk_notes))
    except Exception:  # noqa: BLE001
        return _local_summary(scan_meta, review_meta, issues)
    if not isinstance(raw, dict):
        return _local_summary(scan_meta, review_meta, issues)
    summary = {
        "title": str(raw.get("title", "DeepSeek Diff 代码审查报告")).strip() or "DeepSeek Diff 代码审查报告",
        "overall_risk": str(raw.get("overall_risk", "低")).strip() or "低",
        "conclusion": str(raw.get("conclusion", "")).strip(),
        "review_observations": raw.get("review_observations", []),
        "coverage_limits": raw.get("coverage_limits", []),
        "next_actions": raw.get("next_actions", []),
    }
    for key in ("review_observations", "coverage_limits", "next_actions"):
        if not isinstance(summary[key], list):
            summary[key] = []
    return summary


def _render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# {summary.get('title', 'DeepSeek Diff 代码审查报告')}",
        "",
        "> 生成方式：DeepSeek Diff Review",
        "",
        "## 范围",
        f"- 仓库：{report['scan_meta']['repo_path']}",
        f"- 分支：{report['scan_meta']['branch1']} -> {report['scan_meta']['branch2']}",
        f"- diff 范围：`{report['scan_meta']['range_expr']}`",
        f"- 审查文件：{report['review_meta']['files_reviewed']} / {report['review_meta']['files_total']}",
        f"- 审查 hunk：{report['review_meta']['hunks_reviewed']} / {report['review_meta']['hunks_total']}",
        f"- 总体风险：{summary.get('overall_risk', '')}",
        f"- 结论：{summary.get('conclusion', '')}",
        "",
        "## 审查观察",
    ]

    observations = summary.get("review_observations", [])
    if observations:
        for item in observations:
            lines.append(f"- {item}")
    else:
        lines.append("- 无")

    lines.extend(["", "## 覆盖限制"])
    limits = summary.get("coverage_limits", [])
    if limits:
        for item in limits:
            lines.append(f"- {item}")
    else:
        lines.append("- 无")

    lines.extend(["", "## 发现的问题"])
    issues = report.get("issues", [])
    if not issues:
        lines.append("- 本次未发现值得报告的问题。")
    else:
        for idx, issue in enumerate(issues, 1):
            lines.extend(
                [
                    f"### {idx}. {issue.get('severity', '')} | {issue.get('file', '')}:{issue.get('line', '')}",
                    f"- 分类：`{issue.get('category', '')}`",
                    f"- 标题：{issue.get('title', '')}",
                    f"- 置信度：{issue.get('confidence', '')}",
                    f"- 原因：{issue.get('why', '')}",
                    f"- 证据：{issue.get('evidence', '')}",
                    f"- 建议：{issue.get('suggestion', '')}",
                    f"- 疑似误报：{'是' if issue.get('is_likely_false_positive') else '否'}",
                    "",
                ]
            )

    lines.append("## 建议动作")
    for item in summary.get("next_actions", []):
        lines.append(f"- {item}")

    lines.extend(["", "## 附录：审查块摘要"])
    for chunk in report.get("chunks", []):
        lines.extend(
            [
                f"### {chunk['hunk_id']} | {chunk['file']}",
                f"- 状态：`{chunk['status']}`",
                f"- 变更行数：{chunk['changed_lines']}",
                f"- 摘要：{chunk.get('chunk_summary', '') or '无'}",
                "",
                "```diff",
                chunk["diff_text"],
                "```",
                "",
                "```text",
                chunk["code_context"],
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_issue_records(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for chunk in chunks:
        for issue in chunk.get("issues", []):
            merged = dict(issue)
            merged["file"] = chunk["file"]
            merged["hunk_id"] = chunk["hunk_id"]
            issues.append(merged)
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    issues.sort(
        key=lambda item: (
            severity_rank.get(str(item.get("severity", "info")).lower(), 99),
            str(item.get("file", "")),
            item.get("line") if isinstance(item.get("line"), int) else 10**9,
        )
    )
    return issues


def main(argv: list[str] | None = None) -> int:
    load_local_env()

    parser = argparse.ArgumentParser(description="Review git diff directly with DeepSeek")
    parser.add_argument("--repo", required=True, help="Absolute path to git repository")
    parser.add_argument("--branch1", required=True, help="Base branch/ref")
    parser.add_argument("--branch2", required=True, help="Head branch/ref")
    parser.add_argument("--out", required=True, help="Output Markdown path")
    parser.add_argument("--json-out", required=True, help="Output JSON path")
    parser.add_argument("--range-mode", choices=["triple", "double"], default="triple", help="Use branch1...branch2 or branch1..branch2")
    parser.add_argument("--diff-context", type=int, default=5, help="Unified diff context lines")
    parser.add_argument("--context-lines", type=int, default=20, help="Code context lines around each hunk")
    parser.add_argument("--max-files", type=int, default=20, help="Maximum changed files to review")
    parser.add_argument("--max-hunks", type=int, default=40, help="Maximum hunks to review")
    parser.add_argument("--max-hunk-lines", type=int, default=120, help="Maximum lines kept per hunk diff")
    parser.add_argument("--continue-on-error", action="store_true", help="Skip chunk review failures and continue")
    args = parser.parse_args(argv)

    repo_path = Path(args.repo).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()
    json_out_path = Path(args.json_out).expanduser().resolve()

    chunks, review_meta = _collect_diff_chunks(
        repo_path=repo_path,
        branch1=args.branch1,
        branch2=args.branch2,
        range_mode=args.range_mode,
        diff_context=max(args.diff_context, 0),
        context_lines=max(args.context_lines, 1),
        max_files=max(args.max_files, 1),
        max_hunks=max(args.max_hunks, 1),
        max_hunk_lines=max(args.max_hunk_lines, 20),
    )

    scan_meta = {
        "repo_path": str(repo_path),
        "branch1": args.branch1,
        "branch2": args.branch2,
        "range_expr": review_meta["range_expr"],
        "range_mode": args.range_mode,
    }

    reviewed_chunks: list[dict[str, Any]] = []
    chunk_notes: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks, 1):
        print(
            f"[{index}/{len(chunks)}] reviewing {chunk['file']} hunk={chunk['hunk_id']} changed={chunk['changed_lines']}",
            file=sys.stderr,
        )
        try:
            chunk_review = _review_chunk(scan_meta, chunk)
        except Exception as exc:  # noqa: BLE001
            if not args.continue_on_error:
                raise
            chunk_review = {
                "chunk_summary": f"review failed: {type(exc).__name__}: {exc}",
                "issues": [],
            }
        merged_chunk = dict(chunk)
        merged_chunk.update(chunk_review)
        reviewed_chunks.append(merged_chunk)
        chunk_notes.append(
            {
                "file": chunk["file"],
                "hunk_id": chunk["hunk_id"],
                "chunk_summary": chunk_review.get("chunk_summary", ""),
                "issue_count": len(chunk_review.get("issues", [])),
            }
        )

    issues = _build_issue_records(reviewed_chunks)
    summary = _summarize_review(scan_meta, review_meta, issues, chunk_notes)

    report = {
        "scan_meta": scan_meta,
        "review_meta": review_meta,
        "summary": summary,
        "issues": issues,
        "chunks": reviewed_chunks,
    }

    _write_text(json_out_path, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    _write_text(out_path, _render_markdown(report))

    print(f"Markdown report written to: {out_path}")
    print(f"JSON report written to: {json_out_path}")
    print(f"Reviewed chunks: {review_meta['hunks_reviewed']} / {review_meta['hunks_total']}")
    print(f"Reported issues: {len(issues)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
