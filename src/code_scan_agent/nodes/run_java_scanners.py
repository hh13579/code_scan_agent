from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from code_scan_agent.graph.state import GraphState, ToolResult
from code_scan_agent.tools.shell_runner import is_command_available, run_command


# -------------------------
# Helpers: detect build tool
# -------------------------

def _detect_java_build(repo_path: Path) -> str | None:
    if (repo_path / "pom.xml").is_file():
        return "maven"
    if (repo_path / "build.gradle").is_file() or (repo_path / "build.gradle.kts").is_file():
        return "gradle"
    # monorepo：有子模块
    for p in repo_path.rglob("pom.xml"):
        if p.is_file():
            return "maven"
    for p in repo_path.rglob("build.gradle"):
        if p.is_file():
            return "gradle"
    for p in repo_path.rglob("build.gradle.kts"):
        if p.is_file():
            return "gradle"
    return None


def _find_checkstyle_config(repo_path: Path) -> str | None:
    """
    约定优先级：
    - config/checkstyle/checkstyle.xml（很多团队常用）
    - checkstyle.xml
    - 任意 *checkstyle*.xml
    """
    candidates = [
        repo_path / "config" / "checkstyle" / "checkstyle.xml",
        repo_path / "checkstyle.xml",
    ]
    for c in candidates:
        if c.is_file():
            return str(c.resolve())

    for p in repo_path.rglob("*checkstyle*.xml"):
        if p.is_file():
            return str(p.resolve())

    return None


# -------------------------
# Parsing: SpotBugs (JSON)
# -------------------------

def _parse_spotbugs_json(text: str) -> list[dict[str, Any]]:
    """
    SpotBugs JSON 输出（不同版本字段可能不完全一致）：
    这里做“尽量解析”的宽松策略。
    """
    text = text.strip()
    if not text:
        return []

    try:
        data = json.loads(text)
    except Exception:
        return []

    findings: list[dict[str, Any]] = []

    # 常见形态：{"bugs":[...], ...}
    bugs = None
    if isinstance(data, dict):
        bugs = data.get("bugs") or data.get("BugCollection") or data.get("bugCollection")
    if bugs is None and isinstance(data, list):
        bugs = data

    if not isinstance(bugs, list):
        return findings

    for b in bugs:
        if not isinstance(b, dict):
            continue

        # 这些字段在不同输出里会有差异，所以都做兜底
        rule_id = b.get("type") or b.get("bugType") or b.get("abbrev") or "spotbugs"
        message = b.get("message") or b.get("shortMessage") or b.get("longMessage") or b.get("description") or ""

        # priority/rank: 1高 2中 3低（常见）
        priority = b.get("priority") or b.get("Priority")
        severity = "warning"
        if str(priority) == "1":
            severity = "error"
        elif str(priority) == "2":
            severity = "warning"
        else:
            severity = "info"

        # location：尽量从 sourceLine / primarySourceLine / class 里找
        file_path = ""
        line = None
        col = None

        # SpotBugs 常见字段：primarySourceLine / sourceLine / sourceLines
        sl = b.get("primarySourceLine") or b.get("sourceLine") or b.get("SourceLine")
        if isinstance(sl, dict):
            file_path = sl.get("sourcepath") or sl.get("sourcePath") or sl.get("filename") or sl.get("file") or ""
            start = sl.get("start") or sl.get("startLine")
            if start is not None:
                try:
                    line = int(start)
                except Exception:
                    line = None

        findings.append(
            {
                "tool": "spotbugs",
                "rule_id": str(rule_id),
                "severity": severity,
                "file": file_path,
                "line": line,
                "column": col,
                "message": str(message),
            }
        )

    return findings


# -------------------------
# Parsing: Checkstyle XML
# -------------------------

def _parse_checkstyle_xml(xml_text: str) -> list[dict[str, Any]]:
    """
    Checkstyle XML 典型格式：
    <checkstyle version="...">
      <file name="...">
        <error line=".." column=".." severity="warning" message="..." source="com.puppycrawl.tools.checkstyle.checks..."/>
      </file>
    </checkstyle>
    """
    xml_text = xml_text.strip()
    if not xml_text:
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    findings: list[dict[str, Any]] = []
    for file_node in root.findall("file"):
        file_path = file_node.attrib.get("name", "")
        for err in file_node.findall("error"):
            sev = err.attrib.get("severity", "warning")
            msg = err.attrib.get("message", "")
            src = err.attrib.get("source", "checkstyle")
            line = err.attrib.get("line")
            col = err.attrib.get("column")

            findings.append(
                {
                    "tool": "checkstyle",
                    "rule_id": src,  # 这里用 source 作 rule_id，后面可映射更友好名字
                    "severity": sev,
                    "file": file_path,
                    "line": int(line) if line and line.isdigit() else None,
                    "column": int(col) if col and col.isdigit() else None,
                    "message": msg,
                }
            )

    return findings


# -------------------------
# Build runners
# -------------------------

def _run_maven_spotbugs(repo_path: Path, timeout_sec: int = 600) -> tuple[list[dict[str, Any]], list[str], int]:
    """
    约定：项目 pom 已配置 spotbugs-maven-plugin 并启用 json 输出。
    如果没有配置，这一步会失败，我们记录 stderr 供排查。
    """
    logs: list[str] = []
    total_ms = 0

    if not (is_command_available("mvn") or is_command_available("mvnw")):
        logs.append("maven not found (mvn/mvnw missing), skipped spotbugs via maven")
        return [], logs, total_ms

    mvn = "mvnw" if (repo_path / "mvnw").is_file() else "mvn"

    # 最保守：先尝试 spotbugs:spotbugs
    cmd = [mvn, "-q", "-DskipTests", "spotbugs:spotbugs"]
    result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_sec, check=False)
    total_ms += result.get("duration_ms", 0)

    if result.get("error"):
        logs.append(f"maven spotbugs error: {result['error']}")
        return [], logs, total_ms

    # SpotBugs maven plugin 默认会产出 XML/HTML，不一定有 JSON。
    # 第一版策略：如果 stdout 里有 JSON 就解析；否则返回空 findings 并提示需要配置 JSON 输出或走 CLI fallback。
    findings = _parse_spotbugs_json(result.get("stdout", ""))
    logs.append(f"maven spotbugs: exit={result.get('exit_code')}, findings={len(findings)}")

    if not findings:
        logs.append("maven spotbugs: no JSON findings parsed (consider configuring spotbugs plugin output or use CLI fallback)")
        if result.get("stderr", "").strip():
            logs.append("maven spotbugs stderr (truncated): " + result["stderr"][:3000])

    return findings, logs, total_ms


def _run_gradle_spotbugs(repo_path: Path, timeout_sec: int = 900) -> tuple[list[dict[str, Any]], list[str], int]:
    """
    约定：项目已应用 com.github.spotbugs 插件且存在 spotbugsMain/spotbugsTest task。
    """
    logs: list[str] = []
    total_ms = 0

    if not (is_command_available("gradle") or (repo_path / "gradlew").is_file()):
        logs.append("gradle not found (gradle/gradlew missing), skipped spotbugs via gradle")
        return [], logs, total_ms

    gradle = "./gradlew" if (repo_path / "gradlew").is_file() else "gradle"

    # 常见 task：spotbugsMain
    cmd = [gradle, "-q", "spotbugsMain"]
    result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_sec, check=False)
    total_ms += result.get("duration_ms", 0)

    if result.get("error"):
        logs.append(f"gradle spotbugs error: {result['error']}")
        return [], logs, total_ms

    findings = _parse_spotbugs_json(result.get("stdout", ""))
    logs.append(f"gradle spotbugs: exit={result.get('exit_code')}, findings={len(findings)}")

    if not findings:
        logs.append("gradle spotbugs: no JSON findings parsed (configure spotbugs to output JSON, or use CLI fallback)")
        if result.get("stderr", "").strip():
            logs.append("gradle spotbugs stderr (truncated): " + result["stderr"][:3000])

    return findings, logs, total_ms


def _run_maven_checkstyle(repo_path: Path, timeout_sec: int = 600) -> tuple[list[dict[str, Any]], list[str], int]:
    """
    约定：pom 已配置 maven-checkstyle-plugin，并能在命令行执行 checkstyle:checkstyle。
    输出通常是报告文件，不一定 stdout。
    第一版策略：尝试跑插件；若 stdout/stderr 包含 XML 则解析（较少见）；否则提示建议 CLI fallback。
    """
    logs: list[str] = []
    total_ms = 0

    if not (is_command_available("mvn") or (repo_path / "mvnw").is_file()):
        logs.append("maven not found (mvn/mvnw missing), skipped checkstyle via maven")
        return [], logs, total_ms

    mvn = "mvnw" if (repo_path / "mvnw").is_file() else "mvn"
    cmd = [mvn, "-q", "-DskipTests", "checkstyle:checkstyle"]
    result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_sec, check=False)
    total_ms += result.get("duration_ms", 0)

    if result.get("error"):
        logs.append(f"maven checkstyle error: {result['error']}")
        return [], logs, total_ms

    # maven plugin 通常输出到 target/site/ 下的报告，stdout 未必是 XML
    findings = _parse_checkstyle_xml(result.get("stdout", "")) or _parse_checkstyle_xml(result.get("stderr", ""))
    logs.append(f"maven checkstyle: exit={result.get('exit_code')}, findings={len(findings)}")

    if not findings:
        logs.append("maven checkstyle: no XML findings parsed (plugin usually writes reports to target/site; consider CLI fallback)")
        if result.get("stderr", "").strip():
            logs.append("maven checkstyle stderr (truncated): " + result["stderr"][:3000])

    return findings, logs, total_ms


def _run_gradle_checkstyle(repo_path: Path, timeout_sec: int = 900) -> tuple[list[dict[str, Any]], list[str], int]:
    """
    约定：gradle 应用了 checkstyle plugin，有 checkstyleMain task
    """
    logs: list[str] = []
    total_ms = 0

    if not (is_command_available("gradle") or (repo_path / "gradlew").is_file()):
        logs.append("gradle not found (gradle/gradlew missing), skipped checkstyle via gradle")
        return [], logs, total_ms

    gradle = "./gradlew" if (repo_path / "gradlew").is_file() else "gradle"
    cmd = [gradle, "-q", "checkstyleMain"]
    result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_sec, check=False)
    total_ms += result.get("duration_ms", 0)

    if result.get("error"):
        logs.append(f"gradle checkstyle error: {result['error']}")
        return [], logs, total_ms

    findings = _parse_checkstyle_xml(result.get("stdout", "")) or _parse_checkstyle_xml(result.get("stderr", ""))
    logs.append(f"gradle checkstyle: exit={result.get('exit_code')}, findings={len(findings)}")

    if not findings:
        logs.append("gradle checkstyle: no XML findings parsed (reports typically written to build/reports; consider CLI fallback)")
        if result.get("stderr", "").strip():
            logs.append("gradle checkstyle stderr (truncated): " + result["stderr"][:3000])

    return findings, logs, total_ms


# -------------------------
# CLI fallbacks (optional)
# -------------------------

def _run_spotbugs_cli(repo_path: Path, timeout_sec: int = 900) -> tuple[list[dict[str, Any]], list[str], int]:
    """
    CLI fallback：尝试 spotbugs 命令 / npx 不适用（Java 工具），所以这里只能：
    - spotbugs（如果你安装了 spotbugs 命令）
    - 或者 java -jar spotbugs.jar（需要你自己提供 jar 路径，这里不猜）
    第一版：如果 spotbugs 命令可用，就跑 spotbugs -textui ... 并尽量 JSON（不同发行版差异较大）。
    """
    logs: list[str] = []
    total_ms = 0

    if not is_command_available("spotbugs"):
        logs.append("spotbugs CLI not found, skipped CLI fallback")
        return [], logs, total_ms

    # NOTE: spotbugs CLI 输出 JSON 的参数在不同版本/包装里差异较大
    # 这里先跑 textui，后续你可以换成 -xml/-sarif 这类更稳定输出
    cmd = ["spotbugs", "-textui", "-effort:max", "-low", "-quiet", "."]
    result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_sec, check=False)
    total_ms += result.get("duration_ms", 0)

    if result.get("error"):
        logs.append(f"spotbugs CLI error: {result['error']}")
        return [], logs, total_ms

    # textui 不太好结构化解析，第一版：不强行解析，留给你后面用 XML/SARIF
    logs.append("spotbugs CLI executed (text output not parsed in v1). Consider using SARIF/XML output for parsing.")
    if result.get("stdout", "").strip():
        logs.append("spotbugs CLI stdout (truncated): " + result["stdout"][:2000])
    if result.get("stderr", "").strip():
        logs.append("spotbugs CLI stderr (truncated): " + result["stderr"][:2000])

    return [], logs, total_ms


def _run_checkstyle_cli(repo_path: Path, config_path: str | None, java_files: list[str], timeout_sec: int = 600) -> tuple[list[dict[str, Any]], list[str], int]:
    """
    CLI fallback：checkstyle 一般是 jar 运行：
      java -jar checkstyle-<ver>-all.jar -c <config.xml> -f xml <files...>
    但 jar 路径无法猜。第一版：如果你装了 checkstyle 命令（很少），则尝试：
      checkstyle -c <config> -f xml <files...>
    """
    logs: list[str] = []
    total_ms = 0

    if not is_command_available("checkstyle"):
        logs.append("checkstyle CLI not found, skipped CLI fallback")
        return [], logs, total_ms

    if not config_path:
        logs.append("checkstyle config not found, skipped CLI fallback")
        return [], logs, total_ms

    # 限制文件数量，避免命令过长
    scan_files = java_files[:2000]
    cmd = ["checkstyle", "-c", config_path, "-f", "xml", *scan_files]
    result = run_command(cmd, cwd=repo_path, timeout_sec=timeout_sec, check=False)
    total_ms += result.get("duration_ms", 0)

    if result.get("error"):
        logs.append(f"checkstyle CLI error: {result['error']}")
        return [], logs, total_ms

    findings = _parse_checkstyle_xml(result.get("stdout", ""))
    logs.append(f"checkstyle CLI: exit={result.get('exit_code')}, findings={len(findings)}")

    return findings, logs, total_ms


# -------------------------
# Main node: run_java_scanners
# -------------------------

def _relativize(repo_path: Path, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
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


def run_java_scanners(state: GraphState) -> GraphState:
    targets = [t for t in state.get("targets", []) if t.get("language") == "java"]
    if not targets:
        state.setdefault("logs", []).append("run_java_scanners: skipped (no java targets)")
        return state

    raw_results = state.setdefault("raw_tool_results", [])
    repo_profile = state.get("repo_profile", {})
    repo_path_str = repo_profile.get("repo_path")
    if not repo_path_str:
        state.setdefault("errors", []).append("run_java_scanners: missing repo_profile.repo_path")
        return state

    repo_path = Path(repo_path_str).resolve()
    java_build = _detect_java_build(repo_path)

    # 目标文件（相对路径）
    java_files: list[str] = []
    for t in targets:
        p = Path(t["path"]).resolve()
        try:
            java_files.append(str(p.relative_to(repo_path)))
        except Exception:
            java_files.append(str(p))

    combined_findings: list[dict[str, Any]] = []
    detail_logs: list[str] = []
    total_ms = 0
    success = True
    exit_code = 0
    stderr_parts: list[str] = []

    # --- SpotBugs ---
    spotbugs_findings: list[dict[str, Any]] = []
    if java_build == "maven":
        f, l, ms = _run_maven_spotbugs(repo_path)
        spotbugs_findings, detail_logs, total_ms = f, detail_logs + l, total_ms + ms
    elif java_build == "gradle":
        f, l, ms = _run_gradle_spotbugs(repo_path)
        spotbugs_findings, detail_logs, total_ms = f, detail_logs + l, total_ms + ms
    else:
        # 没有构建系统，尝试 CLI fallback（不一定能解析）
        f, l, ms = _run_spotbugs_cli(repo_path)
        spotbugs_findings, detail_logs, total_ms = f, detail_logs + l, total_ms + ms

    combined_findings.extend(spotbugs_findings)

    # --- Checkstyle ---
    checkstyle_findings: list[dict[str, Any]] = []
    if java_build == "maven":
        f, l, ms = _run_maven_checkstyle(repo_path)
        checkstyle_findings, detail_logs, total_ms = f, detail_logs + l, total_ms + ms
    elif java_build == "gradle":
        f, l, ms = _run_gradle_checkstyle(repo_path)
        checkstyle_findings, detail_logs, total_ms = f, detail_logs + l, total_ms + ms
    else:
        config = _find_checkstyle_config(repo_path)
        f, l, ms = _run_checkstyle_cli(repo_path, config, java_files)
        checkstyle_findings, detail_logs, total_ms = f, detail_logs + l, total_ms + ms

    combined_findings.extend(checkstyle_findings)

    combined_findings = _relativize(repo_path, combined_findings)

    # 判断是否至少有一个工具“真正产生可解析 findings”
    executed_any = (
        any(x.startswith("maven spotbugs:") or x.startswith("gradle spotbugs:") for x in detail_logs)
        or any(x.startswith("maven checkstyle:") or x.startswith("gradle checkstyle:") for x in detail_logs)
        or any("CLI executed" in x for x in detail_logs)
    )

    # 更可靠的判断：至少有一次 runner 运行过
    # 这里简单：如果 build tool 都缺且 CLI 也缺，就失败
    if (java_build in (None, "") and not (is_command_available("spotbugs") or is_command_available("checkstyle"))):
        success = False
        exit_code = -1
        stderr_parts.append("No Java scanner executed successfully (missing build tool and CLI tools)")

    result: ToolResult = {
        "tool": "java_scanners",  # 保持 builder.py 路由兼容
        "language": "java",
        "success": success,
        "exit_code": exit_code,
        "stdout": "java scanners finished",
        "stderr": "\n".join(stderr_parts),
        "duration_ms": total_ms,
        "raw_findings": combined_findings,
    }
    raw_results.append(result)

    state.setdefault("logs", []).append(
        f"run_java_scanners: build={java_build}, processed {len(java_files)} files, findings={len(combined_findings)}"
    )
    state["logs"].extend([f"run_java_scanners detail: {x}" for x in detail_logs])

    if not success:
        state.setdefault("errors", []).append("run_java_scanners: no scanner executed successfully")

    return state