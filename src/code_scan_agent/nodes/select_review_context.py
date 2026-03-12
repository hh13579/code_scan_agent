from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from code_scan_agent.graph.state import GraphState
from code_scan_agent.retrieval.context_bundle import build_context_bundle
from code_scan_agent.retrieval.context_planner import plan_review_context
from code_scan_agent.retrieval.risk_ranker import rank_diff_files
from code_scan_agent.retrieval.retrievers.callsite_retriever import retrieve_call_sites
from code_scan_agent.retrieval.retrievers.function_retriever import retrieve_function_context
from code_scan_agent.retrieval.retrievers.test_retriever import retrieve_related_tests
from code_scan_agent.retrieval.retrievers.type_retriever import retrieve_type_definitions


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


def _attach_subject_file(blocks: list[dict[str, Any]], subject_file: str) -> list[dict[str, Any]]:
    attached: list[dict[str, Any]] = []
    for item in blocks:
        normalized = dict(item)
        normalized["subject_file"] = subject_file
        attached.append(normalized)
    return attached


def select_review_context(state: GraphState) -> GraphState:
    state["review_context_blocks"] = []

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

    ranked = rank_diff_files(
        diff_files[: (_env_int("LLM_DIFF_REVIEW_MAX_FILES", 12) or 12)],
        triaged_findings=list(state.get("triaged_findings", [])),
        normalized_findings=list(state.get("normalized_findings", [])),
    )
    max_files = _env_int("REVIEW_CONTEXT_TOP_FILES", 8) or 8
    per_file_blocks: list[list[dict[str, Any]]] = []
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
                reasons=list(ranked_item.get("reasons", [])),
            )
            file_blocks: list[dict[str, Any]] = []
            function_blocks: list[dict[str, Any]] = []
            function_block: dict[str, Any] | None = None
            needs = list(plan.get("needs", []))

            if "function_context" in needs:
                function_blocks = retrieve_function_context(
                    repo_path=repo_root,
                    file=str(diff_file.get("path", "")),
                    language=str(diff_file.get("language", "")),
                    changed_lines=list(diff_file.get("changed_lines", [])),
                )
                file_blocks.extend(_attach_subject_file(function_blocks, str(diff_file.get("path", ""))))
                function_block = function_blocks[0] if function_blocks else None

            if "type_definition" in needs:
                file_blocks.extend(
                    _attach_subject_file(
                        retrieve_type_definitions(
                        repo_path=repo_root,
                        file=str(diff_file.get("path", "")),
                        language=str(diff_file.get("language", "")),
                        patch=str(diff_file.get("patch", "")),
                        function_context=function_block,
                        ),
                        str(diff_file.get("path", "")),
                    )
                )

            if "call_sites" in needs:
                file_blocks.extend(
                    _attach_subject_file(
                        retrieve_call_sites(
                        repo_path=repo_root,
                        file=str(diff_file.get("path", "")),
                        language=str(diff_file.get("language", "")),
                        patch=str(diff_file.get("patch", "")),
                        function_context=function_block,
                        ),
                        str(diff_file.get("path", "")),
                    )
                )

            if "related_tests" in needs:
                file_blocks.extend(
                    _attach_subject_file(
                        retrieve_related_tests(
                        repo_path=repo_root,
                        file=str(diff_file.get("path", "")),
                        language=str(diff_file.get("language", "")),
                        patch=str(diff_file.get("patch", "")),
                        function_context=function_block,
                        ),
                        str(diff_file.get("path", "")),
                    )
                )

            if file_blocks:
                per_file_blocks.append(file_blocks)

        except Exception as exc:  # noqa: BLE001
            _append_error(
                state,
                f"select_review_context: retrieval failed for {ranked_item.get('path', '')}: {type(exc).__name__}: {exc}",
            )

    raw_blocks: list[dict[str, Any]] = []
    if per_file_blocks:
        max_block_depth = max(len(items) for items in per_file_blocks)
        for index in range(max_block_depth):
            for items in per_file_blocks:
                if index < len(items):
                    raw_blocks.append(items[index])

    bundled = build_context_bundle(
        raw_blocks,
        max_blocks=_env_int("REVIEW_CONTEXT_MAX_BLOCKS", 16) or 16,
        max_block_chars=_env_int("REVIEW_CONTEXT_MAX_BLOCK_CHARS", 1600) or 1600,
        max_total_chars=_env_int("REVIEW_CONTEXT_MAX_TOTAL_CHARS", 20000) or 20000,
        per_kind_limit=_env_int("REVIEW_CONTEXT_PER_KIND_LIMIT", 1) or 1,
    )
    state["review_context_blocks"] = bundled
    state.setdefault("logs", []).append(
        "select_review_context: "
        f"ranked={len(ranked)}, processed={processed}, raw_blocks={len(raw_blocks)}, bundled={len(bundled)}"
    )
    return state
