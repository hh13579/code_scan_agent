from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


BUG_CLASS_NAMES = (
    "resource_lifecycle",
    "ownership_mismatch",
    "stale_state",
    "contract_drift",
    "partial_init_outward_struct",
    "semantic_misuse",
    "sibling_api_asymmetry",
    "error_path_cleanup_missing",
)


EVIDENCE_ROLE_NAMES = (
    "changed_entrypoint",
    "local_changed_logic",
    "declaration_or_type",
    "helper_definition",
    "direct_callee",
    "direct_caller",
    "call_sites",
    "sibling_baseline",
    "cleanup_path",
    "ownership_transfer_path",
    "state_write_point",
    "state_read_point",
    "state_reset_path",
    "destructor_or_clear",
    "public_contract",
    "outward_exposure",
    "domain_invariant",
    "error_path",
    "implementation",
    "initialization_site",
    "related_test",
    "value_producer",
    "value_consumer",
)


@dataclass(frozen=True)
class RetrievalHints:
    keywords: tuple[str, ...] = ()
    symbol_candidates: tuple[str, ...] = ()
    path_terms: tuple[str, ...] = ()
    cleanup_terms: tuple[str, ...] = ()
    state_terms: tuple[str, ...] = ()
    api_families: tuple[str, ...] = ()
    comparison_terms: tuple[str, ...] = ()
    role_biases: tuple[str, ...] = ()

    def merge(self, *others: "RetrievalHints") -> "RetrievalHints":
        def _merge_attr(name: str) -> tuple[str, ...]:
            ordered: list[str] = list(getattr(self, name))
            for other in others:
                for item in getattr(other, name):
                    if item not in ordered:
                        ordered.append(item)
            return tuple(ordered)

        return RetrievalHints(
            keywords=_merge_attr("keywords"),
            symbol_candidates=_merge_attr("symbol_candidates"),
            path_terms=_merge_attr("path_terms"),
            cleanup_terms=_merge_attr("cleanup_terms"),
            state_terms=_merge_attr("state_terms"),
            api_families=_merge_attr("api_families"),
            comparison_terms=_merge_attr("comparison_terms"),
            role_biases=_merge_attr("role_biases"),
        )

    def as_dict(self) -> dict[str, list[str]]:
        return {
            "keywords": list(self.keywords),
            "symbol_candidates": list(self.symbol_candidates),
            "path_terms": list(self.path_terms),
            "cleanup_terms": list(self.cleanup_terms),
            "state_terms": list(self.state_terms),
            "api_families": list(self.api_families),
            "comparison_terms": list(self.comparison_terms),
            "role_biases": list(self.role_biases),
        }


@dataclass(frozen=True)
class TriggerSignal:
    name: str
    patterns: tuple[str, ...]
    weight: float
    reason: str
    hint_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceRoleSpec:
    name: str
    default_hop: int
    description: str
    default_kind: str
    max_blocks: int = 2


@dataclass(frozen=True)
class BugClassSpec:
    name: str
    trigger_signals: tuple[TriggerSignal, ...]
    evidence_roles: tuple[str, ...]
    minimum_evidence_requirements: tuple[tuple[str, ...], ...]
    retrieval_hints: RetrievalHints
    severity_hints: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalPlanItem:
    bug_class: str
    evidence_role: str
    hop: int
    why_selected: str
    hints: RetrievalHints


@dataclass(frozen=True)
class RetrievalPlan:
    file: str
    language: str
    suspected_bug_classes: tuple[str, ...]
    class_reasons: Mapping[str, tuple[str, ...]]
    retrieval_hints: Mapping[str, RetrievalHints]
    items: tuple[RetrievalPlanItem, ...]
    hop_strategy: tuple[str, ...]
    why_selected: tuple[str, ...]


@dataclass(frozen=True)
class ContextBlock:
    file: str
    kind: str
    content: str
    bug_class: str
    evidence_role: str
    hop: int
    source_path: str
    why_selected: str
    subject_file: str = ""
    symbol: str = ""
    priority: int = 10
    max_chars: int | None = None
    max_lines: int | None = None

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {
            "file": self.file,
            "kind": self.kind,
            "content": self.content,
            "bug_class": self.bug_class,
            "evidence_role": self.evidence_role,
            "hop": self.hop,
            "source_path": self.source_path,
            "why_selected": self.why_selected,
        }
        if self.subject_file:
            data["subject_file"] = self.subject_file
        if self.symbol:
            data["symbol"] = self.symbol
        if self.priority != 10:
            data["priority"] = self.priority
        if self.max_chars is not None:
            data["max_chars"] = self.max_chars
        if self.max_lines is not None:
            data["max_lines"] = self.max_lines
        return data


EVIDENCE_ROLE_SPECS: dict[str, EvidenceRoleSpec] = {
    "changed_entrypoint": EvidenceRoleSpec("changed_entrypoint", 1, "Changed entrypoint or wrapper function.", "function_context"),
    "local_changed_logic": EvidenceRoleSpec("local_changed_logic", 1, "Local changed implementation block.", "function_context"),
    "declaration_or_type": EvidenceRoleSpec("declaration_or_type", 1, "Relevant type or declaration.", "type_definition"),
    "helper_definition": EvidenceRoleSpec("helper_definition", 2, "Helper or converter definition used by the patch.", "helper_definition"),
    "direct_callee": EvidenceRoleSpec("direct_callee", 2, "Direct callee implementation from the changed function.", "helper_definition"),
    "direct_caller": EvidenceRoleSpec("direct_caller", 2, "Direct caller or bridge path into the changed function.", "call_site"),
    "call_sites": EvidenceRoleSpec("call_sites", 2, "Representative call sites for changed symbols.", "call_site", max_blocks=3),
    "sibling_baseline": EvidenceRoleSpec("sibling_baseline", 3, "Sibling API or nearby baseline for asymmetry comparison.", "sibling_api", max_blocks=2),
    "cleanup_path": EvidenceRoleSpec("cleanup_path", 3, "Cleanup / release / pool / destroy path.", "cleanup_path", max_blocks=3),
    "ownership_transfer_path": EvidenceRoleSpec("ownership_transfer_path", 3, "Ownership transfer or bridge path.", "ownership_path", max_blocks=2),
    "state_write_point": EvidenceRoleSpec("state_write_point", 1, "State write point introduced or modified by the patch.", "function_context"),
    "state_read_point": EvidenceRoleSpec("state_read_point", 2, "Consumers of the affected state.", "call_site", max_blocks=3),
    "state_reset_path": EvidenceRoleSpec("state_reset_path", 3, "Reset / clear / end path for the affected state.", "cleanup_path", max_blocks=3),
    "destructor_or_clear": EvidenceRoleSpec("destructor_or_clear", 3, "Destructor / clear / teardown path.", "cleanup_path", max_blocks=2),
    "public_contract": EvidenceRoleSpec("public_contract", 3, "Public declaration or external contract.", "type_definition"),
    "outward_exposure": EvidenceRoleSpec("outward_exposure", 3, "Where the value or struct is exposed outward.", "call_site", max_blocks=2),
    "domain_invariant": EvidenceRoleSpec("domain_invariant", 4, "Domain invariant or semantic baseline.", "helper_definition", max_blocks=2),
    "error_path": EvidenceRoleSpec("error_path", 3, "Error / early return branch.", "cleanup_path", max_blocks=2),
    "implementation": EvidenceRoleSpec("implementation", 1, "Changed implementation body.", "function_context"),
    "initialization_site": EvidenceRoleSpec("initialization_site", 1, "Initialization site for an outward struct.", "function_context"),
    "related_test": EvidenceRoleSpec("related_test", 4, "Related tests or executable usage examples.", "related_test", max_blocks=2),
    "value_producer": EvidenceRoleSpec("value_producer", 2, "Producer of a value consumed semantically.", "helper_definition", max_blocks=2),
    "value_consumer": EvidenceRoleSpec("value_consumer", 2, "Consumer of a value used semantically.", "call_site", max_blocks=3),
}


BUG_CLASS_SPECS: dict[str, BugClassSpec] = {
    "resource_lifecycle": BugClassSpec(
        name="resource_lifecycle",
        trigger_signals=(
            TriggerSignal("allocator_or_free", (r"\bnew(?:\[\])?\b", r"\bmalloc\b", r"\bcalloc\b", r"\brealloc\b", r"\bstrdup\b", r"\bfree\b", r"\bdelete(?:\[\])?\b"), 2.8, "explicit allocation or free change", ("new", "malloc", "free", "delete")),
            TriggerSignal("helper_alloc_like", (r"\b(create|clone|parse|decode|pb2c|alloc|open|acquire|retain)\b",), 2.2, "helper may allocate or retain resources", ("pb2c", "parse", "decode", "clone", "create")),
            TriggerSignal("cleanup_terms", (r"\b(save|release|pool|clear|destroy|reset|close|cleanup)\b",), 1.8, "cleanup lifecycle keyword changed", ("save", "release", "pool", "clear", "destroy")),
            TriggerSignal("container_wrapper", (r"\b(PtrArr|vector<|std::vector|unique_ptr|shared_ptr|raw pointer|buffer|handle)\b",), 1.7, "container or ownership wrapper changed", ("PtrArr", "vector", "handle")),
        ),
        evidence_roles=("changed_entrypoint", "declaration_or_type", "helper_definition", "ownership_transfer_path", "cleanup_path", "destructor_or_clear", "sibling_baseline"),
        minimum_evidence_requirements=(("helper_definition", "ownership_transfer_path"), ("cleanup_path", "destructor_or_clear", "sibling_baseline")),
        retrieval_hints=RetrievalHints(
            cleanup_terms=("save", "release", "pool", "clear", "destroy", "reset", "close", "cleanup"),
            comparison_terms=("baseline", "existing API", "sibling"),
            role_biases=("helper_definition", "cleanup_path", "sibling_baseline"),
        ),
        severity_hints={"hot_path": "Do not automatically downgrade if leak is on per-request or high-frequency paths."},
    ),
    "ownership_mismatch": BugClassSpec(
        name="ownership_mismatch",
        trigger_signals=(
            TriggerSignal("wrapper_or_bridge", (r"\b(wrapper|bridge|adapter|manager|setter|set[A-Z][A-Za-z_]+|[A-Z]+_Set[A-Za-z_]+)\b",), 2.3, "wrapper or bridge ownership handoff changed", ("wrapper", "bridge", "manager", "setter")),
            TriggerSignal("complex_param_transfer", (r"\b([A-Z][A-Za-z0-9_]*_t|PtrArr|vector<|std::vector|std::unique_ptr|std::shared_ptr)\b",), 2.0, "complex object or pointer wrapper transferred across API", ("PtrArr", "vector", "ownership")),
        ),
        evidence_roles=("changed_entrypoint", "declaration_or_type", "ownership_transfer_path", "cleanup_path", "sibling_baseline", "public_contract"),
        minimum_evidence_requirements=(("ownership_transfer_path",), ("cleanup_path", "sibling_baseline")),
        retrieval_hints=RetrievalHints(
            keywords=("ownership", "transfer", "bridge", "setter"),
            cleanup_terms=("save", "release", "pool", "clear", "destroy"),
            comparison_terms=("sibling", "existing API"),
            role_biases=("ownership_transfer_path", "cleanup_path", "sibling_baseline"),
        ),
    ),
    "stale_state": BugClassSpec(
        name="stale_state",
        trigger_signals=(
            TriggerSignal("state_field", (r"\b(?:last|current|prev|previous|cache|cached|state|status|flag)[A-Z_][A-Za-z0-9_]*\b", r"\bm_(?:last|current|cache|state|status|flag)[A-Za-z0-9_]*\b", r"\bhas[A-Z][A-Za-z0-9_]*\b", r"\bis[A-Z][A-Za-z0-9_]*\b"), 2.3, "state-like field or flag changed", ("last", "current", "cache", "state", "flag")),
            TriggerSignal("reset_path", (r"\b(clear|reset|end|finish|switch|exchange|destruct|destroy)\b",), 1.9, "state reset or teardown path changed", ("clear", "reset", "end", "switch", "destroy")),
        ),
        evidence_roles=("changed_entrypoint", "state_write_point", "state_read_point", "state_reset_path", "destructor_or_clear", "sibling_baseline", "related_test"),
        minimum_evidence_requirements=(("state_write_point",), ("state_reset_path", "destructor_or_clear")),
        retrieval_hints=RetrievalHints(
            state_terms=("last", "current", "cache", "state", "status", "flag", "reset", "clear", "end"),
            comparison_terms=("previous flow", "sibling API"),
            role_biases=("state_write_point", "state_reset_path", "destructor_or_clear"),
        ),
    ),
    "contract_drift": BugClassSpec(
        name="contract_drift",
        trigger_signals=(
            TriggerSignal("public_api", (r"\b(export|public|virtual|override|interface|api|service)\b",), 1.8, "public or outward-facing API changed", ("public", "api", "interface")),
            TriggerSignal("signature_change", (r"^[+-]\s*(?:export\s+)?(?:async\s+)?(?:public|private|protected|static|virtual|inline|constexpr|final|override|\s)*(?:function\s+)?[A-Za-z_~][\w:<>]*\s*\(",), 1.4, "function signature changed", ("signature",)),
        ),
        evidence_roles=("public_contract", "implementation", "call_sites", "outward_exposure", "sibling_baseline"),
        minimum_evidence_requirements=(("public_contract", "implementation"), ("call_sites", "outward_exposure")),
        retrieval_hints=RetrievalHints(
            keywords=("public", "interface", "api", "contract"),
            comparison_terms=("baseline", "callers"),
            role_biases=("public_contract", "call_sites"),
        ),
    ),
    "partial_init_outward_struct": BugClassSpec(
        name="partial_init_outward_struct",
        trigger_signals=(
            TriggerSignal("stack_struct_init", (r"\b[A-Z][A-Za-z0-9_]*\s+[a-zA-Z_][A-Za-z0-9_]*\s*;\b",), 1.6, "stack struct introduced before outward assignment", ("struct", "init")),
            TriggerSignal("field_assignment", (r"\.[A-Za-z_][A-Za-z0-9_]*\s*=",), 1.4, "individual field assignments changed", ("field", "assign")),
        ),
        evidence_roles=("declaration_or_type", "initialization_site", "outward_exposure", "call_sites"),
        minimum_evidence_requirements=(("declaration_or_type", "initialization_site"), ("outward_exposure",)),
        retrieval_hints=RetrievalHints(
            keywords=("struct", "field", "init"),
            role_biases=("declaration_or_type", "outward_exposure"),
        ),
    ),
    "semantic_misuse": BugClassSpec(
        name="semantic_misuse",
        trigger_signals=(
            TriggerSignal("numeric_semantics", (r"\b(distance|offset|index|heading|angle|projection|route|lat|lng|speed|bearing)\b",), 1.9, "domain-valued input changed", ("distance", "index", "projection", "route")),
            TriggerSignal("comparison_math", (r"\b(min|max|abs|clamp|normalize|project|compare)\b",), 1.5, "semantic helper or math logic changed", ("normalize", "project", "compare")),
        ),
        evidence_roles=("declaration_or_type", "value_producer", "value_consumer", "domain_invariant", "sibling_baseline"),
        minimum_evidence_requirements=(("value_producer", "value_consumer"), ("domain_invariant", "sibling_baseline")),
        retrieval_hints=RetrievalHints(
            keywords=("distance", "index", "projection", "route", "heading"),
            comparison_terms=("baseline", "invariant"),
            role_biases=("value_producer", "value_consumer", "domain_invariant"),
        ),
    ),
    "sibling_api_asymmetry": BugClassSpec(
        name="sibling_api_asymmetry",
        trigger_signals=(
            TriggerSignal("new_api_surface", (r"\b(set[A-Z][A-Za-z_]+|[A-Z]+_Set[A-Za-z_]+|create[A-Z][A-Za-z_]+)\b",), 1.9, "new sibling-like API added or changed", ("setter", "api")),
        ),
        evidence_roles=("changed_entrypoint", "sibling_baseline", "call_sites", "public_contract"),
        minimum_evidence_requirements=(("changed_entrypoint", "sibling_baseline"),),
        retrieval_hints=RetrievalHints(
            comparison_terms=("sibling", "nearby API", "same family"),
            role_biases=("sibling_baseline", "public_contract"),
        ),
    ),
    "error_path_cleanup_missing": BugClassSpec(
        name="error_path_cleanup_missing",
        trigger_signals=(
            TriggerSignal("early_exit", (r"\b(return|break|continue|goto)\b",), 1.7, "early exit changed", ("return", "break", "continue")),
            TriggerSignal("error_terms", (r"\b(error|fail|failed|abort|nullptr|null|invalid)\b",), 1.5, "error handling branch changed", ("error", "fail", "invalid")),
        ),
        evidence_roles=("changed_entrypoint", "error_path", "cleanup_path", "sibling_baseline"),
        minimum_evidence_requirements=(("error_path",), ("cleanup_path", "sibling_baseline")),
        retrieval_hints=RetrievalHints(
            cleanup_terms=("cleanup", "release", "rollback", "clear", "destroy"),
            role_biases=("error_path", "cleanup_path", "sibling_baseline"),
        ),
    ),
}


def get_bug_class_spec(name: str) -> BugClassSpec | None:
    return BUG_CLASS_SPECS.get(name)


def get_evidence_role_spec(name: str) -> EvidenceRoleSpec | None:
    return EVIDENCE_ROLE_SPECS.get(name)
