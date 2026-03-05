from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path

from code_scan_agent.graph.state import GraphState


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

    targets = []
    languages = set(repo.get("languages", []))

    for file_path in repo_path.rglob("*"):
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

        lang = _EXT_TO_LANG.get(file_path.suffix.lower())
        if not lang or lang not in languages:
            continue

        targets.append(
            {
                "path": str(file_path.resolve()),
                "language": lang,
                "changed_lines": [],
            }
        )

    state["targets"] = targets
    state.setdefault("logs", []).append(
        f"collect_targets: mode={mode}, total_targets={len(targets)}"
    )
    return state
