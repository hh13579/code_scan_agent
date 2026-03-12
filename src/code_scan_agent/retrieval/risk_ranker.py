from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from code_scan_agent.retrieval.language.common import guess_symbols_from_patch, normalize_path
from code_scan_agent.retrieval.specs import BUG_CLASS_SPECS, RetrievalHints, TriggerSignal


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
_STATE_TOKEN_RE = re.compile(r"\b(last|current|prev|previous|cache|cached|state|status|flag|dirty|active)\b", re.IGNORECASE)
_CLEANUP_TOKEN_RE = re.compile(r"\b(save|release|pool|clear|destroy|reset|cleanup|free|delete|close)\b", re.IGNORECASE)
_API_FAMILY_RE = re.compile(r"\b([A-Z]+_Set|set|get|update|create|build|begin|end)[A-Za-z_0-9]*\b")
_IDENTIFIER_RE = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{2,}\b")


def _add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


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
        _add_reason(reasons, reason)
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


def _extract_path_terms(file_path: str) -> tuple[str, ...]:
    path = Path(file_path)
    ordered: list[str] = []
    for part in path.parts[-3:]:
        normalized = str(part).strip()
        if normalized and normalized not in ordered:
            ordered.append(normalized)
    stem = path.stem
    if stem and stem not in ordered:
        ordered.append(stem)
    return tuple(ordered)


def _extract_state_terms(patch: str) -> tuple[str, ...]:
    ordered: list[str] = []
    for match in _STATE_TOKEN_RE.finditer(patch):
        token = match.group(1)
        if token not in ordered:
            ordered.append(token)
    return tuple(ordered)


def _extract_cleanup_terms(patch: str) -> tuple[str, ...]:
    ordered: list[str] = []
    for match in _CLEANUP_TOKEN_RE.finditer(patch):
        token = match.group(1)
        if token not in ordered:
            ordered.append(token)
    return tuple(ordered)


def _extract_api_families(symbols: list[str], patch: str) -> tuple[str, ...]:
    ordered: list[str] = []
    for symbol in symbols:
        if "_" in symbol:
            match = re.match(r"^([A-Z]+_[A-Z][a-z]+)", symbol)
            prefix = match.group(1) if match else "_".join(symbol.split("_")[:2])
        else:
            match = re.match(r"(set|get|update|create|build|begin|end)", symbol)
            prefix = match.group(1) if match else ""
        if prefix and prefix not in ordered:
            ordered.append(prefix)
    for match in _API_FAMILY_RE.finditer(patch):
        prefix = match.group(1)
        if prefix and prefix not in ordered:
            ordered.append(prefix)
    return tuple(ordered)


def _extract_identifiers(patch: str, *, max_items: int = 16) -> tuple[str, ...]:
    ordered: list[str] = []
    for token in _IDENTIFIER_RE.findall(patch):
        if token.lower() in {"return", "false", "true", "null", "nullptr", "case", "break"}:
            continue
        if token not in ordered:
            ordered.append(token)
        if len(ordered) >= max_items:
            break
    return tuple(ordered)


def _signal_matches(signal: TriggerSignal, patch: str) -> bool:
    return any(re.search(pattern, patch, re.IGNORECASE | re.MULTILINE) for pattern in signal.patterns)


def _build_class_hints(
    file_path: str,
    patch: str,
    *,
    symbols: list[str],
    reasons: list[str],
    spec_hints: RetrievalHints,
) -> RetrievalHints:
    hint_keywords = tuple(reason for reason in reasons if reason.startswith("signal:"))
    return spec_hints.merge(
        RetrievalHints(
            symbol_candidates=tuple(symbols[:10]),
            path_terms=_extract_path_terms(file_path),
            cleanup_terms=_extract_cleanup_terms(patch),
            state_terms=_extract_state_terms(patch),
            api_families=_extract_api_families(symbols, patch),
            keywords=_extract_identifiers(patch),
            comparison_terms=tuple(token for token in symbols if token[:1].isupper())[:4],
            role_biases=hint_keywords,
        )
    )


def _detect_bug_classes(
    *,
    file_path: str,
    patch: str,
) -> tuple[list[str], dict[str, list[str]], dict[str, RetrievalHints], float]:
    symbols = guess_symbols_from_patch(patch, max_items=10)
    suspected: list[str] = []
    class_reasons: dict[str, list[str]] = {}
    retrieval_hints: dict[str, RetrievalHints] = {}
    score = 0.0

    for bug_class, spec in BUG_CLASS_SPECS.items():
        reasons: list[str] = []
        class_score = 0.0
        for signal in spec.trigger_signals:
            if not _signal_matches(signal, patch):
                continue
            class_score += signal.weight
            reason = f"signal:{signal.name}"
            _add_reason(reasons, reason)
            for keyword in signal.hint_keywords:
                _add_reason(reasons, keyword)
        if not reasons:
            continue
        suspected.append(bug_class)
        class_reasons[bug_class] = reasons
        retrieval_hints[bug_class] = _build_class_hints(
            file_path,
            patch,
            symbols=symbols,
            reasons=reasons,
            spec_hints=spec.retrieval_hints,
        )
        score += class_score

    return suspected, class_reasons, retrieval_hints, score


def rank_diff_files(
    diff_files: list[dict[str, Any]],
    *,
    triaged_findings: list[dict[str, Any]] | None = None,
    normalized_findings: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    findings = list(triaged_findings or normalized_findings or [])
    ranked: list[dict[str, Any]] = []

    for item in diff_files:
        file_path = normalize_path(str(item.get("path", "")).strip())
        if not file_path:
            continue

        patch = str(item.get("patch", ""))
        changed_lines = list(item.get("changed_lines", []))
        score = 0.0
        reasons: list[str] = []

        if _CONTROL_FLOW_RE.search(patch):
            score += 1.8
            _add_reason(reasons, "conditional_change")
        if _COMPARISON_RE.search(patch) and ("+" in patch or "-" in patch):
            score += 1.5
            _add_reason(reasons, "comparison_change")
        if _DEFAULT_VALUE_RE.search(patch):
            score += 1.2
            _add_reason(reasons, "default_value_change")
        if _TYPE_KEYWORD_RE.search(patch):
            score += 1.0
            _add_reason(reasons, "type_shape_change")
        if _SIGNATURE_HINT_RE.search(patch):
            score += 1.4
            _add_reason(reasons, "signature_change")

        bug_classes, class_reasons, retrieval_hints, class_score = _detect_bug_classes(
            file_path=file_path,
            patch=patch,
        )
        score += class_score
        for bug_class in bug_classes:
            _add_reason(reasons, bug_class)

        added, deleted = _count_patch_lines(patch)
        if deleted > added:
            score += 0.8
            _add_reason(reasons, "deletion_heavy")
        elif added > 0:
            score += min(added / 40.0, 0.8)

        if changed_lines:
            score += min(len(changed_lines) / 25.0, 0.8)

        if any(file_path.startswith(prefix) for prefix in _CORE_PATH_HINTS):
            score += 0.7
            _add_reason(reasons, "core_file")

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
                "suspected_bug_classes": bug_classes,
                "class_reasons": class_reasons,
                "retrieval_hints": retrieval_hints,
                "primary_bug_class": bug_classes[0] if bug_classes else "",
            }
        )

    ranked.sort(
        key=lambda item: (
            -float(item.get("risk_score", 0.0)),
            -len(item.get("suspected_bug_classes", [])),
            str(item.get("path", "")),
        )
    )
    return ranked


def rank_diff_risk(
    diff_files: list[dict[str, Any]],
    triaged_findings: list[dict[str, Any]] | None = None,
    *,
    max_items: int = 5,
) -> list[dict[str, Any]]:
    ranked = rank_diff_files(
        diff_files,
        triaged_findings=triaged_findings,
    )
    return ranked[: max(max_items, 0)]
