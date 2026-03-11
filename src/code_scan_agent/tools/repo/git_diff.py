from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from code_scan_agent.tools.shell_runner import run_command


DiffMode = Literal["triple", "double"]  # triple=base...head, double=base..head

_HUNK_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(?P<start>\d+)(?:,(?P<count>\d+))?\s+@@")


def _normalize_git_path(path_text: str) -> str:
    path = path_text.strip()
    if path == "/dev/null":
        return ""
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path.replace("\\", "/").lstrip("./")


def _parse_unified_zero_diff(diff_text: str) -> dict[str, set[int]]:
    changed: dict[str, set[int]] = {}
    current_file: str | None = None

    for raw in diff_text.splitlines():
        line = raw.rstrip("\n")

        if line.startswith("+++ "):
            rhs = line[4:].strip()
            if rhs == "/dev/null":
                current_file = None
                continue
            current_file = _normalize_git_path(rhs)
            changed.setdefault(current_file, set())
            continue

        if not current_file:
            continue

        m = _HUNK_RE.match(line)
        if not m:
            continue

        start = int(m.group("start"))
        count = int(m.group("count") or "1")
        if count <= 0:
            continue
        changed[current_file].update(range(start, start + count))

    return changed


def _parse_name_status(name_status_text: str) -> dict[str, str]:
    """
    Parse `git diff --name-status` / `git show --name-status` output.
    Return {path: status_letter}.
    """
    out: dict[str, str] = {}
    for raw in name_status_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if not parts:
            continue

        status_field = parts[0]
        status = status_field[0] if status_field else ""
        if not status:
            continue

        if status in {"R", "C"}:
            # R100<TAB>old<TAB>new
            if len(parts) >= 3:
                new_path = _normalize_git_path(parts[2])
                if new_path:
                    out[new_path] = status
            continue

        # A/M/D/T/U/X/B<TAB>path
        if len(parts) >= 2:
            path = _normalize_git_path(parts[1])
            if path:
                out[path] = status
    return out


def _merge_changed_lines(dst: dict[str, set[int]], src: dict[str, set[int]]) -> None:
    for path, lines in src.items():
        dst.setdefault(path, set()).update(lines)


def _run_diff(repo_path: Path, cmd: list[str], timeout_sec: int) -> tuple[str, str | None]:
    result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_sec, check=False)
    if result.get("error"):
        return "", str(result["error"])
    if int(result.get("exit_code", 0)) != 0:
        stderr = str(result.get("stderr", "")).strip()
        return "", f"exit={result.get('exit_code')}, stderr={stderr[:300]}"
    return str(result.get("stdout", "")), None


def _build_range_expr(base_ref: str, head_ref: str, mode: DiffMode) -> str:
    return f"{base_ref}...{head_ref}" if mode == "triple" else f"{base_ref}..{head_ref}"


def _format_status_stats(name_status: dict[str, str]) -> str:
    if not name_status:
        return "status={}"
    counts: dict[str, int] = {}
    for st in name_status.values():
        counts[st] = counts.get(st, 0) + 1
    ordered = ", ".join(f"{k}:{counts[k]}" for k in sorted(counts))
    return f"status={{{ordered}}}"


def collect_git_diff_changed_lines(
    *,
    repo_path: Path,
    base_ref: str | None = None,
    head_ref: str | None = None,
    commit: str | None = None,
    staged: bool = False,
    range_mode: DiffMode = "triple",
    timeout_sec: int = 30,
) -> tuple[dict[str, list[int]], list[str], str | None]:
    """
    返回:
    - {rel_path: [changed_line_numbers]}
    - logs
    - error（失败时非空）
    """
    repo_path = repo_path.resolve()
    logs: list[str] = []
    merged: dict[str, set[int]] = {}

    # D 不在 unified line map 中体现；但 name-status 里保留 D 便于记录规模。
    diff_unified_common = ["git", "diff", "--no-color", "--unified=0", "--diff-filter=ACMRTUXB"]
    diff_name_status_common = ["git", "diff", "--name-status", "--diff-filter=ACDMRTUXB"]
    show_unified_common = ["git", "show", "--no-color", "--unified=0", "--diff-filter=ACMRTUXB", "--format="]
    show_name_status_common = ["git", "show", "--no-color", "--name-status", "--diff-filter=ACDMRTUXB", "--format="]

    commands: list[tuple[list[str], list[str], str]] = []
    if commit:
        commands.append(
            (
                [*show_unified_common, commit, "--"],
                [*show_name_status_common, commit, "--"],
                f"commit={commit}",
            )
        )
    elif base_ref:
        effective_head = head_ref or "HEAD"
        range_expr = _build_range_expr(base_ref, effective_head, range_mode)
        commands.append(
            (
                [*diff_unified_common, range_expr, "--"],
                [*diff_name_status_common, range_expr, "--"],
                f"range={range_expr}",
            )
        )
    elif staged:
        commands.append(
            (
                [*diff_unified_common, "--cached", "--"],
                [*diff_name_status_common, "--cached", "--"],
                "staged",
            )
        )
    else:
        commands.append(
            (
                [*diff_unified_common, "--"],
                [*diff_name_status_common, "--"],
                "unstaged",
            )
        )
        commands.append(
            (
                [*diff_unified_common, "--cached", "--"],
                [*diff_name_status_common, "--cached", "--"],
                "staged",
            )
        )

    for unified_cmd, name_status_cmd, label in commands:
        unified_stdout, unified_err = _run_diff(repo_path, unified_cmd, timeout_sec)
        if unified_err:
            return {}, logs, f"git diff unified ({label}) failed: {unified_err}"
        name_status_stdout, name_status_err = _run_diff(repo_path, name_status_cmd, timeout_sec)
        if name_status_err:
            return {}, logs, f"git diff name-status ({label}) failed: {name_status_err}"

        parsed = _parse_unified_zero_diff(unified_stdout)
        status_map = _parse_name_status(name_status_stdout)
        _merge_changed_lines(merged, parsed)
        line_count = sum(len(v) for v in parsed.values())
        logs.append(
            "git_diff: "
            f"{label}, files={len(status_map)}, changed_line_files={len(parsed)}, "
            f"changed_lines={line_count}, {_format_status_stats(status_map)}"
        )

    if not merged:
        logs.append("git_diff: no changed lines detected")

    normalized = {path: sorted(lines) for path, lines in merged.items() if lines}
    return normalized, logs, None
