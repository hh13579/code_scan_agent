from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from code_scan_agent.tools.local_env import load_local_env

try:
    import certifi
except Exception:  # noqa: BLE001
    certifi = None


_HUNK_RE = re.compile(r"^@@\s+-\d+(?:,\d+)?\s+\+(?P<start>\d+)(?:,(?P<count>\d+))?\s+@@")
_KEY_LOG_MARKERS = (
    "discover_repo:",
    "collect_targets detail:",
    "collect_targets:",
    "choose_toolchains:",
    "run_cpp_scanners:",
    "run_java_scanners:",
    "run_ts_scanners:",
    "run_security_scanners:",
    "normalize_findings",
    "llm_triage:",
    "build_report:",
    "Report written to:",
    "Errors:",
)
_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_REVIEW_ACTION_TO_JUDGEMENT = {
    "block": "建议修复",
    "should_fix": "建议修复",
    "follow_up": "需要人工确认",
}
_CONFIDENCE_ZH = {"high": "高", "medium": "中", "low": "低"}


def _get_int_env(name: str, default: int, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default
    if min_value is not None and value < min_value:
        return min_value
    return value


def _get_float_env(name: str, default: float, min_value: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            value = default
    if min_value is not None and value < min_value:
        return min_value
    return value


def _build_api_url() -> str:
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    if base_url.endswith("/v1"):
        return f"{base_url}/chat/completions"
    return f"{base_url}/v1/chat/completions"


def _build_ssl_context() -> ssl.SSLContext | None:
    insecure = os.getenv("DEEPSEEK_INSECURE_SKIP_VERIFY", "").strip().lower()
    if insecure in {"1", "true", "yes", "on"}:
        return ssl._create_unverified_context()
    cafile = os.getenv("SSL_CERT_FILE", "").strip()
    if not cafile and certifi is not None:
        try:
            cafile = certifi.where()
        except Exception:  # noqa: BLE001
            cafile = ""
    if not cafile:
        return None
    try:
        return ssl.create_default_context(cafile=cafile)
    except Exception:  # noqa: BLE001
        return None


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_+-]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)

    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", stripped)
    if not match:
        return {}

    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def _call_deepseek(messages: list[dict[str, str]]) -> dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")

    payload = {
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
        "temperature": 0.1,
        "messages": messages,
        "response_format": {"type": "json_object"},
    }
    req = request.Request(
        _build_api_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout_sec = _get_int_env("DEEPSEEK_TIMEOUT_SEC", 90, min_value=1)

    try:
        with request.urlopen(req, timeout=timeout_sec, context=_build_ssl_context()) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek HTTP {exc.code}: {detail[:500]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"DeepSeek connection failed: {exc}") from exc

    try:
        api_json = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"DeepSeek returned non-JSON body: {body[:300]}") from exc

    try:
        content = api_json["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"DeepSeek malformed response: {api_json}") from exc

    parsed = _extract_json(str(content))
    if not parsed:
        raise RuntimeError("DeepSeek response JSON parse failed")
    return parsed


def _call_deepseek_with_retry(messages: list[dict[str, str]]) -> dict[str, Any]:
    retry = _get_int_env("DEEPSEEK_RETRY", 1, min_value=0)
    backoff = _get_float_env("DEEPSEEK_RETRY_BACKOFF_SEC", 1.0, min_value=0.0)
    last_error: Exception | None = None
    for attempt in range(retry + 1):
        try:
            return _call_deepseek(messages)
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= retry:
                break
            time.sleep(backoff * (attempt + 1))
    if last_error is None:
        raise RuntimeError("DeepSeek retry failed with unknown error")
    raise last_error


def _run_git(repo_path: Path, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git exited with {proc.returncode}")
    return proc.stdout


def _extract_key_logs(log_text: str) -> list[str]:
    lines = []
    for raw in log_text.splitlines():
        line = raw.strip()
        if line.startswith("- "):
            line = line[2:].strip()
        if any(marker in line for marker in _KEY_LOG_MARKERS):
            lines.append(line)
    return lines


def _read_file_at_ref(repo_path: Path, git_ref: str, rel_file: str) -> str | None:
    if not git_ref or not rel_file:
        return None
    try:
        return _run_git(repo_path, ["show", f"{git_ref}:{rel_file}"])
    except RuntimeError:
        return None


def _resolve_ref_sha(repo_path: Path, git_ref: str) -> str:
    if not git_ref:
        return ""
    try:
        return _run_git(repo_path, ["rev-parse", git_ref]).strip()
    except RuntimeError:
        return ""


def _resolve_current_checkout(repo_path: Path) -> dict[str, str]:
    info = {"ref": "", "sha": ""}
    if not repo_path.is_dir():
        return info
    try:
        info["ref"] = _run_git(repo_path, ["branch", "--show-current"]).strip()
    except RuntimeError:
        info["ref"] = ""
    try:
        info["sha"] = _run_git(repo_path, ["rev-parse", "HEAD"]).strip()
    except RuntimeError:
        info["sha"] = ""
    return info


def _read_code_context(
    repo_path: Path,
    rel_file: str,
    line_number: int | None,
    context_lines: int,
    *,
    git_ref: str = "",
) -> str:
    if not rel_file:
        return "(code context unavailable: empty file path)"
    text_content = _read_file_at_ref(repo_path, git_ref, rel_file) if git_ref else None
    if text_content is None:
        file_path = repo_path / rel_file
        if not file_path.is_file():
            return "(code context unavailable: file not found in ref or working tree)"
        text_content = file_path.read_text(encoding="utf-8", errors="replace")

    text = text_content.splitlines()
    if not text:
        return "(code context unavailable: empty file)"

    if line_number is None or line_number <= 0:
        start = 1
        end = min(len(text), context_lines * 2 + 1)
    else:
        start = max(1, line_number - context_lines)
        end = min(len(text), line_number + context_lines)

    rendered = []
    for idx in range(start, end + 1):
        marker = ">" if line_number is not None and idx == line_number else " "
        rendered.append(f"{marker}{idx:5d} | {text[idx - 1]}")
    return "\n".join(rendered)


def _extract_relevant_diff(diff_text: str, target_line: int | None, max_lines: int) -> str:
    lines = diff_text.splitlines()
    if not lines:
        return "(diff unavailable)"

    header: list[str] = []
    hunks: list[tuple[int, int, list[str]]] = []
    current_hunk_lines: list[str] = []
    current_start = 0
    current_count = 0
    in_hunk = False

    for line in lines:
        match = _HUNK_RE.match(line)
        if match:
            if in_hunk:
                hunks.append((current_start, current_count, current_hunk_lines))
            current_start = int(match.group("start"))
            current_count = int(match.group("count") or "1")
            current_hunk_lines = [line]
            in_hunk = True
            continue
        if in_hunk:
            current_hunk_lines.append(line)
        else:
            header.append(line)

    if in_hunk:
        hunks.append((current_start, current_count, current_hunk_lines))

    if not hunks:
        return "\n".join(lines[:max_lines])

    if target_line is None or target_line <= 0:
        selected = hunks[0][2]
        return "\n".join((header + selected)[:max_lines])

    best_hunk: list[str] | None = None
    best_distance: int | None = None
    for start, count, hunk_lines in hunks:
        end = start + max(count, 1) - 1
        if start <= target_line <= end:
            best_hunk = hunk_lines
            break
        distance = min(abs(target_line - start), abs(target_line - end))
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_hunk = hunk_lines

    combined = header + (best_hunk or hunks[0][2])
    return "\n".join(combined[:max_lines])


def _read_diff_hunk(
    repo_path: Path,
    base_ref: str,
    head_ref: str,
    rel_file: str,
    line_number: int | None,
    diff_context: int,
) -> str:
    if not rel_file:
        return "(diff unavailable: empty file path)"
    if not base_ref or not head_ref:
        return "(diff unavailable: base/head refs not provided)"
    try:
        diff_text = _run_git(
            repo_path,
            ["diff", "--no-color", f"--unified={diff_context}", f"{base_ref}...{head_ref}", "--", rel_file],
        )
    except RuntimeError as exc:
        return f"(diff unavailable: {exc})"
    return _extract_relevant_diff(diff_text, line_number, max_lines=diff_context * 6)


def _normalize_findings(report: dict[str, Any], max_findings: int) -> list[dict[str, Any]]:
    findings = list(report.get("findings", []))
    findings.sort(
        key=lambda item: (
            _SEVERITY_ORDER.get(str(item.get("severity", "info")).lower(), 99),
            str(item.get("file", "")),
            item.get("line") if isinstance(item.get("line"), int) else 10**9,
        )
    )
    return findings[:max_findings]


def build_payload(
    *,
    report: dict[str, Any],
    log_text: str,
    repo_path: Path,
    display_repo_path: Path | None,
    base_ref: str,
    head_ref: str,
    context_lines: int,
    diff_context: int,
    max_findings: int,
) -> dict[str, Any]:
    key_logs = _extract_key_logs(log_text)
    display_repo = display_repo_path or repo_path
    findings_all = list(report.get("findings", []))
    findings_payload = []
    for finding in _normalize_findings(report, max_findings=max_findings):
        rel_file = str(finding.get("file", ""))
        line_number = finding.get("line") if isinstance(finding.get("line"), int) else None
        findings_payload.append(
            {
                "file": rel_file,
                "line": line_number,
                "severity": str(finding.get("severity", "info")),
                "tool": str(finding.get("tool", "")),
                "rule_id": str(finding.get("rule_id", "")),
                "source": str(finding.get("source", "")),
                "category": str(finding.get("category", "")),
                "title": str(finding.get("title", "")),
                "message": str(finding.get("message", "")),
                "impact": str(finding.get("impact", "")),
                "confidence": str(finding.get("confidence", "")),
                "review_action": str(finding.get("review_action", "")),
                "evidence": finding.get("evidence", []),
                "verification_status": str(finding.get("verification_status", "")),
                "verification_notes": finding.get("verification_notes", []),
                "suggested_action": str(finding.get("suggested_action", "")),
                "in_diff": bool(finding.get("in_diff", False)),
                "code_context": _read_code_context(repo_path, rel_file, line_number, context_lines, git_ref=head_ref),
                "diff_hunk": _read_diff_hunk(repo_path, base_ref, head_ref, rel_file, line_number, diff_context),
            }
        )

    head_sha = _resolve_ref_sha(repo_path, head_ref)
    current_checkout = _resolve_current_checkout(display_repo)
    current_ref = current_checkout.get("ref", "")
    current_sha = current_checkout.get("sha", "")
    is_historical_snapshot = bool(head_sha and current_sha and head_sha != current_sha)

    return {
        "scan_meta": {
            "repo_path": str(display_repo),
            "effective_repo_path": str(repo_path),
            "base_ref": base_ref,
            "head_ref": head_ref,
            "head_sha": head_sha,
            "current_checkout_ref": current_ref,
            "current_checkout_sha": current_sha,
            "is_historical_snapshot": is_historical_snapshot,
        },
        "report_summary": report.get("summary", {}),
        "static_summary": report.get("static_summary", {}),
        "llm_review_summary": report.get("llm_review_summary", {}),
        "merged_summary": report.get("merged_summary", {}),
        "top_issues": report.get("top_issues", []),
        "key_logs": key_logs,
        "total_findings_count": len(findings_all),
        "displayed_findings_count": len(findings_payload),
        "findings": findings_payload,
    }


def _normalize_evidence(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()][:5]
    text = str(value).strip()
    return [text] if text else []


def _to_confidence_zh(value: str) -> str:
    return _CONFIDENCE_ZH.get(value.strip().lower(), value.strip() or "低")


def _local_judgement(finding: dict[str, Any]) -> tuple[str, str, str, str]:
    rule_id = str(finding.get("rule_id", ""))
    severity = str(finding.get("severity", "info")).lower()

    if rule_id == "shadowFunction":
        return (
            "建议修复",
            "高",
            "局部变量名与同类现有函数同名，容易让后续阅读和搜索产生混淆，但通常不改变运行时行为。",
            "重命名局部变量，避免与现有成员函数或外层符号重名。",
        )
    if rule_id in {"functionStatic", "constParameterReference"}:
        return (
            "可暂缓",
            "中",
            "这类告警更偏向签名或封装层面的优化建议，不直接指向行为缺陷；需要结合实现确认是否值得顺手清理。",
            "若确认无成员访问或无写操作，可在后续整理时将其改为 static 或 const&。",
        )
    if severity in {"critical", "high", "medium"}:
        return (
            "建议修复",
            "中",
            "从静态扫描等级看，这条告警具备实际风险，需要结合代码上下文尽快核实。",
            "优先补充上下文验证，并在确认后修复或加保护逻辑。",
        )
    return (
        "需要人工确认",
        "低",
        "仅凭当前静态扫描信息无法确认其是否有真实影响。",
        "由熟悉该模块的开发者结合完整调用链做一次人工确认。",
    )


def _build_cn_findings(payload: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for item in payload.get("findings", []):
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "")).strip().lower()
        review_action = str(item.get("review_action", "")).strip().lower()
        evidence = _normalize_evidence(item.get("evidence"))
        confidence_raw = str(item.get("confidence", "")).strip().lower()
        message = str(item.get("message", "")).strip()
        title = str(item.get("title", "")).strip()
        impact = str(item.get("impact", "")).strip()
        suggested_action = str(item.get("suggested_action", "")).strip()

        if source == "llm_diff_review":
            judgement = _REVIEW_ACTION_TO_JUDGEMENT.get(review_action, "需要人工确认")
            confidence = _to_confidence_zh(confidence_raw or "low")
            why = message or title or "LLM 基于 diff 和上下文识别出潜在语义风险。"
            if not impact:
                impact = "当前上下文不足以确认明确故障后果，建议结合调用链做一次人工复核。"
            fix_advice = suggested_action or "结合具体调用路径确认问题是否成立，再决定是否在本次修复。"
        else:
            judgement, confidence, why, fix_advice = _local_judgement(item)
            if not impact:
                impact = "这是低优先级代码质量或可维护性问题，通常不会直接改变运行时行为。"

        findings.append(
            {
                "file": item.get("file", ""),
                "line": item.get("line"),
                "severity": item.get("severity", "info"),
                "tool": item.get("tool", ""),
                "rule_id": item.get("rule_id", ""),
                "title": title,
                "judgement": judgement,
                "confidence": confidence,
                "why": why,
                "impact": impact,
                "fix_advice": fix_advice,
                "review_action": review_action,
                "evidence": evidence,
                "verification_status": str(item.get("verification_status", "")),
                "verification_notes": item.get("verification_notes", []),
            }
        )
    return findings


def _build_summary_payload(payload: dict[str, Any]) -> dict[str, Any]:
    findings = _build_cn_findings(payload)
    finding_summaries = []
    for item in findings[:12]:
        finding_summaries.append(
            {
                "file": item.get("file", ""),
                "line": item.get("line"),
                "severity": item.get("severity", ""),
                "tool": item.get("tool", ""),
                "rule_id": item.get("rule_id", ""),
                "title": item.get("title", ""),
                "judgement": item.get("judgement", ""),
                "impact": item.get("impact", ""),
                "review_action": item.get("review_action", ""),
                "verification_status": item.get("verification_status", ""),
                "evidence": item.get("evidence", []),
            }
        )
    return {
        "scan_meta": payload.get("scan_meta", {}),
        "report_summary": payload.get("report_summary", {}),
        "static_summary": payload.get("static_summary", {}),
        "llm_review_summary": payload.get("llm_review_summary", {}),
        "merged_summary": payload.get("merged_summary", {}),
        "top_issues": payload.get("top_issues", []),
        "key_logs": payload.get("key_logs", []),
        "findings": finding_summaries,
    }


def _build_messages(payload: dict[str, Any]) -> list[dict[str, str]]:
    system_prompt = (
        "你是资深 C/C++ 代码审查工程师。"
        "你会基于已结构化的扫描结果和关键日志，输出一份谨慎的中文摘要。"
        "不要编造未给出的代码事实。"
        "输出必须是严格 JSON。"
    )
    summary_payload = _build_summary_payload(payload)
    user_prompt = (
        "请阅读下面的输入，输出严格 JSON，对扫描结果生成中文摘要。\n"
        "JSON 顶层字段必须且只能包含：\n"
        "title(string),\n"
        "summary(object: scope, overall_risk, conclusion, tool_observations[array of string], coverage_limits[array of string]),\n"
        "next_actions(array of string).\n"
        "要求：\n"
        "1. summary.overall_risk 用：低、中、高。\n"
        "2. 只总结已提供的结构化 findings，不要新增、删除或改判具体 finding。\n"
        "3. 如果工具覆盖有缺失或上下文不足，要写进 coverage_limits。\n"
        "4. 不要复述无关日志。\n\n"
        f"input={json.dumps(summary_payload, ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _guess_overall_risk(summary: dict[str, Any]) -> str:
    if int(summary.get("critical", 0) or 0) > 0 or int(summary.get("high", 0) or 0) > 0:
        return "高"
    if int(summary.get("medium", 0) or 0) > 0:
        return "中"
    return "低"


def _local_fallback_summary(payload: dict[str, Any], reason: str) -> dict[str, Any]:
    summary = dict(payload.get("report_summary", {}))
    tool_observations = []
    coverage_limits = [f"DeepSeek 未实际调用，原因：{reason}。以下结论为本地 fallback 生成。"]
    for line in payload.get("key_logs", []):
        if "clang-tidy not found in PATH" in line:
            coverage_limits.append("clang-tidy 未执行，C++ 告警覆盖度低于完整环境。")
        if "llm_triage: disabled" in line:
            tool_observations.append("主扫描阶段未启用 LLM triage，报告结论主要来自本地规则和 cppcheck。")
        if "run_security_scanners: exit=0, findings=0" in line:
            tool_observations.append("semgrep 已执行但本次 diff 未产出安全类 finding。")
        if "collect_targets detail:" in line:
            tool_observations.append(line)
        if "run_cpp_scanners: processed" in line:
            tool_observations.append(line)
        if "normalize_findings" in line:
            tool_observations.append(line)

    return {
        "title": "代码扫描中文审查报告（本地 fallback 版）",
        "summary": {
            "scope": (
                f"仓库 {payload['scan_meta']['repo_path']}，"
                f"比较 {payload['scan_meta']['base_ref']}...{payload['scan_meta']['head_ref']} 的增量改动。"
            ),
            "overall_risk": _guess_overall_risk(summary),
            "conclusion": "本报告直接基于第一阶段结构化 findings 生成；如需更高可信度，请结合实际代码上下文复核 top issues。",
            "tool_observations": tool_observations[:8],
            "coverage_limits": coverage_limits,
        },
        "next_actions": [
            "优先复核首页列出的 top issues，确认是否与当前 head_ref 代码一致。",
            "如果要提高 C++ 覆盖度，在完整环境补齐 clang-tidy 后重新跑一次 diff 扫描。",
            "如需正式中文摘要，配置 DEEPSEEK_API_KEY 后重跑本工具。",
        ],
    }


def render_markdown(analysis: dict[str, Any], payload: dict[str, Any], generated_by: str) -> str:
    summary = analysis.get("summary", {})
    scan_meta = payload.get("scan_meta", {})
    base_ref = str(scan_meta.get("base_ref", "")).strip()
    head_ref = str(scan_meta.get("head_ref", "")).strip()
    head_sha = str(scan_meta.get("head_sha", "")).strip()
    current_ref = str(scan_meta.get("current_checkout_ref", "")).strip()
    current_sha = str(scan_meta.get("current_checkout_sha", "")).strip()
    total_findings = int(payload.get("total_findings_count", 0) or 0)
    displayed_findings = int(payload.get("displayed_findings_count", 0) or 0)
    lines = [
        f"# {analysis.get('title', '代码扫描中文报告')}",
        "",
        f"> 生成方式：{generated_by}",
        "",
        "## 范围",
        f"- {summary.get('scope', '')}",
        f"- 基线范围：`{base_ref}...{head_ref}`" + (f"（head_sha=`{head_sha}`）" if head_sha else ""),
        f"- 结论：{summary.get('conclusion', '')}",
        f"- 总体风险：{summary.get('overall_risk', '')}",
        "",
    ]

    if bool(scan_meta.get("is_historical_snapshot")):
        current_checkout_label = current_ref or "(detached)"
        current_sha_short = current_sha[:12] if current_sha else ""
        suffix = f"（当前 checkout: `{current_checkout_label}` / `{current_sha_short}`）" if current_sha_short or current_checkout_label else ""
        lines.extend(
            [
                "## 快照说明",
                f"- 本报告结论基于 `head_ref` 对应的历史快照生成，不等同于你当前工作树中的文件状态。{suffix}",
                "- 如果当前本地 checkout 不在上述 `head_ref/head_sha`，请不要直接用当前工作树代码去反驳本报告中的历史 diff 结论。",
                "",
            ]
        )

    lines.extend(
        [
        "## 扫描摘要",
        f"- 原始 summary：`{json.dumps(payload.get('report_summary', {}), ensure_ascii=False)}`",
        f"- 正文展示：前 `{displayed_findings}` 条 / 共 `{total_findings}` 条（完整结果见 JSON/SARIF 产物）",
        "",
        "## 工具观察",
        ]
    )

    tool_observations = summary.get("tool_observations", [])
    if tool_observations:
        for item in tool_observations:
            lines.append(f"- {item}")
    else:
        lines.append("- 无")

    lines.extend(["", "## 覆盖限制"])
    coverage_limits = summary.get("coverage_limits", [])
    if coverage_limits:
        for item in coverage_limits:
            lines.append(f"- {item}")
    else:
        lines.append("- 无")

    lines.extend(["", "## Findings"])
    if total_findings > displayed_findings > 0:
        lines.append(f"- 本节仅展开前 `{displayed_findings}` 条；其余结果请查看配套 JSON/SARIF。")
    findings = analysis.get("findings", [])
    if not findings:
        lines.append("- 无 finding。")
    else:
        for idx, item in enumerate(findings, 1):
            lines.extend(
                [
                    f"### {idx}. {item.get('severity', '')} | {item.get('file', '')}:{item.get('line', '')}",
                    f"- 工具：`{item.get('tool', '')}`",
                    f"- 规则：`{item.get('rule_id', '')}`",
                    f"- 标题：{item.get('title', '') or '无'}",
                    f"- 判断：{item.get('judgement', '')}",
                    f"- 置信度：{item.get('confidence', '')}",
                    f"- 审查动作：{item.get('review_action', '') or '无'}",
                    f"- 校验状态：{item.get('verification_status', '') or '未校验'}",
                    f"- 原因：{item.get('why', '')}",
                    f"- 影响：{item.get('impact', '')}",
                    f"- 建议：{item.get('fix_advice', '')}",
                    f"- 证据：{'；'.join(item.get('evidence', [])) if item.get('evidence') else '无'}",
                    f"- 校验说明：{'；'.join(item.get('verification_notes', [])) if item.get('verification_notes') else '无'}",
                    "",
                ]
            )

    lines.append("## 建议动作")
    for item in analysis.get("next_actions", []):
        lines.append(f"- {item}")

    lines.append("")
    lines.append("## 附录：关键日志")
    for item in payload.get("key_logs", []):
        lines.append(f"- {item}")

    lines.append("")
    lines.append("## 附录：命中代码上下文")
    for idx, item in enumerate(payload.get("findings", []), 1):
        lines.extend(
            [
                f"### {idx}. {item.get('file', '')}:{item.get('line', '')}",
                "",
                "```cpp",
                str(item.get("code_context", "")),
                "```",
                "",
                "```diff",
                str(item.get("diff_hunk", "")),
                "```",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, data: dict[str, Any]) -> None:
    _write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def generate_cn_report_from_content(
    *,
    report: dict[str, Any],
    log_text: str,
    repo_path: Path,
    display_repo_path: Path | None = None,
    base_ref: str,
    head_ref: str,
    out_path: Path,
    raw_out_path: Path | None = None,
    context_lines: int = 20,
    diff_context: int = 20,
    max_findings: int = 20,
    allow_local_fallback: bool = False,
) -> dict[str, Any]:
    payload = build_payload(
        report=report,
        log_text=log_text,
        repo_path=repo_path,
        display_repo_path=display_repo_path,
        base_ref=base_ref,
        head_ref=head_ref,
        context_lines=max(context_lines, 1),
        diff_context=max(diff_context, 1),
        max_findings=max(max_findings, 1),
    )

    findings = _build_cn_findings(payload)
    generated_by = "DeepSeek"
    try:
        summary_analysis = _call_deepseek_with_retry(_build_messages(payload))
    except Exception as exc:  # noqa: BLE001
        if not allow_local_fallback:
            raise
        generated_by = "LocalFallback"
        summary_analysis = _local_fallback_summary(payload, str(exc))

    analysis = {
        "title": summary_analysis.get("title", "代码扫描中文报告"),
        "summary": summary_analysis.get("summary", {}),
        "findings": findings,
        "next_actions": summary_analysis.get("next_actions", []),
    }

    markdown = render_markdown(analysis, payload, generated_by=generated_by)
    _write_text(out_path, markdown)
    effective_raw_out = raw_out_path or out_path.with_suffix(".json")
    _write_json(effective_raw_out, analysis)

    return {
        "markdown_path": str(out_path),
        "json_path": str(effective_raw_out),
        "generated_by": generated_by,
    }


def generate_cn_report_from_paths(
    *,
    report_path: Path,
    log_path: Path,
    repo_path: Path,
    base_ref: str,
    head_ref: str,
    out_path: Path,
    raw_out_path: Path | None = None,
    context_lines: int = 20,
    diff_context: int = 20,
    max_findings: int = 20,
    allow_local_fallback: bool = False,
) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    return generate_cn_report_from_content(
        report=report,
        log_text=log_text,
        repo_path=repo_path,
        display_repo_path=repo_path,
        base_ref=base_ref,
        head_ref=head_ref,
        out_path=out_path,
        raw_out_path=raw_out_path,
        context_lines=context_lines,
        diff_context=diff_context,
        max_findings=max_findings,
        allow_local_fallback=allow_local_fallback,
    )


def main(argv: list[str] | None = None) -> int:
    load_local_env()

    parser = argparse.ArgumentParser(description="Generate Chinese code scan report using DeepSeek")
    parser.add_argument("--report", required=True, help="Path to JSON report generated by code_scan_agent")
    parser.add_argument("--log", required=True, help="Path to run log generated by code_scan_agent")
    parser.add_argument("--repo", required=True, help="Absolute path to target repository")
    parser.add_argument("--base", default="", help="Base branch/ref")
    parser.add_argument("--head", default="", help="Head branch/ref")
    parser.add_argument("--out", required=True, help="Output Markdown path")
    parser.add_argument("--raw-out", default="", help="Optional output path for structured JSON analysis")
    parser.add_argument("--context-lines", type=int, default=20, help="Code context lines around each finding")
    parser.add_argument("--diff-context", type=int, default=20, help="Diff context lines when extracting hunks")
    parser.add_argument("--max-findings", type=int, default=20, help="Maximum findings to include in prompt")
    parser.add_argument(
        "--allow-local-fallback",
        action="store_true",
        help="Generate a local heuristic report when DeepSeek is unavailable",
    )
    args = parser.parse_args(argv)

    result = generate_cn_report_from_paths(
        report_path=Path(args.report).expanduser().resolve(),
        log_path=Path(args.log).expanduser().resolve(),
        repo_path=Path(args.repo).expanduser().resolve(),
        base_ref=args.base,
        head_ref=args.head,
        out_path=Path(args.out).expanduser().resolve(),
        raw_out_path=Path(args.raw_out).expanduser().resolve() if args.raw_out else None,
        context_lines=args.context_lines,
        diff_context=args.diff_context,
        max_findings=args.max_findings,
        allow_local_fallback=args.allow_local_fallback,
    )
    print(f"Markdown report written to: {result['markdown_path']}")
    print(f"Structured analysis written to: {result['json_path']}")
    print(f"Generated by: {result['generated_by']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
