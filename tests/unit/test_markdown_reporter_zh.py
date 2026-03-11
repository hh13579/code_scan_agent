from __future__ import annotations

import unittest

from code_scan_agent.reporters.markdown_reporter_zh import (
    render_markdown_report_zh,
    render_markdown_zh,
)


class MarkdownReporterZhTest(unittest.TestCase):
    def test_backward_compatible_entrypoint_matches_new_renderer(self) -> None:
        report = {
            "summary": {"total": 1, "critical": 0, "high": 1, "medium": 0, "low": 0, "info": 0},
            "findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 10,
                    "severity": "high",
                    "review_action": "block",
                    "title": "Potential regression",
                    "message": "New branch may skip validation.",
                    "impact": "Requests may bypass validation and return incorrect results.",
                    "evidence": ["Added early return before validation."],
                    "source": "llm_diff_review",
                }
            ],
            "grouped_by_file": {"src/demo.cpp": [{"file": "src/demo.cpp"}]},
            "static_summary": {"total": 0},
            "llm_review_summary": {"total": 1},
            "merged_summary": {"total": 1},
            "llm_review_findings": [],
            "top_issues": [],
        }

        legacy = render_markdown_report_zh(report)
        current = render_markdown_zh(report)

        self.assertEqual(legacy, current)
        self.assertIn("## 0. 本次最值得关注的问题", legacy)

    def test_top_issues_order_and_string_evidence_are_preserved(self) -> None:
        report = {
            "summary": {"total": 2, "critical": 0, "high": 1, "medium": 1, "low": 0, "info": 0},
            "findings": [],
            "grouped_by_file": {},
            "static_summary": {"total": 0},
            "llm_review_summary": {"total": 2},
            "merged_summary": {"total": 2},
            "llm_review_findings": [],
            "top_issues": [
                {
                    "file": "src/medium_block.cpp",
                    "line": 20,
                    "severity": "medium",
                    "review_action": "block",
                    "title": "Block first",
                    "message": "Must remain first.",
                    "impact": "Can break core flow.",
                    "evidence": "Single string evidence.",
                    "source": "llm_diff_review",
                },
                {
                    "file": "src/high_followup.cpp",
                    "line": 10,
                    "severity": "high",
                    "review_action": "follow_up",
                    "title": "Second",
                    "message": "Should stay second.",
                    "impact": "May affect edge cases.",
                    "evidence": ["List evidence."],
                    "source": "llm_diff_review",
                },
            ],
        }

        rendered = render_markdown_zh(report)

        self.assertLess(rendered.index("Block first"), rendered.index("Second"))
        self.assertIn("Single string evidence.", rendered)


if __name__ == "__main__":
    unittest.main()
