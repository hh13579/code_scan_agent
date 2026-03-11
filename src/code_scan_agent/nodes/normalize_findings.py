from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Literal

from code_scan_agent.graph.state import Finding, GraphState

Severity = Literal["critical", "high", "medium", "low", "info"]


# ---------- Severity mapping (tool-specific -> unified) ----------

# clang-tidy 输出一般是 warning/error/note
_CLANG_TIDY_SEV_MAP: dict[str, Severity] = {
    "error": "high",
    "warning": "medium",
    "note": "info",
}

# cppcheck severity 常见：error, warning, style, performance, portability, information
_CPPCHECK_SEV_MAP: dict[str, Severity] = {
    "error": "high",
    "warning": "medium",
    "style": "low",
    "performance": "medium",
    "portability": "low",
    "information": "info",
    "debug": "info",
}

# 兜底 severity（其他工具/未知文本）
_GENERIC_SEV_MAP: dict[str, Severity] = {
    "critical": "critical",
    "blocker": "critical",
    "fatal": "critical",
    "error": "high",
    "err": "high",
    "high": "high",
    "warning": "medium",
    "warn": "medium",
    "medium": "medium",
    "low": "low",
    "info": "info",
    "note": "info",
    "hint": "info",
}


# ---------- Category mapping (rule_id/message -> category) ----------

# clang-tidy rule id 常见前缀：modernize-*, readability-*, performance-* ...
_CLANG_TIDY_RULE_PREFIX_CATEGORY: list[tuple[str, str]] = [
    ("clang-analyzer-", "memory"),
    ("bugprone-", "bugprone"),
    ("cert-", "security"),
    ("cppcoreguidelines-", "best_practice"),
    ("concurrency-", "concurrency"),
    ("google-", "style"),
    ("hicpp-", "best_practice"),
    ("llvm-", "style"),
    ("misc-", "bugprone"),
    ("modernize-", "modernize"),
    ("performance-", "performance"),
    ("portability-", "portability"),
    ("readability-", "style"),
]

# cppcheck rule id（id）有很多，这里按关键词/前缀做弱匹配
_CPPCHECK_RULE_CATEGORY_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"null", re.IGNORECASE), "nullability"),
    (re.compile(r"uninit|uninitialized", re.IGNORECASE), "memory"),
    (re.compile(r"mem|malloc|free|leak|doubleFree|useAfterFree", re.IGNORECASE), "memory"),
    (re.compile(r"bounds|outOfBounds|arrayIndex", re.IGNORECASE), "memory"),
    (re.compile(r"race|deadlock|mutex|lock", re.IGNORECASE), "concurrency"),
    (re.compile(r"perf|performance", re.IGNORECASE), "performance"),
    (re.compile(r"portability", re.IGNORECASE), "portability"),
    (re.compile(r"security|crypto|xss|injection", re.IGNORECASE), "security"),
    (re.compile(r"style|naming|indent", re.IGNORECASE), "style"),
]

# message 的关键词兜底（两工具都适用）
_MESSAGE_CATEGORY_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"null pointer|nullptr", re.IGNORECASE), "nullability"),
    (re.compile(r"use after free|double free|memory leak", re.IGNORECASE), "memory"),
    (re.compile(r"data race|deadlock|mutex|lock", re.IGNORECASE), "concurrency"),
    (re.compile(r"buffer overflow|out of bounds|heap overflow|stack overflow", re.IGNORECASE), "memory"),
    (re.compile(r"sql injection|command injection|xss|csrf|path traversal", re.IGNORECASE), "security"),
    (re.compile(r"performance|slow|inefficient", re.IGNORECASE), "performance"),
    (re.compile(r"deprecated|modernize|c\+\+11|c\+\+14|c\+\+17|c\+\+20", re.IGNORECASE), "modernize"),
    (re.compile(r"readability|style|naming|format", re.IGNORECASE), "style"),
]


def _normalize_path(repo_root: Path, file_path: str) -> str:
    """
    - 统一分隔符
    - 优先输出相对 repo 的路径（更稳定）
    """
    if not file_path:
        return ""

    # 把可能的 Windows 反斜杠归一
    file_path = file_path.replace("\\", "/")

    p = Path(file_path)

    # 如果是相对路径，直接 norm
    if not p.is_absolute():
        return os.path.normpath(file_path).replace("\\", "/")

    # 绝对路径：尽量转成相对 repo_root
    try:
        rel = p.resolve().relative_to(repo_root.resolve())
        return str(rel).replace("\\", "/")
    except Exception:
        return str(p).replace("\\", "/")


def _map_severity(tool: str, raw_sev: Any) -> Severity:
    sev = str(raw_sev or "info").strip().lower()

    if tool == "clang-tidy":
        return _CLANG_TIDY_SEV_MAP.get(sev, _GENERIC_SEV_MAP.get(sev, "info"))
    if tool == "cppcheck":
        return _CPPCHECK_SEV_MAP.get(sev, _GENERIC_SEV_MAP.get(sev, "info"))

    return _GENERIC_SEV_MAP.get(sev, "info")


def _infer_category(tool: str, rule_id: str, message: str) -> str:
    rule_id = (rule_id or "").strip()
    message = (message or "").strip()

    if tool == "clang-tidy":
        for prefix, cat in _CLANG_TIDY_RULE_PREFIX_CATEGORY:
            if rule_id.startswith(prefix):
                return cat

    if tool == "cppcheck":
        for pat, cat in _CPPCHECK_RULE_CATEGORY_HINTS:
            if pat.search(rule_id):
                return cat

    # message 兜底
    for pat, cat in _MESSAGE_CATEGORY_HINTS:
        if pat.search(message):
            return cat

    return "static_analysis"


def _infer_confidence(tool: str, severity: Severity, rule_id: str) -> str:
    """
    很粗但实用的置信度估计：
    - clang-tidy / cppcheck 都属于静态工具，整体置信度较高
    - 风格类、modernize 类可以稍低
    """
    rid = (rule_id or "").lower()

    if tool == "clang-tidy":
        if rid.startswith(("readability-", "google-", "llvm-", "modernize-")):
            return "medium"
        return "high"

    if tool == "cppcheck":
        if severity in ("high", "critical"):
            return "high"
        if rid.lower().find("style") >= 0:
            return "medium"
        return "high"

    return "medium" if severity in ("low", "info") else "high"


def _default_rule_id(tool: str) -> str:
    if tool == "clang-tidy":
        return "clang-tidy"
    if tool == "cppcheck":
        return "cppcheck"
    return "unknown"


def _normalize_one_raw(
    *,
    repo_root: Path,
    language: str,
    tool: str,
    raw: dict[str, Any],
) -> Finding:
    """
    统一输入：raw 至少包含 message/file/line/column/severity/rule_id 中的部分字段
    输出：Finding（内部统一 schema）
    """
    rule_id = str(raw.get("rule_id") or raw.get("id") or _default_rule_id(tool))
    message = str(raw.get("message") or raw.get("msg") or raw.get("text") or "")

    severity = _map_severity(tool, raw.get("severity"))
    category = _infer_category(tool, rule_id, message)

    file_path = _normalize_path(repo_root, str(raw.get("file") or ""))
    line = raw.get("line")
    col = raw.get("column")

    # 行列容错
    try:
        line = int(line) if line is not None else None
    except Exception:
        line = None
    try:
        col = int(col) if col is not None else None
    except Exception:
        col = None

    confidence = _infer_confidence(tool, severity, rule_id)

    # 未来你可以把 clang-tidy 的修复 hint / cppcheck 的 inconclusive 标记映射进来
    autofix_available = bool(raw.get("autofix_available", False))

    finding: Finding = {
        "language": language if language in {"cpp", "java", "ts"} else "cpp",  # 兜底
        "tool": tool,
        "source": tool,
        "rule_id": rule_id,
        "category": category,
        "severity": severity,
        "file": file_path,
        "line": line,
        "column": col,
        "message": message,
        "snippet": None,
        "confidence": confidence,
        "autofix_available": autofix_available,
    }
    return finding


def _extract_tool_name(tool_result_tool_field: str, raw: dict[str, Any]) -> str:
    """
    你的 tool_result["tool"] 在 C++ 节点里是 "cpp_scanners"（聚合节点），
    但 raw_findings 里会有真正工具名 tool="clang-tidy"/"cppcheck"。
    优先使用 raw["tool"]，否则退回 tool_result 的 tool 字段。
    """
    t = str(raw.get("tool") or "").strip()
    if t:
        return t
    # 这里保留聚合 tool 名也可以，但建议尽量映射成真实工具名
    return str(tool_result_tool_field or "unknown")


def _get_diff_filter_mode(state: GraphState) -> str:
    request = state.get("request", {})
    request_mode = str(request.get("mode", "full")).strip().lower()
    default_mode = "only" if request_mode == "diff" else "mark"

    raw = request.get("diff_findings_filter")
    if not raw:
        raw = os.getenv("DIFF_FINDINGS_FILTER", default_mode)

    mode = str(raw).strip().lower()
    return mode if mode in {"mark", "only"} else default_mode


def _build_diff_line_index(state: GraphState, repo_root: Path) -> dict[str, set[int]]:
    line_index: dict[str, set[int]] = {}
    for target in state.get("targets", []):
        file_path = _normalize_path(repo_root, str(target.get("path") or ""))
        if not file_path:
            continue

        raw_lines = target.get("changed_lines") or []
        if not isinstance(raw_lines, list):
            continue

        lines: set[int] = set()
        for raw in raw_lines:
            try:
                line = int(raw)
            except Exception:
                continue
            if line > 0:
                lines.add(line)

        if lines:
            line_index.setdefault(file_path, set()).update(lines)

    return line_index


def normalize_findings(state: GraphState) -> GraphState:
    repo = state.get("repo_profile")
    if not repo:
        state.setdefault("errors", []).append("normalize_findings: missing repo_profile")
        return state

    repo_root = Path(repo["repo_path"]).resolve()
    request = state.get("request", {})
    scan_mode = str(request.get("mode", "full"))
    diff_filter_mode = _get_diff_filter_mode(state)
    diff_line_index = _build_diff_line_index(state, repo_root) if scan_mode == "diff" else {}

    normalized: list[Finding] = []
    dropped = 0
    diff_filtered = 0

    for tool_result in state.get("raw_tool_results", []):
        language = str(tool_result.get("language") or "unknown")
        tool_result_tool = str(tool_result.get("tool") or "unknown")

        raw_findings = tool_result.get("raw_findings") or []
        if not isinstance(raw_findings, list):
            continue

        for raw in raw_findings:
            if not isinstance(raw, dict):
                dropped += 1
                continue

            tool = _extract_tool_name(tool_result_tool, raw)

            # 如果 message/file 都空，基本无意义，丢掉
            if not raw.get("message") and not raw.get("file"):
                dropped += 1
                continue

            finding = _normalize_one_raw(
                repo_root=repo_root,
                language=language,
                tool=tool,
                raw=raw,
            )
            if scan_mode == "diff":
                file_path = str(finding.get("file") or "")
                line = finding.get("line")
                in_diff = bool(
                    file_path
                    and isinstance(line, int)
                    and line > 0
                    and line in diff_line_index.get(file_path, set())
                )
                finding["in_diff"] = in_diff
                if diff_filter_mode == "only" and not in_diff:
                    diff_filtered += 1
                    continue

            normalized.append(finding)

    # 额外：对明显无 file 的 Finding 也保留，但你也可以在这里过滤
    state["normalized_findings"] = normalized
    if scan_mode == "diff":
        state.setdefault("logs", []).append(
            "normalize_findings(enhanced): "
            f"normalized={len(normalized)}, dropped={dropped}, diff_filtered={diff_filtered}, "
            f"diff_files={len(diff_line_index)}, diff_filter={diff_filter_mode}"
        )
    else:
        state.setdefault("logs", []).append(
            f"normalize_findings(enhanced): normalized={len(normalized)}, dropped={dropped}"
        )
    return state
