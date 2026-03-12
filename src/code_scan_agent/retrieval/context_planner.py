from __future__ import annotations

import re
from typing import Any


_TYPE_KEYWORD_RE = re.compile(r"\b(class|interface|struct|enum|type)\b")
_CONTROL_FLOW_RE = re.compile(r"\b(if|else|switch|throw|catch|try|null|nullptr|None|false|true|0)\b")
_API_SURFACE_RE = re.compile(r"\b(export|public|protected|virtual|override|interface|api|service)\b")
_SIGNATURE_RE = re.compile(
    r"^[+-]\s*(?:export\s+)?(?:async\s+)?(?:public|private|protected|static|virtual|inline|final|\s)*"
    r"(?:function\s+)?[A-Za-z_~][\w:<>]*\s*\(",
    re.MULTILINE,
)


def plan_review_context(
    diff_file: dict[str, Any],
    *,
    risk_score: float | None = None,
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    patch = str(diff_file.get("patch", ""))
    needs: list[str] = []
    reason_list = list(reasons or [])

    if diff_file.get("changed_lines"):
        needs.append("function_context")
    if _TYPE_KEYWORD_RE.search(patch) or "type_shape_change" in reason_list:
        needs.append("type_definition")
    if (
        _API_SURFACE_RE.search(patch)
        or _SIGNATURE_RE.search(patch)
        or "signature_change" in reason_list
        or "conditional_change" in reason_list
        or "default_value_change" in reason_list
        or float(risk_score or 0.0) >= 2.0
    ):
        needs.append("call_sites")
    if _CONTROL_FLOW_RE.search(patch) or "conditional_change" in reason_list or "default_value_change" in reason_list:
        needs.append("related_tests")

    if not needs:
        needs.append("function_context")

    ordered_unique_needs: list[str] = []
    for item in needs:
        if item not in ordered_unique_needs:
            ordered_unique_needs.append(item)

    return {
        "file": str(diff_file.get("path", "")),
        "language": str(diff_file.get("language", "")),
        "needs": ordered_unique_needs,
        "risk_score": float(risk_score or 0.0),
        "reasons": reason_list,
    }
