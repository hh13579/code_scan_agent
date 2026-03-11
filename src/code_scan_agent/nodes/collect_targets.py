from __future__ import annotations

import os
from fnmatch import fnmatch
from pathlib import Path

from code_scan_agent.graph.state import GraphState
from code_scan_agent.tools.repo.git_diff import DiffMode, collect_git_diff_changed_lines


_EXT_TO_LANG = {
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".h": "cpp",
    ".java": "java",
    ".ts": "ts",
    ".tsx": "ts",
}

_DEFAULT_EXCLUDE_PREFIXES = {
    ".git/",
    "build/",
    "dist/",
    "node_modules/",
    "vendor/",
    "third_party/",
    "third-64/",
}


def _match_globs(rel_path: str, patterns: list[str]) -> bool:
    return any(fnmatch(rel_path, p) for p in patterns)


def _parse_bool(raw: object, default: bool = False) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return default


def collect_targets(state: GraphState) -> GraphState:
    repo = state.get("repo_profile")
    if not repo:
        state.setdefault("errors", []).append("collect_targets: missing repo_profile")
        return state

    repo_path = Path(repo.get("repo_path", "")).resolve()
    if not repo_path.is_dir():
        state.setdefault("errors", []).append(f"collect_targets: invalid repo path: {repo_path}")
        return state

    request = state.get("request", {})
    mode = request.get("mode", "full")
    include_globs = list(request.get("include_globs", []))
    exclude_globs = list(request.get("exclude_globs", []))
    selected_paths = list(request.get("selected_paths", []))
    diff_changed_lines: dict[str, list[int]] = {}

    selected_set: set[str] = set()
    for p in selected_paths:
        p_obj = Path(p).expanduser()
        if p_obj.is_absolute():
            try:
                rel = str(p_obj.resolve().relative_to(repo_path)).replace("\\", "/").lstrip("./")
                selected_set.add(rel)
            except ValueError:
                selected_set.add(str(p_obj.resolve()).replace("\\", "/"))
        else:
            selected_set.add(str(p_obj).replace("\\", "/").lstrip("./"))

    if mode == "diff":
        base_ref = str(request.get("diff_base_ref") or request.get("base_ref") or os.getenv("DIFF_BASE_REF", "")).strip() or None
        head_ref = str(request.get("diff_head_ref") or request.get("head_ref") or os.getenv("DIFF_HEAD_REF", "")).strip() or None
        commit = str(request.get("diff_commit") or os.getenv("DIFF_COMMIT", "")).strip() or None
        staged = _parse_bool(request.get("diff_staged"), default=_parse_bool(os.getenv("DIFF_STAGED", "0")))
        range_mode_raw = str(request.get("diff_range_mode") or os.getenv("DIFF_RANGE_MODE", "triple")).strip().lower()
        range_mode: DiffMode = "double" if range_mode_raw == "double" else "triple"
        timeout_sec = int(os.getenv("GIT_DIFF_TIMEOUT_SEC", "30"))
        diff_changed_lines, diff_logs, diff_error = collect_git_diff_changed_lines(
            repo_path=repo_path,
            base_ref=base_ref,
            head_ref=head_ref,
            commit=commit,
            staged=staged,
            range_mode=range_mode,
            timeout_sec=timeout_sec,
        )
        state.setdefault("logs", []).extend([f"collect_targets detail: {x}" for x in diff_logs])
        state.setdefault("logs", []).append(
            f"collect_targets detail: diff_candidates={len(diff_changed_lines)}"
        )
        if diff_error:
            state.setdefault("errors", []).append(f"collect_targets: {diff_error}")
            state["targets"] = []
            return state

    targets = []
    languages = set(repo.get("languages", []))
    if mode == "diff":
        candidate_paths = ((repo_path / rel).resolve() for rel in sorted(diff_changed_lines.keys()))
    else:
        candidate_paths = repo_path.rglob("*")

    for file_path in candidate_paths:
        if not file_path.is_file():
            continue

        rel_path = str(file_path.relative_to(repo_path)).replace("\\", "/")

        if any(rel_path.startswith(prefix) for prefix in _DEFAULT_EXCLUDE_PREFIXES):
            continue
        if exclude_globs and _match_globs(rel_path, exclude_globs):
            continue
        if include_globs and not _match_globs(rel_path, include_globs):
            continue
        abs_norm = str(file_path.resolve()).replace("\\", "/")
        if mode == "selected" and rel_path not in selected_set and abs_norm not in selected_set:
            continue
        changed_lines = diff_changed_lines.get(rel_path, [])
        if mode == "diff" and not changed_lines:
            continue

        lang = _EXT_TO_LANG.get(file_path.suffix.lower())
        if not lang or lang not in languages:
            continue

        targets.append(
            {
                "path": str(file_path.resolve()),
                "language": lang,
                "changed_lines": changed_lines,
            }
        )

    state["targets"] = targets
    state.setdefault("logs", []).append(
        f"collect_targets: mode={mode}, total_targets={len(targets)}"
    )
    return state
