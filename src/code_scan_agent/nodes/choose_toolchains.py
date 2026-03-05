from __future__ import annotations

from code_scan_agent.graph.state import GraphState


def choose_toolchains(state: GraphState) -> GraphState:
    repo = state.get("repo_profile")
    if not repo:
        state.setdefault("errors", []).append("choose_toolchains: missing repo_profile")
        return state

    request = state.get("request", {})
    mode = request.get("mode", "full")
    repo_languages = set(repo.get("languages", []))
    target_languages = {
        str(t.get("language"))
        for t in state.get("targets", [])
        if t.get("language")
    }

    # selected 模式下只按选中文件的语言选工具链，避免跨语言节点空转
    if mode == "selected":
        languages = target_languages
    else:
        # full/diff 模式优先按 targets（兼容 include/exclude 后语言子集），兜底 repo 语言
        languages = target_languages or repo_languages

    toolchains: dict[str, list[str]] = {}

    if "cpp" in languages:
        toolchains["cpp"] = ["clang-tidy", "cppcheck"]

    if "java" in languages:
        toolchains["java"] = ["spotbugs", "checkstyle"]

    if "ts" in languages:
        toolchains["ts"] = ["tsc", "eslint"]

    if request.get("enable_security_scan", True):
        toolchains["security"] = ["semgrep"]

    state["selected_toolchains"] = toolchains
    state.setdefault("logs", []).append(
        f"choose_toolchains: mode={mode}, languages={sorted(languages)}, toolchains={toolchains}"
    )
    return state
