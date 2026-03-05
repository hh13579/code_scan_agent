from __future__ import annotations

import json
import os
import re
import shlex
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from code_scan_agent.graph.state import GraphState, ToolResult
from code_scan_agent.tools.shell_runner import is_command_available, run_command


_CLANG_TIDY_LINE_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<column>\d+):\s+"
    r"(?P<severity>warning|error):\s+"
    r"(?P<message>.+?)"
    r"(?:\s+\[(?P<rule_id>[^\]]+)\])?$"
)


_BUILTIN_PATTERNS: list[tuple[str, str, re.Pattern[str], str]] = [
    (
        "CPP_UNSAFE_STRCPY",
        "high",
        re.compile(r"\bstrcpy\s*\("),
        "Use of strcpy may cause buffer overflow; consider strncpy/strlcpy.",
    ),
    (
        "CPP_UNSAFE_STRCAT",
        "high",
        re.compile(r"\bstrcat\s*\("),
        "Use of strcat may cause buffer overflow; prefer strncat/safe string builder.",
    ),
    (
        "CPP_UNSAFE_SPRINTF",
        "high",
        re.compile(r"\bsprintf\s*\("),
        "Use of sprintf is unsafe; prefer snprintf with explicit buffer length.",
    ),
    (
        "CPP_UNSAFE_GETS",
        "critical",
        re.compile(r"\bgets\s*\("),
        "Use of gets is unsafe and should be removed.",
    ),
    (
        "CPP_COMMAND_EXEC",
        "high",
        re.compile(r"\b(system|popen)\s*\("),
        "Command execution API used; validate and sanitize all external inputs.",
    ),
]

_CPP_SOURCE_EXTS = {".c", ".cc", ".cpp", ".cxx", ".c++", ".cp"}
_CPP_HEADER_EXTS = {".h", ".hh", ".hpp", ".hxx", ".h++"}
_DEFAULT_THIRD_PARTY_PREFIXES = [
    "third_party/",
    "third-64/",
    "thirdparty/",
    "vendor/",
    "external/",
    "node_modules/",
    "build/",
    "dist/",
    "nav_wrapper/protobuf_google_src/",
    "nav_wrapper/protobuf_google_src_2.5/",
    "nav_wrapper/rn_dependencies/",
]


def _split_args(raw: str) -> list[str]:
    if not raw.strip():
        return []
    try:
        return shlex.split(raw)
    except ValueError:
        return []


def _normalize_rel_path(path_text: str) -> str:
    return path_text.replace("\\", "/").lstrip("./")


def _normalize_prefix(prefix: str) -> str:
    p = _normalize_rel_path(prefix).lower()
    if p and not p.endswith("/"):
        p += "/"
    return p


def _third_party_prefixes() -> list[str]:
    extra_raw = os.getenv("CPP_THIRD_PARTY_EXCLUDES", "")
    extra = [_normalize_prefix(x) for x in extra_raw.split(",") if x.strip()]

    seen: set[str] = set()
    out: list[str] = []
    for p in [_normalize_prefix(x) for x in _DEFAULT_THIRD_PARTY_PREFIXES] + extra:
        if not p or p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _is_cpp_source_file(rel_path: str) -> bool:
    ext = Path(rel_path).suffix.lower()
    if ext in _CPP_HEADER_EXTS:
        return False
    return ext in _CPP_SOURCE_EXTS


def _is_third_party_path(rel_path: str, prefixes: list[str]) -> bool:
    rel = _normalize_rel_path(rel_path).lower()
    if any(rel.startswith(p) for p in prefixes):
        return True
    parts = rel.split("/")
    return any(part in {"third_party", "thirdparty", "vendor", "external", "node_modules"} for part in parts)


def _find_compile_db(repo_path: Path, state: GraphState) -> str | None:
    repo_profile = state.get("repo_profile", {})
    compile_db = repo_profile.get("compile_db_path")
    if compile_db:
        return str(Path(compile_db).resolve())

    hit = repo_path / "compile_commands.json"
    if hit.is_file():
        return str(hit.resolve())

    for p in repo_path.rglob("compile_commands.json"):
        if p.is_file():
            return str(p.resolve())

    return None


def _load_compile_db_units(
    repo_path: Path,
    compile_db_path: str,
    third_party_prefixes: list[str],
) -> tuple[list[str], list[str]]:
    logs: list[str] = []
    compile_db = Path(compile_db_path).resolve()
    try:
        data = json.loads(compile_db.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as e:
        logs.append(f"compile_db: failed to read/parse {compile_db}: {e}")
        return [], logs

    if not isinstance(data, list):
        logs.append(f"compile_db: unexpected JSON root (expected list): {type(data).__name__}")
        return [], logs

    units: list[str] = []
    seen: set[str] = set()
    skipped_non_source = 0
    skipped_third_party = 0
    skipped_non_repo = 0
    skipped_missing = 0

    for item in data:
        if not isinstance(item, dict):
            continue
        raw_file = item.get("file")
        if not isinstance(raw_file, str) or not raw_file.strip():
            continue

        raw_dir = item.get("directory")
        if Path(raw_file).is_absolute():
            abs_file = Path(raw_file).resolve()
        elif isinstance(raw_dir, str) and raw_dir.strip():
            abs_file = (Path(raw_dir) / raw_file).resolve()
        else:
            abs_file = (repo_path / raw_file).resolve()

        if not abs_file.exists():
            skipped_missing += 1
            continue
        if not abs_file.is_file():
            continue
        if not abs_file.is_relative_to(repo_path):
            skipped_non_repo += 1
            continue

        rel = _normalize_rel_path(str(abs_file.relative_to(repo_path)))
        if not _is_cpp_source_file(rel):
            skipped_non_source += 1
            continue
        if _is_third_party_path(rel, third_party_prefixes):
            skipped_third_party += 1
            continue
        if rel in seen:
            continue

        seen.add(rel)
        units.append(rel)

    logs.append(
        "compile_db: entries="
        f"{len(data)}, units={len(units)}, skipped_non_source={skipped_non_source}, "
        f"skipped_third_party={skipped_third_party}, skipped_non_repo={skipped_non_repo}, skipped_missing={skipped_missing}"
    )
    return units, logs


def _parse_clang_tidy_output(stdout: str, stderr: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    text = "\n".join([stdout, stderr]).strip()

    for line in text.splitlines():
        m = _CLANG_TIDY_LINE_RE.match(line.strip())
        if not m:
            continue

        rule_id = m.group("rule_id") or "clang-tidy"
        findings.append(
            {
                "tool": "clang-tidy",
                "rule_id": rule_id,
                "severity": m.group("severity").lower(),
                "file": m.group("file"),
                "line": int(m.group("line")),
                "column": int(m.group("column")),
                "message": m.group("message").strip(),
            }
        )

    return findings


def _parse_cppcheck_xml(stderr_xml: str) -> list[dict[str, Any]]:
    """
    cppcheck 常用：
      cppcheck --xml --xml-version=2 ...
    XML 大多输出到 stderr。
    """
    findings: list[dict[str, Any]] = []
    xml_text = stderr_xml.strip()
    if not xml_text:
        return findings

    # cppcheck stderr 常混有非 XML 文本，先尝试抽取 <results>...</results>
    start_idx = xml_text.find("<results")
    end_idx = xml_text.rfind("</results>")
    if start_idx != -1 and end_idx != -1:
        xml_text = xml_text[start_idx:end_idx + len("</results>")]

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        # 有些环境会夹杂非 XML 文本，第一版先容错返回空
        return findings

    errors_node = root.find("errors")
    if errors_node is None:
        return findings

    for err in errors_node.findall("error"):
        severity = err.attrib.get("severity", "info")
        message = err.attrib.get("msg", "") or err.attrib.get("verbose", "")
        rule_id = err.attrib.get("id", "cppcheck")

        locations = err.findall("location")
        if locations:
            for loc in locations:
                file_path = loc.attrib.get("file", "")
                line_str = loc.attrib.get("line")
                column_str = loc.attrib.get("column")
                findings.append(
                    {
                        "tool": "cppcheck",
                        "rule_id": rule_id,
                        "severity": severity,
                        "file": file_path,
                        "line": int(line_str) if line_str and line_str.isdigit() else None,
                        "column": int(column_str) if column_str and column_str.isdigit() else None,
                        "message": message,
                    }
                )
        else:
            findings.append(
                {
                    "tool": "cppcheck",
                    "rule_id": rule_id,
                    "severity": severity,
                    "file": "",
                    "line": None,
                    "column": None,
                    "message": message,
                }
            )

    return findings


def _extract_failure_reason(result: dict[str, Any]) -> str:
    if result.get("error"):
        return str(result["error"])

    text = "\n".join([str(result.get("stderr", "")), str(result.get("stdout", ""))]).strip()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("suppressed "):
            continue
        if low.startswith("use -header-filter"):
            continue
        if "warning generated" in low:
            continue
        if "error while processing" in low:
            return line[:220]
        if "error:" in low:
            return line[:220]
        if "fatal" in low:
            return line[:220]

    return f"exit={result.get('exit_code', -1)} with no diagnostics"


def _run_clang_tidy(
    repo_path: Path,
    cpp_files: list[str],
    compile_db_path: str | None,
    third_party_prefixes: list[str],
    extra_args: list[str] | None = None,
    timeout_per_file_sec: int = 60,
) -> tuple[list[dict[str, Any]], list[str], int]:
    """
    逐文件运行 clang-tidy，便于：
    - 精确定位失败文件
    - 避免一次性传太多文件
    返回：
    - findings
    - logs
    - total_duration_ms
    """
    findings: list[dict[str, Any]] = []
    logs: list[str] = []
    total_duration_ms = 0

    if not is_command_available("clang-tidy"):
        logs.append("clang-tidy not found in PATH, skipped")
        return findings, logs, total_duration_ms

    if not compile_db_path:
        logs.append("compile_commands.json not found, clang-tidy skipped")
        return findings, logs, total_duration_ms

    p_flag = str(Path(compile_db_path).parent)
    extra_args = list(extra_args or [])
    if not any(a.startswith("-checks=") or a.startswith("--checks=") for a in extra_args):
        extra_args.append("-checks=clang-analyzer-*,bugprone-*")
    if not any(a.startswith("-header-filter=") or a.startswith("--header-filter=") for a in extra_args):
        extra_args.append("--header-filter=^$")
    if not any(a.startswith("--system-headers") for a in extra_args):
        extra_args.append("--system-headers=0")
    per_file_log = os.getenv("CLANG_TIDY_LOG_PER_FILE", "0").strip() == "1"

    failure_reasons: Counter[str] = Counter()
    failure_sample_file: dict[str, str] = {}
    nonzero_exit_files = 0

    for file_path in cpp_files:
        cmd = [
            "clang-tidy",
            file_path,
            "-p",
            p_flag,
            "--quiet",
            *extra_args,
        ]
        result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_per_file_sec, check=False)
        total_duration_ms += result.get("duration_ms", 0)

        parsed_findings = _parse_clang_tidy_output(
            result.get("stdout", ""),
            result.get("stderr", ""),
        )
        file_findings: list[dict[str, Any]] = []
        for f in parsed_findings:
            raw_file = str(f.get("file", ""))
            if not raw_file:
                continue
            p = Path(raw_file)
            if not p.is_absolute():
                p = (repo_path / p).resolve()
            else:
                p = p.resolve()
            if not p.is_relative_to(repo_path):
                continue
            rel = _normalize_rel_path(str(p.relative_to(repo_path)))
            if not _is_cpp_source_file(rel):
                continue
            if _is_third_party_path(rel, third_party_prefixes):
                continue
            out = dict(f)
            out["file"] = rel
            file_findings.append(out)
        findings.extend(file_findings)

        exit_code = int(result.get("exit_code", -1))
        if exit_code != 0 or result.get("error"):
            nonzero_exit_files += 1
            reason = _extract_failure_reason(result)
            failure_reasons[reason] += 1
            failure_sample_file.setdefault(reason, file_path)

        if per_file_log:
            logs.append(f"clang-tidy: file={file_path}, exit={exit_code}, findings={len(file_findings)}")

    logs.append(
        f"clang-tidy summary: files={len(cpp_files)}, findings={len(findings)}, nonzero_exit={nonzero_exit_files}"
    )
    for reason, count in failure_reasons.most_common(12):
        sample = failure_sample_file.get(reason, "")
        logs.append(f"clang-tidy failure: {count}x {reason} | sample={sample}")

    return findings, logs, total_duration_ms


def _run_cppcheck(
    repo_path: Path,
    cpp_files: list[str],
    compile_db_path: str | None,
    third_party_prefixes: list[str],
    extra_args: list[str] | None = None,
    timeout_sec: int = 180,
) -> tuple[list[dict[str, Any]], list[str], int]:
    findings: list[dict[str, Any]] = []
    logs: list[str] = []
    total_duration_ms = 0

    if not is_command_available("cppcheck"):
        logs.append("cppcheck not found in PATH, skipped")
        return findings, logs, total_duration_ms

    if not cpp_files and not compile_db_path:
        logs.append("cppcheck skipped (no cpp files)")
        return findings, logs, total_duration_ms

    # --enable=warning,style,performance,portability,information
    # 如需更激进可加 unusedFunction，但会更慢
    cmd = [
        "cppcheck",
        "--xml",
        "--xml-version=2",
        "--enable=warning,style,performance,portability,information",
        "--inline-suppr",
    ]
    for prefix in third_party_prefixes:
        cmd.extend(["-i", prefix.rstrip("/")])
    if compile_db_path:
        cmd.append(f"--project={compile_db_path}")
    else:
        cmd.extend(cpp_files)
    cmd.extend(extra_args or [])

    result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_sec, check=False)
    total_duration_ms += result.get("duration_ms", 0)

    if result.get("error"):
        logs.append(f"cppcheck error: {result['error']}")
        return findings, logs, total_duration_ms

    # cppcheck 的 XML 常在 stderr
    findings = _parse_cppcheck_xml(result.get("stderr", "") or result.get("stdout", ""))
    mode = "project" if compile_db_path else "files"
    logs.append(f"cppcheck: exit={result.get('exit_code')}, findings={len(findings)}, mode={mode}")
    if int(result.get("exit_code", 0)) != 0 and not findings:
        reason = _extract_failure_reason(result)
        logs.append(f"cppcheck failure summary: {reason}")

    return findings, logs, total_duration_ms


def _run_builtin_cpp_pattern_scan(
    repo_path: Path,
    cpp_files: list[str],
    max_findings: int = 2000,
) -> tuple[list[dict[str, Any]], list[str], int]:
    findings: list[dict[str, Any]] = []
    logs: list[str] = []

    scanned_files = 0
    for rel in cpp_files:
        if len(findings) >= max_findings:
            logs.append(f"builtin_cpp_pattern: hit max_findings={max_findings}, stopped early")
            break

        full_path = Path(rel)
        if not full_path.is_absolute():
            full_path = repo_path / full_path
        if not full_path.is_file():
            continue

        scanned_files += 1
        try:
            text = full_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logs.append(f"builtin_cpp_pattern: read failed: {full_path}: {e}")
            continue

        rel_path = str(full_path.relative_to(repo_path)) if full_path.is_relative_to(repo_path) else str(full_path)
        for line_no, line_text in enumerate(text.splitlines(), start=1):
            for rule_id, severity, pattern, message in _BUILTIN_PATTERNS:
                m = pattern.search(line_text)
                if not m:
                    continue

                findings.append(
                    {
                        "tool": "builtin_cpp_pattern",
                        "rule_id": rule_id,
                        "severity": severity,
                        "file": rel_path,
                        "line": line_no,
                        "column": m.start() + 1,
                        "message": message,
                    }
                )

                if len(findings) >= max_findings:
                    break
            if len(findings) >= max_findings:
                break

    logs.append(f"builtin_cpp_pattern: scanned={scanned_files}, findings={len(findings)}")
    return findings, logs, 0


def run_cpp_scanners(state: GraphState) -> GraphState:
    request = state.get("request", {})
    mode = request.get("mode", "full")

    targets = [t for t in state.get("targets", []) if t.get("language") == "cpp"]
    if not targets:
        state.setdefault("logs", []).append("run_cpp_scanners: skipped (no cpp targets)")
        return state

    raw_results = state.setdefault("raw_tool_results", [])
    repo_profile = state.get("repo_profile", {})
    repo_path_str = repo_profile.get("repo_path")
    if not repo_path_str:
        state.setdefault("errors", []).append("run_cpp_scanners: missing repo_profile.repo_path")
        return state

    repo_path = Path(repo_path_str).resolve()

    third_party_prefixes = _third_party_prefixes()

    # 尽量转成相对 repo 的路径，工具输出更稳定
    target_cpp_files: list[str] = []
    for t in targets:
        p = Path(t["path"]).resolve()
        try:
            rel = _normalize_rel_path(str(p.relative_to(repo_path)))
        except ValueError:
            rel = _normalize_rel_path(str(p))
        if not _is_cpp_source_file(rel):
            continue
        if _is_third_party_path(rel, third_party_prefixes):
            continue
        target_cpp_files.append(rel)

    compile_db_path = _find_compile_db(repo_path, state)
    cpp_files = target_cpp_files
    if compile_db_path:
        compile_db_units, compile_db_logs = _load_compile_db_units(
            repo_path=repo_path,
            compile_db_path=compile_db_path,
            third_party_prefixes=third_party_prefixes,
        )
        state.setdefault("logs", []).extend([f"run_cpp_scanners detail: {x}" for x in compile_db_logs])
        if compile_db_units:
            if mode == "selected":
                selected_set = set(target_cpp_files)
                intersect_units = [p for p in compile_db_units if p in selected_set]
                if intersect_units:
                    cpp_files = intersect_units
                    state.setdefault("logs", []).append(
                        "run_cpp_scanners: using compile_db intersection "
                        f"units={len(cpp_files)} (selected_targets={len(target_cpp_files)})"
                    )
                else:
                    cpp_files = target_cpp_files
                    state.setdefault("logs", []).append(
                        "run_cpp_scanners: selected mode has no compile_db intersection, "
                        f"fallback to selected_targets={len(target_cpp_files)}"
                    )
            else:
                cpp_files = compile_db_units
                state.setdefault("logs", []).append(
                    f"run_cpp_scanners: using compile_db units={len(cpp_files)} (targets_filtered={len(target_cpp_files)})"
                )
        else:
            state.setdefault("logs", []).append(
                f"run_cpp_scanners: compile_db had no usable units, fallback to targets_filtered={len(target_cpp_files)}"
            )

    max_files = int(os.getenv("CPP_SCAN_MAX_FILES", "0"))
    if max_files > 0 and len(cpp_files) > max_files:
        cpp_files = cpp_files[:max_files]
        state.setdefault("logs", []).append(
            f"run_cpp_scanners: capped cpp files to {max_files} by CPP_SCAN_MAX_FILES"
        )

    clang_timeout = int(os.getenv("CLANG_TIDY_TIMEOUT_SEC", "60"))
    cppcheck_timeout = int(os.getenv("CPPCHECK_TIMEOUT_SEC", "180"))
    clang_extra_args = _split_args(os.getenv("CLANG_TIDY_EXTRA_ARGS", ""))
    cppcheck_extra_args = _split_args(os.getenv("CPPCHECK_EXTRA_ARGS", ""))

    combined_findings: list[dict[str, Any]] = []
    detail_logs: list[str] = []
    total_duration_ms = 0
    success = True
    exit_code = 0
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []

    # 1) clang-tidy
    clang_findings, clang_logs, clang_ms = _run_clang_tidy(
        repo_path=repo_path,
        cpp_files=cpp_files,
        compile_db_path=compile_db_path,
        third_party_prefixes=third_party_prefixes,
        extra_args=clang_extra_args,
        timeout_per_file_sec=clang_timeout,
    )
    combined_findings.extend(clang_findings)
    detail_logs.extend(clang_logs)
    total_duration_ms += clang_ms

    # 2) cppcheck
    cppcheck_compile_db = compile_db_path if mode != "selected" else None
    if mode == "selected" and compile_db_path:
        state.setdefault("logs", []).append("run_cpp_scanners: selected mode -> cppcheck uses explicit file list")

    cppcheck_findings, cppcheck_logs, cppcheck_ms = _run_cppcheck(
        repo_path=repo_path,
        cpp_files=cpp_files,
        compile_db_path=cppcheck_compile_db,
        third_party_prefixes=third_party_prefixes,
        extra_args=cppcheck_extra_args,
        timeout_sec=cppcheck_timeout,
    )
    combined_findings.extend(cppcheck_findings)
    detail_logs.extend(cppcheck_logs)
    total_duration_ms += cppcheck_ms

    clang_executed = any(log.startswith("clang-tidy summary:") for log in clang_logs)
    cppcheck_executed = any(log.startswith("cppcheck: exit=") for log in cppcheck_logs)

    # 3) fallback: 内置模式扫描，确保在无外部工具时仍可产出发现
    if not clang_executed and not cppcheck_executed:
        fallback_findings, fallback_logs, fallback_ms = _run_builtin_cpp_pattern_scan(
            repo_path=repo_path,
            cpp_files=cpp_files,
            max_findings=2000,
        )
        combined_findings.extend(fallback_findings)
        detail_logs.extend(fallback_logs)
        total_duration_ms += fallback_ms

    # 如果三个扫描都没跑起来，则视为失败但不中断全图
    if (
        not clang_executed
        and not cppcheck_executed
        and not any("builtin_cpp_pattern:" in x for x in detail_logs)
        and (
            any("not found in PATH" in x for x in detail_logs)
            or any("skipped" in x for x in detail_logs)
        )
    ):
        success = False
        exit_code = -1
        stderr_parts.append("No C++ scanner executed successfully")

    result: ToolResult = {
        # 保持和你 builder.py 当前路由兼容
        "tool": "cpp_scanners",
        "language": "cpp",
        "success": success,
        "exit_code": exit_code,
        "stdout": "\n".join(stdout_parts) if stdout_parts else "cpp scanners finished",
        "stderr": "\n".join(stderr_parts),
        "duration_ms": total_duration_ms,
        "raw_findings": combined_findings,
    }
    raw_results.append(result)

    state.setdefault("logs", []).append(
        f"run_cpp_scanners: processed {len(cpp_files)} files, findings={len(combined_findings)}"
    )
    state["logs"].extend([f"run_cpp_scanners detail: {x}" for x in detail_logs])

    if not success:
        state.setdefault("errors", []).append("run_cpp_scanners: no scanner executed successfully")

    return state
