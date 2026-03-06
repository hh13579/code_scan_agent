from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any

from code_scan_agent.graph.state import GraphState, ToolResult
from code_scan_agent.tools.shell_runner import is_command_available, run_command


_LANG_BY_EXT = {
    ".c": "cpp",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".java": "java",
    ".ts": "ts",
    ".tsx": "ts",
    ".js": "ts",
    ".jsx": "ts",
}

_DEFAULT_EXCLUDES = [
    ".git",
    "build",
    "dist",
    "node_modules",
    "vendor",
    "third_party",
    "third-64",
]


def _infer_language(file_path: str) -> str:
    ext = Path(file_path).suffix.lower()
    return _LANG_BY_EXT.get(ext, "ts")


def _split_args(raw: str) -> list[str]:
    if not raw.strip():
        return []
    try:
        return shlex.split(raw)
    except ValueError:
        return []


def _parse_semgrep_json(stdout: str) -> tuple[list[dict[str, Any]], str | None]:
    text = stdout.strip()
    if not text:
        return [], None

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return [], f"semgrep json parse failed: {e}"

    results = data.get("results", [])
    if not isinstance(results, list):
        return [], "semgrep response missing results list"

    findings: list[dict[str, Any]] = []
    for item in results:
        if not isinstance(item, dict):
            continue

        extra = item.get("extra", {}) if isinstance(item.get("extra"), dict) else {}
        start = item.get("start", {}) if isinstance(item.get("start"), dict) else {}
        metadata = extra.get("metadata", {}) if isinstance(extra.get("metadata"), dict) else {}

        file_path = str(item.get("path", ""))
        severity = str(extra.get("severity", "info")).lower()
        message = str(extra.get("message", "")).strip()
        rule_id = str(item.get("check_id", "semgrep"))
        snippet = extra.get("lines")
        confidence = str(metadata.get("confidence", "high")).lower()
        category = str(
            metadata.get("category")
            or metadata.get("cwe")
            or "security"
        )
        autofix_available = bool(item.get("fix") or item.get("fix_regex"))

        findings.append(
            {
                "tool": "semgrep",
                "rule_id": rule_id,
                "severity": severity,
                "file": file_path,
                "line": start.get("line"),
                "column": start.get("col"),
                "message": message,
                "snippet": snippet if isinstance(snippet, str) else None,
                "confidence": confidence,
                "category": category,
                "autofix_available": autofix_available,
                "language": _infer_language(file_path),
            }
        )

    return findings, None


def _build_semgrep_cmd(repo_path: Path, state: GraphState) -> list[str]:
    request = state.get("request", {})
    mode = request.get("mode", "full")
    selected_paths = list(request.get("selected_paths", []))
    include_globs = list(request.get("include_globs", []))
    exclude_globs = list(request.get("exclude_globs", []))

    config = os.getenv("SEMGREP_CONFIG", "p/security-audit")
    timeout_sec = os.getenv("SEMGREP_RULE_TIMEOUT_SEC", "15")
    metrics = os.getenv("SEMGREP_METRICS", "").strip()
    if not metrics:
        metrics = "auto" if config == "auto" else "off"

    cmd = [
        "semgrep",
        "--json",
        "--quiet",
        f"--metrics={metrics}",
        "--config",
        config,
        "--timeout",
        timeout_sec,
    ]

    for pattern in _DEFAULT_EXCLUDES:
        cmd.extend(["--exclude", pattern])
    for pattern in exclude_globs:
        cmd.extend(["--exclude", pattern])
    for pattern in include_globs:
        cmd.extend(["--include", pattern])

    cmd.extend(_split_args(os.getenv("SEMGREP_EXTRA_ARGS", "")))

    if mode == "selected" and selected_paths:
        for p in selected_paths:
            p_obj = Path(p)
            if not p_obj.is_absolute():
                p_obj = repo_path / p_obj
            try:
                rel = p_obj.resolve().relative_to(repo_path)
                cmd.append(str(rel))
            except ValueError:
                continue
    elif mode == "diff":
        seen: set[str] = set()
        for t in state.get("targets", []):
            raw_path = str(t.get("path") or "").strip()
            if not raw_path:
                continue
            p_obj = Path(raw_path)
            if not p_obj.is_absolute():
                p_obj = repo_path / p_obj
            try:
                rel = str(p_obj.resolve().relative_to(repo_path))
            except ValueError:
                continue
            if rel in seen:
                continue
            seen.add(rel)
            cmd.append(rel)
        if not seen:
            cmd.append(".")
    else:
        cmd.append(".")

    return cmd


def run_security_scanners(state: GraphState) -> GraphState:
    if not state["request"].get("enable_security_scan", True):
        state.setdefault("logs", []).append("run_security_scanners: disabled")
        return state

    repo_profile = state.get("repo_profile", {})
    repo_path_str = repo_profile.get("repo_path")
    if not repo_path_str:
        state.setdefault("errors", []).append("run_security_scanners: missing repo_profile.repo_path")
        return state

    repo_path = Path(repo_path_str).resolve()
    raw_results = state.setdefault("raw_tool_results", [])
    request = state.get("request", {})
    mode = request.get("mode", "full")

    if mode == "diff" and not state.get("targets"):
        raw_results.append(
            {
                "tool": "semgrep",
                "language": "mixed",
                "success": True,
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "duration_ms": 0,
                "raw_findings": [],
            }
        )
        state.setdefault("logs", []).append("run_security_scanners: skipped (diff mode no targets)")
        return state

    if not is_command_available("semgrep"):
        raw_results.append(
            {
                "tool": "semgrep",
                "language": "mixed",
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": "semgrep not found in PATH",
                "duration_ms": 0,
                "raw_findings": [],
            }
        )
        state.setdefault("errors", []).append("run_security_scanners: semgrep not found in PATH")
        state.setdefault("logs", []).append("run_security_scanners: semgrep not found, skipped")
        return state

    cmd = _build_semgrep_cmd(repo_path, state)
    timeout_sec = int(os.getenv("SEMGREP_TIMEOUT_SEC", "300"))
    cmd_result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_sec, check=False)

    parsed_findings, parse_error = _parse_semgrep_json(cmd_result.get("stdout", ""))
    success = cmd_result.get("error") is None and cmd_result.get("exit_code", -1) in (0, 1)
    stderr = cmd_result.get("stderr", "")
    if parse_error:
        success = False
        stderr = f"{stderr}\n{parse_error}".strip()

    result: ToolResult = {
        "tool": "semgrep",
        "language": "mixed",
        "success": success,
        "exit_code": cmd_result.get("exit_code", -1),
        "stdout": cmd_result.get("stdout", ""),
        "stderr": stderr,
        "duration_ms": cmd_result.get("duration_ms", 0),
        "raw_findings": parsed_findings,
    }
    raw_results.append(result)

    state.setdefault("logs", []).append(
        f"run_security_scanners: exit={result['exit_code']}, findings={len(parsed_findings)}"
    )
    if not success:
        msg = cmd_result.get("error") or parse_error or "semgrep execution failed"
        state.setdefault("errors", []).append(f"run_security_scanners: {msg}")

    return state
