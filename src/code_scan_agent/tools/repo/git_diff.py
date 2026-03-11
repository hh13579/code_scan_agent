from __future__ import annotations

import re
from pathlib import Path
from typing import Literal, TypedDict

from code_scan_agent.tools.shell_runner import run_command


DiffMode = Literal["triple", "double"]  # triple=base...head, double=base..head


class DiffFile(TypedDict, total=False):
    path: str
    old_path: str
    status: str
    changed_lines: list[int]
    patch: str
    hunks: list[str]


_DIFF_HEADER_RE = re.compile(r"^diff --git a/(?P<old>.+) b/(?P<new>.+)$")
_HUNK_RE = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@"
)


def _normalize_git_path(path_text: str) -> str:
    path = path_text.strip()
    if path == "/dev/null":
        return ""
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path.replace("\\", "/").lstrip("./")


def _build_range_expr(base_ref: str, head_ref: str, mode: DiffMode) -> str:
    return f"{base_ref}...{head_ref}" if mode == "triple" else f"{base_ref}..{head_ref}"


def _run_diff(repo_path: Path, cmd: list[str], timeout_sec: int) -> tuple[str, str | None]:
    result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_sec, check=False)
    if result.get("error"):
        return "", str(result["error"])
    if int(result.get("exit_code", 0)) != 0:
        stderr = str(result.get("stderr", "")).strip()
        return "", f"exit={result.get('exit_code')}, stderr={stderr[:300]}"
    return str(result.get("stdout", "")), None


def _parse_name_status(name_status_text: str) -> dict[str, dict[str, str]]:
    """
    Parse `git diff --name-status` / `git show --name-status` output.
    Return {path: {"status": status_letter, "old_path": old_path}}.
    """
    out: dict[str, dict[str, str]] = {}
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

        if status in {"R", "C"} and len(parts) >= 3:
            old_path = _normalize_git_path(parts[1])
            new_path = _normalize_git_path(parts[2])
            if new_path:
                out[new_path] = {"status": status, "old_path": old_path}
            continue

        if len(parts) >= 2:
            path = _normalize_git_path(parts[1])
            if path:
                out[path] = {"status": status, "old_path": ""}

    return out


def _split_patch_sections(diff_text: str) -> dict[str, DiffFile]:
    sections: dict[str, DiffFile] = {}
    current_lines: list[str] = []
    current_old_path = ""
    current_new_path = ""
    current_hunk_lines: list[str] = []
    current_hunks: list[str] = []
    current_changed_lines: set[int] = set()

    def flush_current() -> None:
        nonlocal current_lines, current_old_path, current_new_path, current_hunk_lines, current_hunks, current_changed_lines
        if not current_lines:
            return

        if current_hunk_lines:
            current_hunks.append("\n".join(current_hunk_lines).rstrip("\n"))

        patch_path = current_new_path or current_old_path
        if patch_path:
            patch_text = "\n".join(current_lines).rstrip("\n")
            if patch_text:
                patch_text += "\n"
            sections[patch_path] = {
                "path": patch_path,
                "old_path": current_old_path,
                "patch": patch_text,
                "hunks": [item for item in current_hunks if item],
                "changed_lines": sorted(current_changed_lines),
            }

        current_lines = []
        current_old_path = ""
        current_new_path = ""
        current_hunk_lines = []
        current_hunks = []
        current_changed_lines = set()

    for raw in diff_text.splitlines():
        line = raw.rstrip("\n")
        diff_header = _DIFF_HEADER_RE.match(line)
        if diff_header:
            flush_current()
            current_old_path = _normalize_git_path(diff_header.group("old"))
            current_new_path = _normalize_git_path(diff_header.group("new"))
            current_lines = [line]
            continue

        if not current_lines:
            continue

        hunk_match = _HUNK_RE.match(line)
        if hunk_match:
            if current_hunk_lines:
                current_hunks.append("\n".join(current_hunk_lines).rstrip("\n"))
            current_hunk_lines = [line]
            new_start = int(hunk_match.group("new_start"))
            new_count = int(hunk_match.group("new_count") or "1")
            if new_count > 0:
                current_changed_lines.update(range(new_start, new_start + new_count))
            current_lines.append(line)
            continue

        current_lines.append(line)
        if current_hunk_lines:
            current_hunk_lines.append(line)

    flush_current()
    return sections


def _merge_diff_files(existing: DiffFile, incoming: DiffFile) -> DiffFile:
    merged_lines = set(existing.get("changed_lines", []))
    merged_lines.update(incoming.get("changed_lines", []))

    merged_hunks = list(existing.get("hunks", []))
    merged_hunks.extend(incoming.get("hunks", []))

    existing_patch = str(existing.get("patch", "")).strip("\n")
    incoming_patch = str(incoming.get("patch", "")).strip("\n")
    patch_parts = [part for part in (existing_patch, incoming_patch) if part]

    return {
        "path": str(existing.get("path") or incoming.get("path") or ""),
        "old_path": str(existing.get("old_path") or incoming.get("old_path") or ""),
        "status": str(incoming.get("status") or existing.get("status") or ""),
        "changed_lines": sorted(merged_lines),
        "patch": "\n\n".join(patch_parts) + ("\n" if patch_parts else ""),
        "hunks": merged_hunks,
    }


def _format_status_stats(name_status: dict[str, dict[str, str]]) -> str:
    if not name_status:
        return "status={}"
    counts: dict[str, int] = {}
    for item in name_status.values():
        status = item.get("status", "")
        if not status:
            continue
        counts[status] = counts.get(status, 0) + 1
    ordered = ", ".join(f"{key}:{counts[key]}" for key in sorted(counts))
    return f"status={{{ordered}}}"


def _collect_git_diff_files(
    *,
    repo_path: Path,
    base_ref: str | None = None,
    head_ref: str | None = None,
    commit: str | None = None,
    staged: bool = False,
    mode: DiffMode = "triple",
    exclude_deleted: bool = True,
    timeout_sec: int = 30,
) -> tuple[list[DiffFile], list[str], str | None]:
    repo_path = repo_path.resolve()
    logs: list[str] = []
    merged_by_path: dict[str, DiffFile] = {}

    diff_patch_common = ["git", "diff", "--no-color", "--unified=0"]
    diff_name_status_common = ["git", "diff", "--name-status"]
    show_patch_common = ["git", "show", "--no-color", "--unified=0", "--format="]
    show_name_status_common = ["git", "show", "--no-color", "--name-status", "--format="]

    commands: list[tuple[list[str], list[str], str]] = []
    if commit:
        commands.append(
            (
                [*show_patch_common, commit, "--"],
                [*show_name_status_common, commit, "--"],
                f"commit={commit}",
            )
        )
    elif base_ref:
        effective_head = head_ref or "HEAD"
        range_expr = _build_range_expr(base_ref, effective_head, mode)
        commands.append(
            (
                [*diff_patch_common, range_expr, "--"],
                [*diff_name_status_common, range_expr, "--"],
                f"range={range_expr}",
            )
        )
    elif staged:
        commands.append(
            (
                [*diff_patch_common, "--cached", "--"],
                [*diff_name_status_common, "--cached", "--"],
                "staged",
            )
        )
    else:
        commands.append(
            (
                [*diff_patch_common, "--"],
                [*diff_name_status_common, "--"],
                "unstaged",
            )
        )
        commands.append(
            (
                [*diff_patch_common, "--cached", "--"],
                [*diff_name_status_common, "--cached", "--"],
                "staged",
            )
        )

    for patch_cmd, name_status_cmd, label in commands:
        patch_stdout, patch_err = _run_diff(repo_path, patch_cmd, timeout_sec)
        if patch_err:
            return [], logs, f"git diff patch ({label}) failed: {patch_err}"
        name_status_stdout, name_status_err = _run_diff(repo_path, name_status_cmd, timeout_sec)
        if name_status_err:
            return [], logs, f"git diff name-status ({label}) failed: {name_status_err}"

        status_map = _parse_name_status(name_status_stdout)
        patch_sections = _split_patch_sections(patch_stdout)
        line_count = sum(len(item.get("changed_lines", [])) for item in patch_sections.values())

        for path, meta in status_map.items():
            status = str(meta.get("status", ""))
            if exclude_deleted and status == "D":
                continue
            patch_section = patch_sections.get(
                path,
                {
                    "path": path,
                    "old_path": str(meta.get("old_path", "")),
                    "patch": "",
                    "hunks": [],
                    "changed_lines": [],
                },
            )
            item: DiffFile = {
                "path": path,
                "old_path": str(meta.get("old_path", "") or patch_section.get("old_path", "")),
                "status": status,
                "changed_lines": list(patch_section.get("changed_lines", [])),
                "patch": str(patch_section.get("patch", "")),
                "hunks": list(patch_section.get("hunks", [])),
            }
            if path in merged_by_path:
                merged_by_path[path] = _merge_diff_files(merged_by_path[path], item)
            else:
                merged_by_path[path] = item

        logs.append(
            "git_diff: "
            f"{label}, files={len(status_map)}, changed_line_files={len(patch_sections)}, "
            f"changed_lines={line_count}, {_format_status_stats(status_map)}"
        )

    diff_files = [
        merged_by_path[path]
        for path in sorted(merged_by_path)
        if merged_by_path[path].get("path")
    ]
    if not diff_files:
        logs.append("git_diff: no changed files detected")
    return diff_files, logs, None


def get_git_diff_files(
    *,
    repo_path: Path,
    base_ref: str | None = None,
    head_ref: str | None = None,
    commit: str | None = None,
    staged: bool = False,
    mode: DiffMode = "triple",
    exclude_deleted: bool = True,
    timeout_sec: int = 30,
) -> list[DiffFile]:
    diff_files, _, error = _collect_git_diff_files(
        repo_path=repo_path,
        base_ref=base_ref,
        head_ref=head_ref,
        commit=commit,
        staged=staged,
        mode=mode,
        exclude_deleted=exclude_deleted,
        timeout_sec=timeout_sec,
    )
    if error:
        raise RuntimeError(error)
    return diff_files


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
    diff_files, logs, error = _collect_git_diff_files(
        repo_path=repo_path,
        base_ref=base_ref,
        head_ref=head_ref,
        commit=commit,
        staged=staged,
        mode=range_mode,
        exclude_deleted=True,
        timeout_sec=timeout_sec,
    )
    if error:
        return {}, logs, error

    normalized = {
        str(item.get("path", "")): list(item.get("changed_lines", []))
        for item in diff_files
        if item.get("path") and item.get("changed_lines")
    }
    return normalized, logs, None
