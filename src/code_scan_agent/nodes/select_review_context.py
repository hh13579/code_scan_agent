from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from code_scan_agent.graph.state import GraphState
from code_scan_agent.retrieval.context_bundle import bundle_context
from code_scan_agent.retrieval.context_planner import plan_review_context
from code_scan_agent.retrieval.language.common import (
    extract_line_window,
    find_matching_brace_end,
    guess_symbols_from_patch,
    iter_repo_files,
    normalize_path,
    read_file_text,
    safe_slice_lines,
    trim_block,
)
from code_scan_agent.retrieval.risk_ranker import rank_diff_risk
from code_scan_agent.retrieval.retrievers.callsite_retriever import retrieve_call_sites
from code_scan_agent.retrieval.retrievers.function_retriever import get_function_context
from code_scan_agent.retrieval.retrievers.test_retriever import find_related_tests
from code_scan_agent.retrieval.retrievers.type_retriever import get_related_types
from code_scan_agent.retrieval.specs import ContextBlock, RetrievalHints, RetrievalPlan, RetrievalPlanItem

_LANG_SUFFIXES = {
    "cpp": {".cpp", ".cc", ".cxx", ".hpp", ".h"},
    "java": {".java"},
    "ts": {".ts", ".tsx"},
}
_ALL_CODE_SUFFIXES = {".cpp", ".cc", ".cxx", ".hpp", ".h", ".java", ".ts", ".tsx"}
_CLEANUP_WORDS = ("save", "release", "pool", "clear", "destroy", "reset", "cleanup", "free", "delete", "close")
_STATE_RESET_WORDS = ("clear", "reset", "end", "finish", "switch", "destroy", "teardown")
_REPO_KNOWLEDGE_CONTEXT_SPECS = (
    {
        "path_terms": ("rg_tools", "navi_guide", "dd_route_guide"),
        "keywords": ("PtrArr", "RGEvent_t", "pb2c"),
        "file": "src/navi_guide.cpp",
        "kind": "ownership_path",
        "symbol": "setter lifecycle path",
        "anchors": (r"\bint RG_SetCodeSection\(",),
    },
    {
        "path_terms": ("rg_tools", "navi_guide", "dd_route_guide"),
        "keywords": ("PtrArr", "RGEvent_t", "pb2c"),
        "file": "src/navi_guide.cpp",
        "kind": "sibling_api",
        "symbol": "sibling setter baseline",
        "anchors": (r"\bint RG_SetMarkers\(",),
    },
    {
        "path_terms": ("rg_tools",),
        "keywords": ("pb2c", "PtrArr", "RGEvent_t"),
        "file": "nav_wrapper/rg_tools/pb2c.h",
        "kind": "helper_definition",
        "symbol": "converter deep allocation baseline",
        "anchors": (
            r"static void pb2c\(RGVISentence_t",
            r"static void pb2c\(RGBIMission_t",
            r"static void pb2c\(RGEvent_t",
            r"template <typename T> class PtrArr",
        ),
    },
    {
        "path_terms": ("dd_route_guide", "route_guide"),
        "keywords": ("save", "release", "pool", "clear"),
        "file": "dd_src/dd_route_guide/dd_ng_route_guide_mgr.cpp",
        "kind": "cleanup_path",
        "symbol": "manager cleanup bridge",
        "anchors": (
            r"\bint DDRouteGuideMgr::saveEventsAllocPointerToPool\(",
            r"\bvoid DDRouteGuideMgr::releaseEventsAllocPointer\(",
            r"\bint DDRouteGuideMgr::setCodeSection\(",
        ),
    },
    {
        "path_terms": ("dd_route_guide", "data_mgr"),
        "keywords": ("save", "pool", "clear"),
        "file": "dd_src/dd_route_guide/dd_data_mgr/dd_rg_data_mgr.cpp",
        "kind": "cleanup_path",
        "symbol": "data manager pointer pool",
        "anchors": (
            r"\bvoid DDRGDataMgr::clearEventsAllocPointerPool\(",
            r"\bvoid DDRGDataMgr::saveEventsAllocPointerToPool\(",
        ),
    },
)
_ROLE_ALLOWED_KINDS = {
    "helper_definition": {"helper_definition"},
    "direct_callee": {"helper_definition"},
    "value_producer": {"helper_definition"},
    "domain_invariant": {"helper_definition"},
    "cleanup_path": {"cleanup_path"},
    "destructor_or_clear": {"cleanup_path"},
    "state_reset_path": {"cleanup_path"},
    "error_path": {"cleanup_path"},
    "ownership_transfer_path": {"ownership_path"},
    "sibling_baseline": {"sibling_api"},
}


@lru_cache(maxsize=16)
def _repo_files_cached(repo_root: str, language: str) -> tuple[Path, ...]:
    suffixes = tuple(sorted(_LANG_SUFFIXES.get(language, _ALL_CODE_SUFFIXES)))
    return tuple(iter_repo_files(Path(repo_root), suffixes))


@lru_cache(maxsize=4096)
def _read_text_cached(path: str) -> str:
    return read_file_text(path)


def _append_error(state: GraphState, message: str) -> None:
    bucket = state.get("errors")
    if not isinstance(bucket, list):
        bucket = []
        state["errors"] = bucket
    bucket.append(message)


def _is_explicitly_disabled(request: dict[str, object]) -> bool:
    enabled = request.get("enable_llm_triage")
    if isinstance(enabled, bool) and not enabled:
        return True
    review_enabled = request.get("enable_llm_diff_review")
    return isinstance(review_enabled, bool) and not review_enabled


def _find_diff_file(diff_files: list[dict[str, Any]], path: str) -> dict[str, Any] | None:
    for item in diff_files:
        if str(item.get("path", "")) == path:
            return item
    return None


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    try:
        value = int(raw) if raw else default
    except ValueError:
        value = default
    return max(value, 0)


def _extract_anchor_block(
    text: str,
    pattern: str,
    *,
    before: int = 3,
    after: int = 36,
    probe_forward_lines: int = 8,
) -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    compiled = re.compile(pattern)
    for index, line in enumerate(lines, start=1):
        if not compiled.search(line):
            continue
        brace_line: int | None = index if "{" in line else None
        if brace_line is None:
            for probe in range(index + 1, min(len(lines), index + probe_forward_lines) + 1):
                if "{" in lines[probe - 1]:
                    brace_line = probe
                    break
        if brace_line is not None:
            end_line = find_matching_brace_end(lines, brace_line)
            if end_line is not None:
                return safe_slice_lines(text, max(1, index - before), end_line)
        return safe_slice_lines(text, max(1, index - before), min(len(lines), index + after))
    return ""


def _guess_changed_symbols(diff_file: dict[str, Any], function_block: dict[str, Any] | None) -> tuple[str, ...]:
    ordered = guess_symbols_from_patch(str(diff_file.get("patch", "")), max_items=10)
    if function_block:
        symbol = str(function_block.get("symbol", "")).strip()
        if symbol and symbol not in ordered:
            ordered.insert(0, symbol)
    return tuple(ordered[:10])


def _path_score(subject_file: str, candidate_file: str, hints: RetrievalHints) -> int:
    score = 0
    subject_parts = set(Path(subject_file).parts)
    candidate_parts = set(Path(candidate_file).parts)
    if subject_file == candidate_file:
        score += 10
    if subject_parts.intersection(candidate_parts):
        score += len(subject_parts.intersection(candidate_parts))
    for term in hints.path_terms:
        if term and term in candidate_parts:
            score += 2
    return score


def _make_context_block(
    *,
    subject_file: str,
    file: str,
    kind: str,
    content: str,
    plan_item: RetrievalPlanItem,
    symbol: str = "",
    priority: int | None = None,
    max_chars: int | None = None,
    max_lines: int | None = None,
) -> ContextBlock | None:
    normalized_content = trim_block(content, max_chars=max_chars or 1800, max_lines=max_lines)
    if not normalized_content.strip():
        return None
    return ContextBlock(
        file=normalize_path(file),
        kind=kind,
        content=normalized_content,
        bug_class=plan_item.bug_class,
        evidence_role=plan_item.evidence_role,
        hop=plan_item.hop,
        source_path=normalize_path(file),
        why_selected=plan_item.why_selected,
        subject_file=normalize_path(subject_file),
        symbol=symbol,
        priority=int(priority if priority is not None else max(0, plan_item.hop - 1)),
        max_chars=max_chars,
        max_lines=max_lines,
    )


def _from_retriever_blocks(
    raw_blocks: list[dict[str, Any]],
    *,
    subject_file: str,
    plan_item: RetrievalPlanItem,
) -> list[ContextBlock]:
    out: list[ContextBlock] = []
    for item in raw_blocks:
        block = _make_context_block(
            subject_file=subject_file,
            file=str(item.get("file", "")),
            kind=str(item.get("kind", "")),
            content=str(item.get("content", "")),
            plan_item=plan_item,
            symbol=str(item.get("symbol", "")),
            max_chars=int(item["max_chars"]) if item.get("max_chars") is not None else None,
            max_lines=int(item["max_lines"]) if item.get("max_lines") is not None else None,
        )
        if block:
            out.append(block)
    return out


def _search_repo_blocks(
    repo_root: Path,
    *,
    subject_file: str,
    language: str,
    plan_item: RetrievalPlanItem,
    required_terms: tuple[str, ...],
    optional_terms: tuple[str, ...] = (),
    kind: str,
    max_results: int = 2,
    prefer_same_file: bool = False,
) -> list[ContextBlock]:
    suffixes = _LANG_SUFFIXES.get(language, _ALL_CODE_SUFFIXES)
    candidates: list[tuple[int, ContextBlock]] = []
    seen_files: set[str] = set()

    for path in _repo_files_cached(str(repo_root), language):
        if path.suffix.lower() not in suffixes:
            continue
        rel_path = normalize_path(path.relative_to(repo_root))
        if rel_path in seen_files:
            continue
        text = _read_text_cached(str(path))
        if not text:
            continue
        lowered = text.lower()
        primary_hits = [term for term in required_terms if term and term.lower() in lowered]
        if not primary_hits:
            continue
        if optional_terms and not any(term.lower() in lowered for term in optional_terms):
            continue

        score = _path_score(subject_file, rel_path, plan_item.hints)
        if prefer_same_file and rel_path == subject_file:
            score += 6
        score += len(primary_hits) * 2

        snippet = ""
        symbol = primary_hits[0]
        for term in primary_hits:
            pattern = rf"\b{re.escape(term)}\b"
            snippet = _extract_anchor_block(text, pattern)
            if snippet:
                symbol = term
                break
        if not snippet:
            for line_no, line in enumerate(text.splitlines(), start=1):
                if any(term.lower() in line.lower() for term in primary_hits):
                    snippet = extract_line_window(text, line_no, before=10, after=20)
                    symbol = primary_hits[0]
                    break
        block = _make_context_block(
            subject_file=subject_file,
            file=rel_path,
            kind=kind,
            content=snippet,
            plan_item=plan_item,
            symbol=symbol,
            max_chars=2200,
            max_lines=220,
        )
        if not block:
            continue
        candidates.append((score, block))
        seen_files.add(rel_path)

    candidates.sort(key=lambda item: (-item[0], item[1].file))
    return [block for _, block in candidates[:max_results]]


def _retrieve_sibling_baselines(
    repo_root: Path,
    *,
    subject_file: str,
    language: str,
    plan_item: RetrievalPlanItem,
    changed_symbols: tuple[str, ...],
) -> list[ContextBlock]:
    candidates: list[ContextBlock] = []
    target_path = (repo_root / subject_file).resolve()
    text = _read_text_cached(str(target_path))
    if not text:
        return []

    families = list(plan_item.hints.api_families) or [symbol.split("_")[0] for symbol in changed_symbols if "_" in symbol]
    cleanup_terms = tuple(plan_item.hints.cleanup_terms) or _CLEANUP_WORDS

    for family in families:
        if not family:
            continue
        pattern = re.compile(rf"\b({re.escape(family)}[A-Za-z_0-9]+)\s*\(")
        for match in pattern.finditer(text):
            symbol = match.group(1)
            if symbol in changed_symbols:
                continue
            block = _extract_anchor_block(text, rf"\b{re.escape(symbol)}\s*\(")
            if not block:
                continue
            if cleanup_terms and not any(term.lower() in block.lower() for term in cleanup_terms):
                continue
            context_block = _make_context_block(
                subject_file=subject_file,
                file=subject_file,
                kind="sibling_api",
                content=block,
                plan_item=plan_item,
                symbol=symbol,
                priority=1,
                max_chars=2200,
                max_lines=220,
            )
            if context_block:
                candidates.append(context_block)
            if len(candidates) >= 2:
                return candidates

    if candidates:
        return candidates
    return _search_repo_blocks(
        repo_root,
        subject_file=subject_file,
        language=language,
        plan_item=plan_item,
        required_terms=tuple(families or changed_symbols[:2]),
        optional_terms=cleanup_terms,
        kind="sibling_api",
        max_results=2,
    )


def _retrieve_repo_knowledge_blocks(
    repo_root: Path,
    *,
    subject_file: str,
    plan_item: RetrievalPlanItem,
) -> list[ContextBlock]:
    hints = plan_item.hints
    hits: list[ContextBlock] = []
    hint_tokens = set(hints.keywords) | set(hints.symbol_candidates) | set(hints.path_terms)
    allowed_kinds = _ROLE_ALLOWED_KINDS.get(plan_item.evidence_role, set())
    for spec in _REPO_KNOWLEDGE_CONTEXT_SPECS:
        if allowed_kinds and str(spec["kind"]) not in allowed_kinds:
            continue
        should_include = bool(set(spec["path_terms"]).intersection(hint_tokens) or set(spec["keywords"]).intersection(hint_tokens))
        if not should_include and plan_item.bug_class in {"resource_lifecycle", "ownership_mismatch"}:
            if plan_item.evidence_role in {"helper_definition", "cleanup_path", "ownership_transfer_path", "sibling_baseline"}:
                should_include = True
        if not should_include:
            continue
        abs_path = (repo_root / str(spec["file"])).resolve()
        text = _read_text_cached(str(abs_path))
        if not text:
            continue
        snippets: list[str] = []
        for anchor in spec["anchors"]:
            block = _extract_anchor_block(text, anchor)
            if block and block not in snippets:
                snippets.append(block)
        if not snippets:
            continue
        block = _make_context_block(
            subject_file=subject_file,
            file=str(spec["file"]),
            kind=str(spec["kind"]),
            content="\n\n".join(snippets),
            plan_item=plan_item,
            symbol=str(spec["symbol"]),
            priority=0,
            max_chars=3200,
            max_lines=260,
        )
        if block:
            hits.append(block)
    return hits


def _retrieve_role_blocks(
    repo_root: Path,
    *,
    subject_file: str,
    language: str,
    diff_file: dict[str, Any],
    plan_item: RetrievalPlanItem,
    function_block: dict[str, Any] | None,
) -> list[ContextBlock]:
    changed_symbols = _guess_changed_symbols(diff_file, function_block)
    common_terms = tuple(plan_item.hints.symbol_candidates) or changed_symbols

    if plan_item.evidence_role in {"changed_entrypoint", "local_changed_logic", "implementation", "initialization_site", "state_write_point"}:
        if not function_block:
            return []
        return _from_retriever_blocks([function_block], subject_file=subject_file, plan_item=plan_item)

    if plan_item.evidence_role in {"declaration_or_type", "public_contract"}:
        return _from_retriever_blocks(
            get_related_types(
                repo_path=repo_root,
                file=subject_file,
                language=language,
                patch=str(diff_file.get("patch", "")),
                function_context=function_block,
            ),
            subject_file=subject_file,
            plan_item=plan_item,
        )

    if plan_item.evidence_role in {"call_sites", "direct_caller", "state_read_point", "outward_exposure", "value_consumer"}:
        return _from_retriever_blocks(
            retrieve_call_sites(
                repo_path=repo_root,
                file=subject_file,
                language=language,
                patch=str(diff_file.get("patch", "")),
                function_context=function_block,
            ),
            subject_file=subject_file,
            plan_item=plan_item,
        )

    if plan_item.evidence_role == "sibling_baseline":
        blocks = _retrieve_sibling_baselines(
            repo_root,
            subject_file=subject_file,
            language=language,
            plan_item=plan_item,
            changed_symbols=changed_symbols,
        )
        return blocks + _retrieve_repo_knowledge_blocks(repo_root, subject_file=subject_file, plan_item=plan_item)

    if plan_item.evidence_role in {"helper_definition", "direct_callee", "value_producer", "domain_invariant"}:
        return _search_repo_blocks(
            repo_root,
            subject_file=subject_file,
            language=language,
            plan_item=plan_item,
            required_terms=common_terms,
            optional_terms=(),
            kind="helper_definition",
            max_results=3,
        )

    if plan_item.evidence_role in {"cleanup_path", "ownership_transfer_path", "state_reset_path", "destructor_or_clear", "error_path"}:
        optional_terms = tuple(plan_item.hints.cleanup_terms) or (_STATE_RESET_WORDS if "state" in plan_item.evidence_role else _CLEANUP_WORDS)
        kind = "cleanup_path" if plan_item.evidence_role != "ownership_transfer_path" else "ownership_path"
        blocks = _search_repo_blocks(
            repo_root,
            subject_file=subject_file,
            language=language,
            plan_item=plan_item,
            required_terms=common_terms or plan_item.hints.keywords,
            optional_terms=optional_terms,
            kind=kind,
            max_results=3,
        )
        return blocks + _retrieve_repo_knowledge_blocks(repo_root, subject_file=subject_file, plan_item=plan_item)

    if plan_item.evidence_role in {"related_test", "related_tests"}:
        return _from_retriever_blocks(
            find_related_tests(
                repo_path=repo_root,
                file=subject_file,
                language=language,
                patch=str(diff_file.get("patch", "")),
                function_context=function_block,
            ),
            subject_file=subject_file,
            plan_item=plan_item,
        )

    return []


def _context_key(block: ContextBlock) -> tuple[str, str, str, str, str, int]:
    return (
        block.subject_file,
        block.file,
        block.kind,
        block.symbol,
        block.bug_class,
        block.hop,
    )


def select_review_context(state: GraphState) -> GraphState:
    state["review_context_blocks"] = []
    state["review_plans"] = []

    request = state.get("request", {})
    if str(request.get("mode", "full")) != "diff":
        state.setdefault("logs", []).append("select_review_context: skipped (non-diff mode)")
        return state
    if _is_explicitly_disabled(request):
        state.setdefault("logs", []).append("select_review_context: skipped (--no-llm)")
        return state

    diff_files = list(state.get("diff_files", []))
    if not diff_files:
        state.setdefault("logs", []).append("select_review_context: skipped (no diff_files)")
        return state

    repo_root = Path(
        str(
            request.get("repo_path")
            or state.get("repo_profile", {}).get("repo_path", "")
        )
    ).resolve()
    if not repo_root.is_dir():
        _append_error(state, f"select_review_context: invalid repo path: {repo_root}")
        return state

    max_files = _env_int("REVIEW_CONTEXT_TOP_FILES", 5) or 5
    ranked = rank_diff_risk(
        diff_files[: (_env_int("LLM_DIFF_REVIEW_MAX_FILES", 12) or 12)],
        triaged_findings=list(state.get("triaged_findings", []))
        or list(state.get("normalized_findings", [])),
        max_items=max_files,
    )

    raw_blocks: list[ContextBlock] = []
    review_plans: list[RetrievalPlan] = []
    seen_keys: set[tuple[str, str, str, str, str, int]] = set()
    processed = 0

    for ranked_item in ranked[:max_files]:
        diff_file = _find_diff_file(diff_files, str(ranked_item.get("path", "")))
        if not diff_file:
            continue
        processed += 1
        try:
            plan = plan_review_context(
                diff_file,
                risk_score=float(ranked_item.get("risk_score", 0.0)),
                reasons=[str(item) for item in ranked_item.get("reasons", [])],
                suspected_bug_classes=[str(item) for item in ranked_item.get("suspected_bug_classes", [])],
                class_reasons={
                    str(key): [str(reason) for reason in value]
                    for key, value in dict(ranked_item.get("class_reasons", {})).items()
                },
                retrieval_hints={
                    str(key): value
                    for key, value in dict(ranked_item.get("retrieval_hints", {})).items()
                    if isinstance(value, RetrievalHints)
                },
            )
            review_plans.append(plan)

            function_block = get_function_context(
                repo_path=repo_root,
                file=str(diff_file.get("path", "")),
                language=str(diff_file.get("language", "")),
                changed_lines=list(diff_file.get("changed_lines", [])),
            )

            for plan_item in plan.items:
                blocks = _retrieve_role_blocks(
                    repo_root,
                    subject_file=plan.file,
                    language=plan.language,
                    diff_file=diff_file,
                    plan_item=plan_item,
                    function_block=function_block,
                )
                for block in blocks:
                    key = _context_key(block)
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    raw_blocks.append(block)

        except Exception as exc:  # noqa: BLE001
            _append_error(
                state,
                f"select_review_context: retrieval failed for {ranked_item.get('path', '')}: {type(exc).__name__}: {exc}",
            )

    bundled = bundle_context(raw_blocks)
    state["review_plans"] = review_plans
    state["review_context_blocks"] = bundled
    state.setdefault("logs", []).append(
        "select_review_context: "
        f"ranked={len(ranked)}, processed={processed}, plans={len(review_plans)}, raw_blocks={len(raw_blocks)}, bundled={len(bundled)}"
    )
    return state
