from __future__ import annotations

from typing import Any

from code_scan_agent.retrieval.specs import (
    BUG_CLASS_SPECS,
    RetrievalHints,
    RetrievalPlan,
    RetrievalPlanItem,
    get_evidence_role_spec,
)


_HOP_STRATEGY = (
    "hop1: changed function / declaration / local implementation",
    "hop2: helper definitions / direct callees / direct callers",
    "hop3: sibling APIs / cleanup-clear-reset-dtor paths / outward contract",
    "hop4: tests / domain invariants / repository knowledge",
)


def _why_selected(
    bug_class: str,
    evidence_role: str,
    reasons: list[str],
) -> str:
    joined = ", ".join(reasons[:3]) if reasons else "triggered by patch signals"
    return f"{bug_class} requires {evidence_role}; selected because {joined}."


def _merge_hints(*values: RetrievalHints | None) -> RetrievalHints:
    merged = RetrievalHints()
    for value in values:
        if value is None:
            continue
        merged = merged.merge(value)
    return merged


def _fallback_items(
    file_path: str,
    language: str,
    *,
    reasons: list[str],
) -> RetrievalPlan:
    items = (
        RetrievalPlanItem(
            bug_class="generic_review",
            evidence_role="changed_entrypoint",
            hop=1,
            why_selected="Need the changed implementation as a baseline review anchor.",
            hints=RetrievalHints(role_biases=("changed_entrypoint",)),
        ),
        RetrievalPlanItem(
            bug_class="generic_review",
            evidence_role="call_sites",
            hop=2,
            why_selected="Need representative callers to avoid judging the patch in isolation.",
            hints=RetrievalHints(role_biases=("call_sites",)),
        ),
        RetrievalPlanItem(
            bug_class="generic_review",
            evidence_role="related_test",
            hop=4,
            why_selected="Need tests or executable examples as a late-hop behavioral baseline.",
            hints=RetrievalHints(role_biases=("related_test",)),
        ),
    )
    return RetrievalPlan(
        file=file_path,
        language=language,
        suspected_bug_classes=(),
        class_reasons={},
        retrieval_hints={},
        items=items,
        hop_strategy=_HOP_STRATEGY,
        why_selected=(f"Fallback review plan; reasons={', '.join(reasons[:4])}" if reasons else "Fallback review plan",),
    )


def plan_review_context(
    diff_file: dict[str, Any],
    *,
    risk_score: float | None = None,
    reasons: list[str] | None = None,
    suspected_bug_classes: list[str] | None = None,
    class_reasons: dict[str, list[str]] | None = None,
    retrieval_hints: dict[str, RetrievalHints] | None = None,
) -> RetrievalPlan:
    file_path = str(diff_file.get("path", ""))
    language = str(diff_file.get("language", ""))
    reason_list = list(reasons or [])
    bug_classes = list(suspected_bug_classes or [])
    class_reason_map = dict(class_reasons or {})
    hint_map = dict(retrieval_hints or {})

    if not bug_classes:
        return _fallback_items(file_path, language, reasons=reason_list)

    items: list[RetrievalPlanItem] = []
    seen: set[tuple[str, str]] = set()
    why_selected: list[str] = []

    for bug_class in bug_classes:
        spec = BUG_CLASS_SPECS.get(bug_class)
        if spec is None:
            continue
        per_class_reasons = list(class_reason_map.get(bug_class, []))
        why_selected.append(
            f"{bug_class}: risk_score={float(risk_score or 0.0):.2f}, signals={', '.join(per_class_reasons[:4]) or 'none'}"
        )
        class_hints = _merge_hints(spec.retrieval_hints, hint_map.get(bug_class))
        for evidence_role in spec.evidence_roles:
            key = (bug_class, evidence_role)
            if key in seen:
                continue
            role_spec = get_evidence_role_spec(evidence_role)
            if role_spec is None:
                continue
            items.append(
                RetrievalPlanItem(
                    bug_class=bug_class,
                    evidence_role=evidence_role,
                    hop=role_spec.default_hop,
                    why_selected=_why_selected(bug_class, evidence_role, per_class_reasons),
                    hints=class_hints,
                )
            )
            seen.add(key)

    if not items:
        return _fallback_items(file_path, language, reasons=reason_list)

    return RetrievalPlan(
        file=file_path,
        language=language,
        suspected_bug_classes=tuple(bug_classes),
        class_reasons={key: tuple(value) for key, value in class_reason_map.items()},
        retrieval_hints={key: value for key, value in hint_map.items()},
        items=tuple(sorted(items, key=lambda item: (item.hop, item.bug_class, item.evidence_role))),
        hop_strategy=_HOP_STRATEGY,
        why_selected=tuple(why_selected),
    )


def plan_context(diff_file: dict[str, Any], patch: str | None = None) -> RetrievalPlan:
    normalized = dict(diff_file)
    if patch is not None:
        normalized["patch"] = patch
    return plan_review_context(normalized)
