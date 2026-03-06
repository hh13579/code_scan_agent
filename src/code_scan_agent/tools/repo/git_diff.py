from __future__ import annotations

import re
from pathlib import Path

from code_scan_agent.tools.shell_runner import run_command


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(?P<start>\d+)(?:,(?P<count>\d+))? @@")


def _normalize_git_path(path_text: str) -> str:
    path = path_text.strip()
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


def collect_git_diff_changed_lines(
    *,
    repo_path: Path,
    base_ref: str | None = None,
    head_ref: str | None = None,
    commit: str | None = None,
    staged: bool = False,
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

    diff_common = ["git", "diff", "--no-color", "--unified=0", "--diff-filter=ACMRTUXB"]
    show_common = ["git", "show", "--no-color", "--unified=0", "--diff-filter=ACMRTUXB", "--format="]

    commands: list[tuple[list[str], str]] = []
    if commit:
        commands.append(([*show_common, commit, "--"], f"commit={commit}"))
    elif base_ref:
        if head_ref:
            commands.append(([*diff_common, f"{base_ref}...{head_ref}", "--"], f"range={base_ref}...{head_ref}"))
        else:
            commands.append(([*diff_common, f"{base_ref}...HEAD", "--"], f"range={base_ref}...HEAD"))
    elif staged:
        commands.append(([*diff_common, "--cached", "--"], "staged"))
    else:
        commands.append(([*diff_common, "--"], "unstaged"))
        commands.append(([*diff_common, "--cached", "--"], "staged"))

    for cmd, label in commands:
        stdout, err = _run_diff(repo_path, cmd, timeout_sec)
        if err:
            return {}, logs, f"git diff ({label}) failed: {err}"

        parsed = _parse_unified_zero_diff(stdout)
        _merge_changed_lines(merged, parsed)
        line_count = sum(len(v) for v in parsed.values())
        logs.append(f"git_diff: {label}, files={len(parsed)}, changed_lines={line_count}")

    if not merged:
        logs.append("git_diff: no changed lines detected")

    normalized = {path: sorted(lines) for path, lines in merged.items() if lines}
    return normalized, logs, None
