from __future__ import annotations

from typing import Any, Literal, TypedDict

from code_scan_agent.retrieval.specs import ContextBlock, RetrievalPlan


Language = Literal["cpp", "java", "ts"]
ScanMode = Literal["full", "diff", "selected"]
Severity = Literal["critical", "high", "medium", "low", "info"]
ReviewAction = Literal["block", "should_fix", "follow_up"]


class ScanRequest(TypedDict, total=False):
    repo_path: str
    source_repo_path: str
    mode: ScanMode
    enable_security_scan: bool
    enable_fix_suggestion: bool
    enable_llm_triage: bool
    enable_llm_diff_review: bool
    include_globs: list[str]
    exclude_globs: list[str]
    selected_paths: list[str]
    base_ref: str
    head_ref: str
    diff_base_ref: str
    diff_head_ref: str
    diff_commit: str
    diff_staged: bool
    diff_range_mode: Literal["triple", "double"]
    diff_findings_filter: Literal["mark", "only"]


class RepoProfile(TypedDict, total=False):
    repo_path: str
    languages: list[Language]
    build_systems: list[str]
    config_files: list[str]
    compile_db_path: str | None


class FileTarget(TypedDict, total=False):
    path: str
    language: Language
    changed_lines: list[int]


class DiffFile(TypedDict, total=False):
    path: str
    old_path: str
    language: Language
    status: str
    changed_lines: list[int]
    patch: str
    hunks: list[str]


class ToolResult(TypedDict, total=False):
    tool: str
    language: str
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    raw_findings: list[dict[str, Any]]


class Finding(TypedDict, total=False):
    language: Language
    tool: str
    source: str
    rule_id: str
    category: str
    bug_class: str
    severity: Severity
    file: str
    line: int | None
    column: int | None
    title: str
    message: str
    impact: str
    snippet: str | None
    confidence: str
    review_action: ReviewAction
    autofix_available: bool
    in_diff: bool
    evidence: list[str] | str
    key_evidence_roles: list[str]
    evidence_completeness: str
    key_evidence_summary: list[str]
    suggested_action: str
    overlaps_static: bool
    verification_status: str
    verification_notes: list[str] | str


class Report(TypedDict, total=False):
    summary: dict[str, Any]
    findings: list[Finding]
    grouped_by_file: dict[str, list[Finding]]
    grouped_by_severity: dict[str, list[Finding]]


class GraphState(TypedDict, total=False):
    # 输入
    request: ScanRequest

    # 中间态
    repo_profile: RepoProfile
    targets: list[FileTarget]
    diff_files: list[DiffFile]
    selected_toolchains: dict[str, list[str]]
    raw_tool_results: list[ToolResult]
    normalized_findings: list[Finding]
    triaged_findings: list[Finding]
    llm_review_findings: list[Finding]
    static_findings: list[Finding]
    merged_findings: list[Finding]
    review_plans: list[RetrievalPlan]
    review_context_blocks: list[ContextBlock]

    # 输出
    report: Report

    # 运行信息 / 调试
    errors: list[str]
    logs: list[str]
