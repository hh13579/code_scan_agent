from __future__ import annotations

from pathlib import Path

from code_scan_agent.graph.state import GraphState


def _detect_languages(repo_path: Path) -> list[str]:
    exts = {
        ".cpp": "cpp",
        ".cc": "cpp",
        ".cxx": "cpp",
        ".hpp": "cpp",
        ".h": "cpp",
        ".java": "java",
        ".ts": "ts",
        ".tsx": "ts",
    }

    found: set[str] = set()
    for p in repo_path.rglob("*"):
        if not p.is_file():
            continue
        lang = exts.get(p.suffix.lower())
        if lang:
            found.add(lang)

    return sorted(found)


def _detect_build_systems(repo_path: Path) -> tuple[list[str], list[str], str | None]:
    build_systems: list[str] = []
    config_files: list[str] = []
    compile_db_path: str | None = None

    known = [
        "CMakeLists.txt",
        "compile_commands.json",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "package.json",
        "tsconfig.json",
        "eslint.config.js",
        ".eslintrc",
    ]

    for name in known:
        hits = list(repo_path.rglob(name))
        for hit in hits:
            rel = str(hit.relative_to(repo_path))
            config_files.append(rel)
            if name == "CMakeLists.txt":
                build_systems.append("cmake")
            elif name == "compile_commands.json":
                build_systems.append("clang_compile_db")
                compile_db_path = str(hit)
            elif name == "pom.xml":
                build_systems.append("maven")
            elif name in ("build.gradle", "build.gradle.kts"):
                build_systems.append("gradle")
            elif name == "package.json":
                build_systems.append("npm")
            elif name == "tsconfig.json":
                build_systems.append("typescript")

    # 去重保持顺序
    build_systems = list(dict.fromkeys(build_systems))
    config_files = list(dict.fromkeys(config_files))
    return build_systems, config_files, compile_db_path


def discover_repo(state: GraphState) -> GraphState:
    request = state["request"]
    repo_path = Path(request["repo_path"]).expanduser().resolve()

    if not repo_path.exists() or not repo_path.is_dir():
        state.setdefault("errors", []).append(f"Repo path not found: {repo_path}")
        return state

    languages = _detect_languages(repo_path)
    build_systems, config_files, compile_db_path = _detect_build_systems(repo_path)

    state["repo_profile"] = {
        "repo_path": str(repo_path),
        "languages": languages,  # type: ignore[assignment]
        "build_systems": build_systems,
        "config_files": config_files,
        "compile_db_path": compile_db_path,
    }

    state.setdefault("logs", []).append(
        f"discover_repo: languages={languages}, build_systems={build_systems}"
    )
    return state