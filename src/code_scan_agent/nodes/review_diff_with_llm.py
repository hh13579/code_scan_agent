from __future__ import annotations

import json
import os
import re
import subprocess
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


def _patch_header(patch: str) -> str:
    header_lines: list[str] = []
    for line in patch.splitlines():
        if line.startswith("@@"):
            break
        header_lines.append(line)
    return "\n".join(header_lines).strip()


def _build_changed_file_label(item: dict[str, Any]) -> str:
    file_path = str(item.get("path", "")).strip()
    old_path = str(item.get("old_path", "")).strip()
    status = str(item.get("status", "")).strip().upper()
    if status in {"R", "C"} and old_path and old_path != file_path:
        return f"{status} {old_path} -> {file_path}"
    if status:
        return f"{status} {file_path}"
    return file_path


def _build_diff_patch_text(item: dict[str, Any], hunk_text: str, max_patch_chars: int) -> str:
    patch = str(item.get("patch", ""))
    status = str(item.get("status", "")).strip().upper()
    header = _patch_header(patch)
    body = hunk_text.strip()
    if status in {"R", "C"} and patch.strip():
        body = patch.strip()
    elif header and body:
        body = f"{header}\n{body}"
    elif not body:
        body = patch.strip()
    return _truncate_text(body, max_patch_chars)


def _is_move_like_status(status: str) -> bool:
    normalized = status.strip().upper()
    return normalized in {"R", "C"}


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
        old_path = str(item.get("old_path", ""))
        status = str(item.get("status", "")).strip().upper()
        changed_lines = list(item.get("changed_lines", []))
        hunks = [str(hunk) for hunk in item.get("hunks", []) if str(hunk).strip()]
        changed_files.append(_build_changed_file_label(item))

        if _is_move_like_status(status) and str(item.get("patch", "")).strip():
            if hunk_budget <= 0:
                break
            diff_blocks.append(
                {
                    "file": file_path,
                    "old_path": old_path,
                    "status": status,
                    "language": str(item.get("language", "")),
                    "block_id": f"{file_path}#patch",
                    "changed_lines": changed_lines,
                    "patch": _build_diff_patch_text(item, "", max_patch_chars),
                }
            )
            hunk_budget -= 1
        elif hunks:
            for index, hunk in enumerate(hunks, start=1):
                if hunk_budget <= 0:
                    break
                diff_blocks.append(
                    {
                        "file": file_path,
                        "old_path": old_path,
                        "status": status,
                        "language": str(item.get("language", "")),
                        "block_id": f"{file_path}#{index}",
                        "changed_lines": changed_lines,
                        "patch": _build_diff_patch_text(item, hunk, max_patch_chars),
                    }
                )
                hunk_budget -= 1
        elif str(item.get("patch", "")).strip():
            if hunk_budget <= 0:
                break
            diff_blocks.append(
                {
                    "file": file_path,
                    "old_path": old_path,
                    "status": status,
                    "language": str(item.get("language", "")),
                    "block_id": f"{file_path}#patch",
                    "changed_lines": changed_lines,
                    "patch": _build_diff_patch_text(item, str(item.get("patch", "")), max_patch_chars),
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


def _finding_text(finding: dict[str, Any]) -> str:
    parts = [
        _norm_str(finding.get("title")),
        _norm_str(finding.get("message")),
        _norm_str(finding.get("impact")),
        _norm_str(finding.get("suggested_action")),
    ]
    parts.extend(_normalize_evidence(finding.get("evidence")))
    return "\n".join(part for part in parts if part)


def _is_diff_only_evidence(evidence: list[str]) -> bool:
    if not evidence:
        return False
    diff_markers = ("diff 显示", "diff block", "代码显示", "代码：", "代码返回", "代码中", "diff shows", "code shows")
    context_markers = ("上下文", "调用方", "调用点", "调用处", "测试", "context", "call site", "caller", "test")
    has_diff_marker = False
    for item in evidence:
        lowered = item.lower()
        if any(marker in lowered for marker in diff_markers):
            has_diff_marker = True
        if any(marker in lowered for marker in context_markers):
            return False
    return has_diff_marker


def _candidate_identifiers(text: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for token in re.findall(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b", text):
        if token in seen:
            continue
        if token.lower() in {"diff", "code", "context", "return", "front", "back", "none", "high", "medium", "low"}:
            continue
        seen.add(token)
        out.append(token)
    return out


def _repo_contains_identifier(
    repo_root: Path,
    identifier: str,
    *,
    exclude_files: set[str],
    cache: dict[str, bool],
) -> bool:
    cached = cache.get(identifier)
    if cached is not None:
        return cached

    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "grep",
                "-n",
                "-F",
                identifier,
                "--",
                "*.h",
                "*.hpp",
                "*.hh",
                "*.cpp",
                "*.cc",
                "*.cxx",
                "*.java",
                "*.ts",
                "*.tsx",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except Exception:  # noqa: BLE001
        cache[identifier] = False
        return False

    if proc.returncode not in {0, 1}:
        cache[identifier] = False
        return False

    for raw in proc.stdout.splitlines():
        path = raw.split(":", 1)[0].strip().replace("\\", "/").lstrip("./")
        if path and path not in exclude_files:
            cache[identifier] = True
            return True

    cache[identifier] = False
    return False


def _related_context_blocks(
    review_context_blocks: list[dict[str, Any]],
    *,
    file_path: str,
) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    for item in review_context_blocks:
        subject_file = str(item.get("subject_file", "")).strip() or str(item.get("file", "")).strip()
        if subject_file == file_path:
            related.append(item)
    return related


def _has_guarded_call_context(finding: Finding, related_context_blocks: list[dict[str, Any]]) -> bool:
    finding_text = _finding_text(finding)
    lowered = finding_text.lower()
    if not any(token in lowered for token in ("empty", "front()", "back()", "空检查", "空容器", "未定义行为", "段错误")):
        return False

    identifiers = _candidate_identifiers(finding_text)
    if not identifiers:
        return False

    for block in related_context_blocks:
        if str(block.get("kind", "")) != "call_site":
            continue
        content = str(block.get("content", ""))
        content_lower = content.lower()
        if "empty()" not in content_lower or "return" not in content_lower:
            continue
        if any(f"{identifier}(" in content for identifier in identifiers):
            return True
    return False


def _has_relocation_signal(
    finding: Finding,
    *,
    file_path: str,
    diff_file_map: dict[str, dict[str, Any]],
    review_context_blocks: list[dict[str, Any]],
) -> bool:
    finding_text = _finding_text(finding)
    identifiers = _candidate_identifiers(finding_text)
    if not identifiers:
        return False

    for item in review_context_blocks:
        subject_file = str(item.get("subject_file", "")).strip() or str(item.get("file", "")).strip()
        source_file = str(item.get("file", "")).strip()
        if subject_file == file_path:
            continue
        content = str(item.get("content", ""))
        if any(identifier in content or identifier in source_file for identifier in identifiers):
            return True

    for other_path, diff_item in diff_file_map.items():
        if other_path == file_path:
            continue
        patch = str(diff_item.get("patch", ""))
        if any(identifier in patch or identifier in other_path for identifier in identifiers):
            return True
    return False


def _is_speculative_callsite_gap(finding: Finding) -> bool:
    lowered = _finding_text(finding).lower()
    markers = (
        "调用点",
        "调用处",
        "调用链",
        "未更新",
        "未同步",
        "向后兼容",
        "默认值",
        "call site",
        "callsite",
        "caller",
        "default value",
        "backward compatible",
    )
    return any(marker in lowered for marker in markers)


def _is_speculative_finding(finding: Finding) -> bool:
    lowered = _finding_text(finding).lower()
    markers = ("可能", "如果", "需确认", "might", "may ", "could", "unclear", "assum", "speculat")
    return any(marker in lowered for marker in markers)


def _needs_helper_semantic_context(finding: Finding) -> bool:
    lowered = _finding_text(finding).lower()
    markers = (
        "未提供",
        "未展开",
        "语义",
        "不匹配预期",
        "参数不正确",
        "expected type",
        "expected semantics",
        "implementation not provided",
        "helper",
    )
    return any(marker in lowered for marker in markers)


def _downgrade_finding(
    finding: Finding,
    *,
    message: str,
    impact: str,
    suggested_action: str,
) -> Finding:
    downgraded = dict(finding)
    downgraded["severity"] = "low"  # type: ignore[typeddict-item]
    downgraded["review_action"] = "follow_up"  # type: ignore[typeddict-item]
    downgraded["confidence"] = "low"
    downgraded["message"] = message
    downgraded["impact"] = impact
    downgraded["suggested_action"] = suggested_action
    return downgraded


def _stabilize_llm_finding(
    finding: Finding,
    *,
    repo_root: Path,
    diff_item: dict[str, Any] | None,
    diff_file_map: dict[str, dict[str, Any]],
    review_context_blocks: list[dict[str, Any]],
    repo_symbol_cache: dict[str, bool],
) -> Finding:
    file_path = str(finding.get("file", "")).strip()
    status = str((diff_item or {}).get("status", "")).strip().upper()
    evidence = _normalize_evidence(finding.get("evidence"))
    related_context = _related_context_blocks(review_context_blocks, file_path=file_path)

    if (
        _is_move_like_status(status)
        and str(finding.get("severity", "")).lower() in {"high", "medium"}
    ):
        if _has_guarded_call_context(finding, related_context):
            return _downgrade_finding(
                finding,
                message="当前 diff 移除了内部防御性检查，但已提供的调用方上下文显示存在前置空判断；更像是健壮性收缩而不是已证实的崩溃路径。",
                impact="如果该函数未来出现新的未受保护入口，才可能演变成健壮性问题；基于当前上下文，不足以判定为明确行为回归。",
                suggested_action="确认该函数是否只通过现有受保护调用路径进入；如果是，可按低优先级决定是否保留内部防御。",
            )
        if _has_relocation_signal(
            finding,
            file_path=file_path,
            diff_file_map=diff_file_map,
            review_context_blocks=review_context_blocks,
        ):
            return _downgrade_finding(
                finding,
                message="当前 diff 更像是重构迁移：旧文件内的 helper/判定逻辑被移走，但同次变更里仍能看到相关实现或调用痕迹。",
                impact="这更可能是实现位置调整带来的可读性成本，而不是已证实的功能缺失；是否存在行为偏差仍需结合迁移后的调用链确认。",
                suggested_action="优先核对迁移后的实现是否保持等价，再决定是否需要补回防御逻辑或注释说明。",
            )

    if (
        str(finding.get("severity", "")).lower() in {"high", "medium"}
        and _is_diff_only_evidence(evidence)
        and _is_speculative_callsite_gap(finding)
    ):
        call_site_blocks = [item for item in related_context if str(item.get("kind", "")) == "call_site"]
        if not call_site_blocks or all(str(item.get("file", "")).strip() == file_path for item in call_site_blocks):
            return _downgrade_finding(
                finding,
                message="当前只看到签名或局部调用改动，没有拿到未同步调用方的直接证据，这更像一次需要补充核对的兼容性提醒。",
                impact="若仓库中确有遗漏更新的调用点，才会形成真实问题；基于当前证据，不足以下结论为本次必须修复的行为回归。",
                suggested_action="补查该符号的其余调用点或仓库内引用，再决定是否需要回滚接口变更或补齐适配。",
            )

    if (
        str(finding.get("severity", "")).lower() in {"high", "medium"}
        and _is_diff_only_evidence(evidence)
        and _is_speculative_finding(finding)
    ):
        return _downgrade_finding(
            finding,
            message="当前判断主要来自 diff 片段推断，缺少能够直接证明故障路径的上下文证据，更适合作为后续复核项而不是高优先级缺陷。",
            impact="如果后续补充调用链、边界样例或运行验证后仍能复现，再提升优先级会更稳妥；基于当前证据，不足以直接判定为本次必须修复的问题。",
            suggested_action="结合对应函数的完整实现和实际调用路径做一次人工复核；只有在能明确构造失败路径时再升级为 should_fix 或 block。",
        )

    if (
        str(finding.get("severity", "")).lower() in {"high", "medium"}
        and _needs_helper_semantic_context(finding)
    ):
        exclude_files = set(diff_file_map)
        identifiers = [token for token in _candidate_identifiers(_finding_text(finding)) if any(ch.isupper() for ch in token)]
        if any(
            _repo_contains_identifier(
                repo_root,
                identifier,
                exclude_files=exclude_files,
                cache=repo_symbol_cache,
            )
            for identifier in identifiers
        ):
            return _downgrade_finding(
                finding,
                message="当前结论依赖 helper/工具函数的语义推断，但仓库内已存在相关符号定义；在没有把该定义上下文一并纳入审查前，不宜把它保留为中高风险结论。",
                impact="如果后续补充 helper 定义后仍能证明参数或语义不匹配，再提升优先级会更稳妥；基于当前证据，更适合作为低优先级复核项。",
                suggested_action="补充对应 helper 的定义与调用语义后再复核；若 helper 定义本身已明确支持当前调用，可直接关闭该条。",
            )

    return finding


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
    diff_file_map: dict[str, dict[str, Any]],
    review_context_blocks: list[dict[str, Any]],
) -> tuple[list[Finding], int]:
    findings_raw = parsed.get("findings", [])
    if not isinstance(findings_raw, list):
        return [], 0

    findings: list[Finding] = []
    dropped = 0
    repo_symbol_cache: dict[str, bool] = {}
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
        findings.append(
            _stabilize_llm_finding(
                normalized,
                repo_root=repo_root,
                diff_item=diff_file_map.get(file_path),
                diff_file_map=diff_file_map,
                review_context_blocks=review_context_blocks,
                repo_symbol_cache=repo_symbol_cache,
            )
        )
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
    diff_file_map = {str(item.get("path", "")): item for item in diff_files if item.get("path")}
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

    findings, dropped = _normalize_review_findings(
        parsed,
        repo_root,
        diff_paths,
        diff_file_map,
        extra_context_blocks,
    )
    state["llm_review_findings"] = findings
    state.setdefault("logs", []).append(
        "review_diff_with_llm: "
        f"reviewed_files={len(changed_files)}, diff_blocks={len(diff_blocks)}, findings={len(findings)}, dropped={dropped}"
    )
    return state
