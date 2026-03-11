from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = (
    "You are a senior code reviewer focused on semantic regressions in diffs. "
    "Review only the provided changed files and diff blocks. "
    "Prefer real bugs, behavior regressions, memory/resource issues, API misuse, "
    "and missing validation over style nitpicks. "
    "Output strict JSON only."
)


def build_diff_review_prompt(
    *,
    repo_name: str,
    base_ref: str,
    head_ref: str,
    changed_files: list[dict[str, Any]],
    diff_blocks: list[dict[str, Any]],
    static_findings: list[dict[str, Any]],
    extra_context_blocks: list[dict[str, Any]] | None = None,
    max_findings: int = 10,
) -> str:
    payload = {
        "repo_name": repo_name,
        "base_ref": base_ref,
        "head_ref": head_ref,
        "changed_files": changed_files,
        "diff_blocks": diff_blocks,
        "static_findings": static_findings,
        "extra_context_blocks": extra_context_blocks or [],
        "max_findings": max_findings,
    }
    return (
        "Review the diff and return strict JSON.\n"
        "Top-level keys must be: summary, findings.\n"
        "summary must be an object with keys: overall_risk, notes.\n"
        "findings must be an array of objects with keys: "
        "file, line, severity, category, title, message, confidence, evidence, suggested_action.\n"
        "Rules:\n"
        "1. severity must be one of critical/high/medium/low/info.\n"
        "2. confidence must be one of high/medium/low.\n"
        "3. Only report actionable issues tied to the provided diff.\n"
        "4. If nothing actionable is found, return findings as an empty array.\n"
        "5. Do not return markdown, prose outside JSON, or code fences.\n\n"
        f"input={json.dumps(payload, ensure_ascii=False)}"
    )


def build_diff_review_messages(
    *,
    repo_name: str,
    base_ref: str,
    head_ref: str,
    changed_files: list[dict[str, Any]],
    diff_blocks: list[dict[str, Any]],
    static_findings: list[dict[str, Any]],
    extra_context_blocks: list[dict[str, Any]] | None = None,
    max_findings: int = 10,
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": build_diff_review_prompt(
                repo_name=repo_name,
                base_ref=base_ref,
                head_ref=head_ref,
                changed_files=changed_files,
                diff_blocks=diff_blocks,
                static_findings=static_findings,
                extra_context_blocks=extra_context_blocks,
                max_findings=max_findings,
            ),
        },
    ]
