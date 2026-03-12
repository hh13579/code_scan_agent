from __future__ import annotations

import re
from typing import Any


_CONTROL_FLOW_RE = re.compile(r"\b(if|else|switch|case|return|throw|catch|try)\b")
_COMPARISON_RE = re.compile(r"(>=|<=|==|!=|>|<)")
_DEFAULT_VALUE_RE = re.compile(r"\b(null|nullptr|None|false|true|0)\b|\[\]|\{\}")
_TYPE_KEYWORD_RE = re.compile(r"\b(class|interface|struct|enum|type)\b")
_SIGNATURE_HINT_RE = re.compile(
    r"^[+-]\s*(?:export\s+)?(?:async\s+)?(?:public|private|protected|static|virtual|inline|constexpr|final|override|\s)*"
    r"(?:function\s+)?[A-Za-z_~][\w:<>]*\s*\(",
    re.MULTILINE,
)
_CORE_PATH_HINTS = (
    "src/",
    "core/",
    "engine/",
    "service/",
    "dd_src/",
    "walk_src/",
    "nav_wrapper/",
)
_SEVERITY_WEIGHT = {
    "critical": 3.0,
    "high": 2.5,
    "medium": 1.5,
    "low": 0.5,
}


def _score_static_findings(
    file_path: str,
    findings: list[dict[str, Any]],
) -> tuple[float, list[str]]:
    score = 0.0
    reasons: list[str] = []
    for item in findings:
        if str(item.get("file", "")) != file_path:
            continue
        severity = str(item.get("severity", "")).lower()
        weight = _SEVERITY_WEIGHT.get(severity, 0.0)
        if weight <= 0:
            continue
        score += weight
        reason = f"static_{severity}"
        if reason not in reasons:
            reasons.append(reason)
    return score, reasons


def _count_patch_lines(patch: str) -> tuple[int, int]:
    added = 0
    deleted = 0
    for line in patch.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            deleted += 1
    return added, deleted


def rank_diff_files(
    diff_files: list[dict[str, Any]],
    *,
    triaged_findings: list[dict[str, Any]] | None = None,
    normalized_findings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    findings = list(triaged_findings or normalized_findings or [])
    ranked: list[dict[str, Any]] = []

    for item in diff_files:
        file_path = str(item.get("path", "")).strip()
        if not file_path:
            continue

        patch = str(item.get("patch", ""))
        changed_lines = list(item.get("changed_lines", []))
        score = 0.0
        reasons: list[str] = []

        if _CONTROL_FLOW_RE.search(patch):
            score += 1.8
            reasons.append("conditional_change")
        if _COMPARISON_RE.search(patch) and ("+" in patch or "-" in patch):
            score += 1.5
            reasons.append("comparison_change")
        if _DEFAULT_VALUE_RE.search(patch):
            score += 1.2
            reasons.append("default_value_change")
        if _TYPE_KEYWORD_RE.search(patch):
            score += 1.0
            reasons.append("type_shape_change")
        if _SIGNATURE_HINT_RE.search(patch):
            score += 1.4
            reasons.append("signature_change")

        added, deleted = _count_patch_lines(patch)
        if deleted > added:
            score += 0.8
            reasons.append("deletion_heavy")
        elif added > 0:
            score += min(added / 40.0, 0.8)

        if changed_lines:
            score += min(len(changed_lines) / 25.0, 0.8)

        if any(file_path.startswith(prefix) for prefix in _CORE_PATH_HINTS):
            score += 0.7
            reasons.append("core_file")

        static_score, static_reasons = _score_static_findings(file_path, findings)
        if static_score > 0:
            score += static_score
            reasons.extend(static_reasons)

        ranked.append(
            {
                "path": file_path,
                "language": str(item.get("language", "")),
                "risk_score": round(score, 2),
                "reasons": reasons,
            }
        )

    ranked.sort(key=lambda item: (-float(item.get("risk_score", 0.0)), str(item.get("path", ""))))
    return ranked
