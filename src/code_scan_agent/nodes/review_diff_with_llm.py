from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from code_scan_agent.graph.state import Finding, GraphState
from code_scan_agent.prompts.diff_review_prompt import build_diff_review_messages
from code_scan_agent.tools.deepseek_cn_report import _call_deepseek_with_retry


_ALLOWED_SEVERITIES = {"high", "medium", "low"}
_ALLOWED_REVIEW_ACTIONS = {"block", "should_fix", "follow_up"}
_ALLOWED_CONFIDENCE = {"low", "medium", "high"}
_ALLOWED_CATEGORIES = {
    "logic_regression",
    "boundary_condition",
    "contract_mismatch",
    "exception_handling",
    "state_consistency",
    "concurrency",
    "config_behavior_change",
    "partial_refactor",
    "other",
}


def _append_error(state: GraphState, message: str) -> None:
    bucket = state.get("errors")
    if not isinstance(bucket, list):
        bucket = []
        state["errors"] = bucket
    bucket.append(message)


def _get_int_env(name: str, default: int, min_value: int = 0) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(value, min_value)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    head = max_chars // 2
    tail = max_chars - head - 32
    return f"{text[:head]}\n... truncated {omitted} chars ...\n{text[-max(tail, 0):]}"


def _extract_json_text(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_+-]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {}
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


def _is_explicitly_disabled(request: dict[str, object]) -> bool:
    enabled = request.get("enable_llm_triage")
    if isinstance(enabled, bool) and not enabled:
        return True
    review_enabled = request.get("enable_llm_diff_review")
    return isinstance(review_enabled, bool) and not review_enabled


def _select_diff_blocks(
    diff_files: list[dict[str, Any]],
    *,
    max_files: int,
    max_hunks: int,
    max_patch_chars: int,
) -> tuple[list[str], list[dict[str, Any]]]:
    changed_files: list[str] = []
    diff_blocks: list[dict[str, Any]] = []
    hunk_budget = max_hunks

    for item in diff_files[:max_files]:
        file_path = str(item.get("path", ""))
        if not file_path:
            continue
        changed_lines = list(item.get("changed_lines", []))
        hunks = [str(hunk) for hunk in item.get("hunks", []) if str(hunk).strip()]
        changed_files.append(file_path)

        if hunks:
            for index, hunk in enumerate(hunks, start=1):
                if hunk_budget <= 0:
                    break
                diff_blocks.append(
                    {
                        "file": file_path,
                        "status": str(item.get("status", "")),
                        "language": str(item.get("language", "")),
                        "block_id": f"{file_path}#{index}",
                        "changed_lines": changed_lines,
                        "patch": _truncate_text(hunk, max_patch_chars),
                    }
                )
                hunk_budget -= 1
        elif str(item.get("patch", "")).strip():
            if hunk_budget <= 0:
                break
            diff_blocks.append(
                {
                    "file": file_path,
                    "status": str(item.get("status", "")),
                    "language": str(item.get("language", "")),
                    "block_id": f"{file_path}#patch",
                    "changed_lines": changed_lines,
                    "patch": _truncate_text(str(item.get("patch", "")), max_patch_chars),
                }
            )
            hunk_budget -= 1

        if hunk_budget <= 0:
            break

    return changed_files, diff_blocks


def _select_static_findings(
    findings: list[dict[str, Any]],
    diff_paths: set[str],
    *,
    max_items: int,
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for item in findings:
        file_path = str(item.get("file", ""))
        if file_path and file_path not in diff_paths:
            continue
        selected.append(
            {
                "file": file_path,
                "line": item.get("line"),
                "severity": str(item.get("severity", "info")),
                "category": str(item.get("category", "")),
                "tool": str(item.get("tool", "")),
                "rule_id": str(item.get("rule_id", "")),
                "message": str(item.get("message", ""))[:400],
            }
        )
        if len(selected) >= max_items:
            break
    return selected


def _call_llm_diff_review(messages: list[dict[str, str]], state: GraphState) -> str:
    result = _call_deepseek_with_retry(messages)
    return json.dumps(result, ensure_ascii=False)


def _norm_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _norm_line(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        line = int(value)
        return line if line > 0 else None
    except Exception:
        return None


def _infer_language_from_file(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".cpp", ".cc", ".cxx", ".hpp", ".h"}:
        return "cpp"
    if suffix == ".java":
        return "java"
    if suffix in {".ts", ".tsx"}:
        return "ts"
    return ""


def _norm_severity(value: Any) -> str:
    severity = _norm_str(value).lower()
    if severity in _ALLOWED_SEVERITIES:
        return severity
    return "low"


def _norm_review_action(value: Any, severity: str) -> str:
    action = _norm_str(value).lower()
    if action in _ALLOWED_REVIEW_ACTIONS:
        return action
    if severity == "high":
        return "should_fix"
    return "follow_up"


def _norm_confidence(value: Any, severity: str) -> str:
    confidence = _norm_str(value).lower()
    if confidence in _ALLOWED_CONFIDENCE:
        return confidence
    if severity == "high":
        return "medium"
    return "low"


def _norm_category(value: Any) -> str:
    category = _norm_str(value)
    if category in _ALLOWED_CATEGORIES:
        return category
    return "other"


def _default_title(message: str, category: str) -> str:
    if message:
        short = message.replace("\n", " ").strip()
        return short[:60] + ("..." if len(short) > 60 else "")
    if category and category != "other":
        return category.replace("_", " ")
    return "Potential semantic issue"


def _normalize_evidence(value: Any) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            text = _norm_str(item)
            if text:
                out.append(text)
        return out[:5]
    text = _norm_str(value)
    return [text] if text else []


def _normalize_llm_review_finding(raw: dict[str, Any]) -> Finding:
    file_path = _norm_str(raw.get("file"))
    line = _norm_line(raw.get("line"))

    severity = _norm_severity(raw.get("severity"))
    review_action = _norm_review_action(raw.get("review_action"), severity)
    confidence = _norm_confidence(raw.get("confidence"), severity)
    category = _norm_category(raw.get("category"))

    message = _norm_str(raw.get("message"))
    impact = _norm_str(raw.get("impact"))
    title = _norm_str(raw.get("title")) or _default_title(message, category)
    suggested_action = _norm_str(raw.get("suggested_action"))
    evidence = _normalize_evidence(raw.get("evidence"))
    language = _norm_str(raw.get("language")) or _infer_language_from_file(file_path)

    if not evidence and confidence == "high":
        confidence = "medium"
    elif not evidence and confidence == "medium":
        confidence = "low"

    if not impact:
        if severity == "high":
            impact = "该改动可能引入行为回归或稳定性风险，建议结合具体调用路径进一步确认。"
        elif severity == "medium":
            impact = "该改动可能影响局部行为正确性，建议在相关路径上补充验证。"
        else:
            impact = "该改动存在一定语义风险，但当前证据不足以判断为明确错误。"

    if not message:
        message = title or impact

    return {
        "language": language,  # type: ignore[typeddict-item]
        "tool": "llm_diff_review",
        "source": "llm_diff_review",
        "rule_id": "semantic-review",
        "category": category,
        "severity": severity,  # type: ignore[typeddict-item]
        "file": file_path,
        "line": line,
        "column": None,
        "title": title,
        "message": message,
        "impact": impact,
        "snippet": None,
        "confidence": confidence,
        "review_action": review_action,  # type: ignore[typeddict-item]
        "autofix_available": False,
        "in_diff": True,
        "evidence": evidence,
        "suggested_action": suggested_action,
    }


def _normalize_review_findings(
    parsed: dict[str, Any],
    repo_root: Path,
    diff_paths: set[str],
) -> tuple[list[Finding], int]:
    findings_raw = parsed.get("findings", [])
    if not isinstance(findings_raw, list):
        return [], 0

    findings: list[Finding] = []
    dropped = 0
    for item in findings_raw:
        if not isinstance(item, dict):
            dropped += 1
            continue

        normalized = _normalize_llm_review_finding(item)
        file_path = str(normalized.get("file", "")).replace("\\", "/").lstrip("./")
        if file_path:
            try:
                absolute = Path(file_path)
                if absolute.is_absolute():
                    file_path = str(absolute.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
            except Exception:
                file_path = file_path.replace("\\", "/")
        if not file_path or file_path not in diff_paths:
            dropped += 1
            continue
        normalized["file"] = file_path
        findings.append(normalized)
    return findings, dropped


def review_diff_with_llm(state: GraphState) -> GraphState:
    request = state.get("request", {})
    if str(request.get("mode", "full")).strip().lower() != "diff":
        state["llm_review_findings"] = []
        state.setdefault("logs", []).append("review_diff_with_llm: skipped (mode != diff)")
        return state

    if _is_explicitly_disabled(request):
        state["llm_review_findings"] = []
        state.setdefault("logs", []).append("review_diff_with_llm: skipped (--no-llm)")
        return state

    diff_files = list(state.get("diff_files", []))
    if not diff_files:
        state["llm_review_findings"] = []
        state.setdefault("logs", []).append("review_diff_with_llm: skipped (no diff_files)")
        return state

    repo_profile = state.get("repo_profile", {})
    repo_root = Path(str(repo_profile.get("repo_path") or request.get("repo_path") or ".")).resolve()
    repo_name = repo_root.name
    base_ref = str(request.get("diff_base_ref") or request.get("base_ref") or "").strip()
    head_ref = str(request.get("diff_head_ref") or request.get("head_ref") or "HEAD").strip() or "HEAD"

    max_files = _get_int_env("LLM_DIFF_REVIEW_MAX_FILES", 12, min_value=1)
    max_hunks = _get_int_env("LLM_DIFF_REVIEW_MAX_HUNKS", 24, min_value=1)
    max_patch_chars = _get_int_env("LLM_DIFF_REVIEW_MAX_PATCH_CHARS", 4000, min_value=200)
    max_static_findings = _get_int_env("LLM_DIFF_REVIEW_MAX_STATIC_FINDINGS", 20, min_value=0)
    max_findings = _get_int_env("LLM_DIFF_REVIEW_MAX_FINDINGS", 12, min_value=1)

    changed_files, diff_blocks = _select_diff_blocks(
        diff_files,
        max_files=max_files,
        max_hunks=max_hunks,
        max_patch_chars=max_patch_chars,
    )
    if not diff_blocks:
        state["llm_review_findings"] = []
        state.setdefault("logs", []).append("review_diff_with_llm: skipped (no diff blocks)")
        return state

    static_findings = list(state.get("triaged_findings") or state.get("normalized_findings") or [])
    diff_paths = {str(item.get("path", "")) for item in diff_files if item.get("path")}
    extra_context_blocks = list(state.get("review_context_blocks", []))
    messages = build_diff_review_messages(
        repo_name=repo_name,
        base_ref=base_ref,
        head_ref=head_ref,
        changed_files=changed_files,
        diff_blocks=diff_blocks,
        static_findings=_select_static_findings(
            static_findings,
            diff_paths,
            max_items=max_static_findings,
        ),
        extra_context_blocks=extra_context_blocks,
        max_findings=max_findings,
    )

    try:
        raw_text = _call_llm_diff_review(messages, state)
    except Exception as e:  # noqa: BLE001
        state["llm_review_findings"] = []
        state.setdefault("logs", []).append(
            f"review_diff_with_llm: fallback_empty, diff_blocks={len(diff_blocks)}, error_type={type(e).__name__}"
        )
        _append_error(
            state,
            f"review_diff_with_llm: LLM request failed, fallback to empty findings: {type(e).__name__}: {e}",
        )
        return state

    parsed = _extract_json_text(raw_text)
    if not parsed:
        state["llm_review_findings"] = []
        state.setdefault("logs", []).append(
            f"review_diff_with_llm: parse_failed, diff_blocks={len(diff_blocks)}"
        )
        _append_error(state, "review_diff_with_llm: response JSON parse failed")
        return state

    findings, dropped = _normalize_review_findings(parsed, repo_root, diff_paths)
    state["llm_review_findings"] = findings
    state.setdefault("logs", []).append(
        "review_diff_with_llm: "
        f"reviewed_files={len(changed_files)}, diff_blocks={len(diff_blocks)}, findings={len(findings)}, dropped={dropped}"
    )
    return state
