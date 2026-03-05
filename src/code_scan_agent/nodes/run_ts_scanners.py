from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from code_scan_agent.graph.state import GraphState, ToolResult
from code_scan_agent.tools.shell_runner import is_command_available, run_command


# --- tsc output parsing ---
# 常见 tsc 格式（默认 pretty off 时也类似）：
# path/to/file.ts(12,34): error TS2322: Type 'string' is not assignable to type 'number'.
_TSC_RE = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+),(?P<col>\d+)\):\s+"
    r"(?P<severity>error|warning)\s+"
    r"(?P<rule>TS\d+):\s+"
    r"(?P<message>.+)$"
)


def _find_tsconfig(repo_path: Path) -> str | None:
    # 优先根目录
    root = repo_path / "tsconfig.json"
    if root.is_file():
        return str(root.resolve())

    # 次选：任意子目录（monorepo）
    for p in repo_path.rglob("tsconfig.json"):
        if p.is_file():
            return str(p.resolve())

    return None


def _parse_tsc_output(stdout: str, stderr: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    text = "\n".join([stdout, stderr]).strip()
    if not text:
        return findings

    for line in text.splitlines():
        line = line.strip()
        m = _TSC_RE.match(line)
        if not m:
            continue

        findings.append(
            {
                "tool": "tsc",
                "rule_id": m.group("rule"),
                "severity": m.group("severity").lower(),
                "file": m.group("file"),
                "line": int(m.group("line")),
                "column": int(m.group("col")),
                "message": m.group("message").strip(),
            }
        )

    return findings


# --- eslint json parsing ---
def _parse_eslint_json(stdout: str) -> list[dict[str, Any]]:
    """
    eslint -f json 输出是一段 JSON 数组，每个元素对应一个文件：
    [
      {"filePath":"...","messages":[{"ruleId":"no-unused-vars","severity":2,"message":"...","line":1,"column":1,...}], ...}
    ]
    """
    stdout = stdout.strip()
    if not stdout:
        return []

    try:
        data = json.loads(stdout)
    except Exception:
        return []

    findings: list[dict[str, Any]] = []
    if not isinstance(data, list):
        return findings

    for file_entry in data:
        if not isinstance(file_entry, dict):
            continue
        file_path = file_entry.get("filePath", "") or file_entry.get("filePath", "")

        for msg in file_entry.get("messages", []) or []:
            if not isinstance(msg, dict):
                continue
            rule_id = msg.get("ruleId") or "eslint"
            sev_num = msg.get("severity", 1)  # 1 warn, 2 error
            sev = "error" if sev_num == 2 else "warning"
            findings.append(
                {
                    "tool": "eslint",
                    "rule_id": rule_id,
                    "severity": sev,
                    "file": file_path,
                    "line": msg.get("line"),
                    "column": msg.get("column"),
                    "message": msg.get("message", ""),
                }
            )

    return findings


def _relativize_paths(repo_path: Path, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    把 eslint/tsc 里可能出现的绝对路径尽量转成相对 repo 的路径，
    让 normalize_findings 更稳定。
    """
    repo_path = repo_path.resolve()
    out: list[dict[str, Any]] = []
    for f in findings:
        ff = dict(f)
        fp = str(ff.get("file") or "")
        if fp:
            p = Path(fp)
            try:
                if p.is_absolute():
                    ff["file"] = str(p.resolve().relative_to(repo_path))
            except Exception:
                pass
        out.append(ff)
    return out


def _run_tsc(repo_path: Path, tsconfig_path: str | None, timeout_sec: int = 240) -> tuple[list[dict[str, Any]], list[str], int]:
    findings: list[dict[str, Any]] = []
    logs: list[str] = []
    total_ms = 0

    if not (is_command_available("tsc") or is_command_available("npx")):
        logs.append("tsc not found (tsc or npx missing), skipped")
        return findings, logs, total_ms

    # 优先直接 tsc（全局/本地 bin 在 PATH）
    # 否则 fallback npx tsc
    if is_command_available("tsc"):
        base_cmd = ["tsc"]
    else:
        base_cmd = ["npx", "--yes", "tsc"]

    cmd = [*base_cmd, "--noEmit", "--pretty", "false"]

    # 如果找得到 tsconfig，更稳定（否则 tsc 会默认找当前目录）
    if tsconfig_path:
        # tsc -p <tsconfig>
        cmd += ["-p", tsconfig_path]
        logs.append(f"tsc: using tsconfig={Path(tsconfig_path).name}")
    else:
        logs.append("tsc: tsconfig.json not found, using default project resolution")

    result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_sec, check=False)
    total_ms += result.get("duration_ms", 0)

    if result.get("error"):
        logs.append(f"tsc error: {result['error']}")
        return findings, logs, total_ms

    findings = _parse_tsc_output(result.get("stdout", ""), result.get("stderr", ""))
    logs.append(f"tsc: exit={result.get('exit_code')}, findings={len(findings)}")
    return findings, logs, total_ms


def _run_eslint(repo_path: Path, targets: list[str], timeout_sec: int = 240) -> tuple[list[dict[str, Any]], list[str], int]:
    findings: list[dict[str, Any]] = []
    logs: list[str] = []
    total_ms = 0

    if not (is_command_available("eslint") or is_command_available("npx")):
        logs.append("eslint not found (eslint or npx missing), skipped")
        return findings, logs, total_ms

    # eslint 扫描范围：第一版扫 targets 里 ts/tsx 文件
    # 为了避免命令太长，限制一下数量（可配置化）
    max_files = 2000
    scan_files = targets[:max_files]

    # 优先 eslint，否则 npx eslint
    if is_command_available("eslint"):
        base_cmd = ["eslint"]
    else:
        base_cmd = ["npx", "--yes", "eslint"]

    # ESLint 新版 config 是 eslint.config.*，旧版是 .eslintrc*
    # 第一版不强制指定 config，让 eslint 自己加载项目配置
    cmd = [
        *base_cmd,
        "-f",
        "json",
        *scan_files,
    ]

    result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_sec, check=False)
    total_ms += result.get("duration_ms", 0)

    if result.get("error"):
        logs.append(f"eslint error: {result['error']}")
        return findings, logs, total_ms

    findings = _parse_eslint_json(result.get("stdout", ""))
    logs.append(f"eslint: exit={result.get('exit_code')}, findings={len(findings)}")

    # eslint 出错时常会把错误写到 stderr，比如配置问题；保留日志便于排障
    if result.get("stderr", "").strip():
        logs.append("eslint stderr (truncated): " + result["stderr"][:3000])

    return findings, logs, total_ms


def run_ts_scanners(state: GraphState) -> GraphState:
    targets = [t for t in state.get("targets", []) if t.get("language") == "ts"]
    if not targets:
        state.setdefault("logs", []).append("run_ts_scanners: skipped (no ts targets)")
        return state

    raw_results = state.setdefault("raw_tool_results", [])
    repo_profile = state.get("repo_profile", {})
    repo_path_str = repo_profile.get("repo_path")
    if not repo_path_str:
        state.setdefault("errors", []).append("run_ts_scanners: missing repo_profile.repo_path")
        return state

    repo_path = Path(repo_path_str).resolve()

    # 转成相对路径更稳定
    ts_files: list[str] = []
    for t in targets:
        p = Path(t["path"]).resolve()
        try:
            ts_files.append(str(p.relative_to(repo_path)))
        except Exception:
            ts_files.append(str(p))

    tsconfig_path = _find_tsconfig(repo_path)

    combined_findings: list[dict[str, Any]] = []
    detail_logs: list[str] = []
    total_ms = 0
    success = True
    exit_code = 0
    stderr_parts: list[str] = []

    # 1) tsc
    tsc_findings, tsc_logs, tsc_ms = _run_tsc(repo_path, tsconfig_path, timeout_sec=240)
    combined_findings.extend(tsc_findings)
    detail_logs.extend(tsc_logs)
    total_ms += tsc_ms

    # 2) eslint
    eslint_findings, eslint_logs, eslint_ms = _run_eslint(repo_path, ts_files, timeout_sec=240)
    combined_findings.extend(eslint_findings)
    detail_logs.extend(eslint_logs)
    total_ms += eslint_ms

    combined_findings = _relativize_paths(repo_path, combined_findings)

    # 判断是否完全没跑起来
    executed_any = any(x.startswith("tsc:") for x in detail_logs) or any(x.startswith("eslint:") for x in detail_logs)
    if not executed_any:
        success = False
        exit_code = -1
        stderr_parts.append("No TS scanner executed successfully")

    result: ToolResult = {
        # 保持 builder.py 路由兼容
        "tool": "ts_scanners",
        "language": "ts",
        "success": success,
        "exit_code": exit_code,
        "stdout": "ts scanners finished",
        "stderr": "\n".join(stderr_parts),
        "duration_ms": total_ms,
        "raw_findings": combined_findings,
    }
    raw_results.append(result)

    state.setdefault("logs", []).append(
        f"run_ts_scanners: processed {len(ts_files)} files, findings={len(combined_findings)}"
    )
    state["logs"].extend([f"run_ts_scanners detail: {x}" for x in detail_logs])

    if not success:
        state.setdefault("errors", []).append("run_ts_scanners: no scanner executed successfully")

    return state