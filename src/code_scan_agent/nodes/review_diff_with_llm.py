from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from code_scan_agent.graph.state import Finding, GraphState
from code_scan_agent.prompts.diff_review_prompt import build_diff_review_messages
from code_scan_agent.tools.deepseek_cn_report import _call_deepseek_with_retry


_VALID_SEVERITY = {"critical", "high", "medium", "low", "info"}
_VALID_CONFIDENCE = {"high", "medium", "low"}


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
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    changed_files: list[dict[str, Any]] = []
    diff_blocks: list[dict[str, Any]] = []
    hunk_budget = max_hunks

    for item in diff_files[:max_files]:
        changed_lines = list(item.get("changed_lines", []))
        hunks = [str(hunk) for hunk in item.get("hunks", []) if str(hunk).strip()]
        changed_files.append(
            {
                "path": str(item.get("path", "")),
                "old_path": str(item.get("old_path", "")),
                "status": str(item.get("status", "")),
                "language": str(item.get("language", "")),
                "changed_line_count": len(changed_lines),
                "hunk_count": len(hunks),
            }
        )

        if hunks:
            for index, hunk in enumerate(hunks, start=1):
                if hunk_budget <= 0:
                    break
                diff_blocks.append(
                    {
                        "path": str(item.get("path", "")),
                        "status": str(item.get("status", "")),
                        "language": str(item.get("language", "")),
                        "block_id": f"{item.get('path', '')}#{index}",
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
                    "path": str(item.get("path", "")),
                    "status": str(item.get("status", "")),
                    "language": str(item.get("language", "")),
                    "block_id": f"{item.get('path', '')}#patch",
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


def _normalize_line(value: object) -> int | None:
    try:
        line = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return line if line > 0 else None


def _normalize_review_findings(parsed: dict[str, Any], repo_root: Path) -> list[Finding]:
    findings_raw = parsed.get("findings", [])
    if not isinstance(findings_raw, list):
        return []

    findings: list[Finding] = []
    for item in findings_raw:
        if not isinstance(item, dict):
            continue

        severity = str(item.get("severity", "medium")).strip().lower()
        if severity not in _VALID_SEVERITY:
            severity = "medium"

        confidence = str(item.get("confidence", "medium")).strip().lower()
        if confidence not in _VALID_CONFIDENCE:
            confidence = "medium"

        file_path = str(item.get("file", "")).replace("\\", "/").lstrip("./")
        if file_path:
            try:
                absolute = Path(file_path)
                if absolute.is_absolute():
                    file_path = str(absolute.resolve().relative_to(repo_root.resolve())).replace("\\", "/")
            except Exception:
                file_path = file_path.replace("\\", "/")

        title = str(item.get("title", "")).strip()
        message = str(item.get("message", "")).strip() or title
        if not message:
            continue

        finding: Finding = {
            "tool": "llm_diff_review",
            "source": "llm_diff_review",
            "rule_id": "semantic-review",
            "category": str(item.get("category", "semantic-review")).strip() or "semantic-review",
            "severity": severity,  # type: ignore[typeddict-item]
            "file": file_path,
            "line": _normalize_line(item.get("line")),
            "column": None,
            "title": title or "LLM diff review finding",
            "message": message,
            "snippet": None,
            "confidence": confidence,
            "autofix_available": False,
            "in_diff": True,
            "evidence": str(item.get("evidence", "")).strip(),
            "suggested_action": str(item.get("suggested_action", "")).strip(),
        }
        findings.append(finding)
    return findings


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

    findings = _normalize_review_findings(parsed, repo_root)
    state["llm_review_findings"] = findings
    state.setdefault("logs", []).append(
        f"review_diff_with_llm: reviewed_files={len(changed_files)}, diff_blocks={len(diff_blocks)}, findings={len(findings)}"
    )
    return state
