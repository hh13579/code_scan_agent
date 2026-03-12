from __future__ import annotations

import unittest

from code_scan_agent.nodes.build_report import build_report


class BuildReportMergedTest(unittest.TestCase):
    def test_build_report_prefers_llm_report_view_and_keeps_split_summaries(self) -> None:
        state = {
            "static_findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 10,
                    "severity": "high",
                    "category": "memory",
                    "tool": "cppcheck",
                    "message": "Static finding",
                }
            ],
            "llm_review_findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 12,
                    "bug_class": "resource_lifecycle",
                    "severity": "medium",
                    "category": "semantic-review",
                    "tool": "llm_diff_review",
                    "evidence_completeness": "complete",
                    "key_evidence_summary": ["allocation point", "missing cleanup"],
                    "message": "LLM finding",
                }
            ],
            "merged_findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 12,
                    "bug_class": "resource_lifecycle",
                    "severity": "medium",
                    "category": "semantic-review",
                    "tool": "llm_diff_review",
                    "evidence_completeness": "complete",
                    "key_evidence_summary": ["allocation point", "missing cleanup"],
                    "message": "LLM finding",
                },
            ],
            "logs": [],
        }

        result = build_report(state)  # type: ignore[arg-type]
        report = result["report"]

        self.assertEqual(report["summary"]["total"], 1)
        self.assertEqual(report["static_summary"]["total"], 1)
        self.assertEqual(report["llm_review_summary"]["total"], 1)
        self.assertEqual(report["merged_summary"]["total"], 1)
        self.assertEqual(report["findings"], result["merged_findings"])
        self.assertIn("merged_grouped_by_file", report)
        self.assertIn("merged_grouped_by_severity", report)
        self.assertIn("top_issues", report)
        self.assertEqual(report["bug_class_summary"]["resource_lifecycle"], 1)
        self.assertEqual(report["evidence_completeness_summary"]["complete"], 1)

    def test_build_report_stays_compatible_without_merged_findings(self) -> None:
        state = {
            "triaged_findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 1,
                    "severity": "low",
                    "category": "style",
                    "tool": "cppcheck",
                    "message": "Old path",
                }
            ],
            "logs": [],
        }

        result = build_report(state)  # type: ignore[arg-type]
        report = result["report"]

        self.assertEqual(report["summary"]["total"], 1)
        self.assertEqual(report["findings"], state["triaged_findings"])
        self.assertEqual(report["merged_summary"]["total"], 1)
        self.assertIn("merged_grouped_by_file", report)

    def test_build_report_hides_static_only_findings_when_merge_stage_ran(self) -> None:
        state = {
            "static_findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 10,
                    "severity": "high",
                    "category": "memory",
                    "tool": "cppcheck",
                    "message": "Static finding",
                }
            ],
            "llm_review_findings": [],
            "merged_findings": [],
            "logs": [],
        }

        result = build_report(state)  # type: ignore[arg-type]
        report = result["report"]

        self.assertEqual(report["summary"]["total"], 0)
        self.assertEqual(report["findings"], [])
        self.assertEqual(report["static_summary"]["total"], 1)
        self.assertEqual(report["llm_review_summary"]["total"], 0)

    def test_top_issues_prioritize_strengthened_findings(self) -> None:
        state = {
            "llm_review_findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 30,
                    "severity": "low",
                    "review_action": "follow_up",
                    "verification_status": "unchanged",
                    "category": "semantic-review",
                    "tool": "llm_diff_review",
                    "message": "Later finding",
                    "impact": "Some impact",
                    "evidence": ["diff"],
                },
                {
                    "file": "src/demo.cpp",
                    "line": 10,
                    "severity": "low",
                    "review_action": "follow_up",
                    "verification_status": "strengthened",
                    "category": "semantic-review",
                    "tool": "llm_diff_review",
                    "message": "First finding",
                    "impact": "Some impact",
                    "evidence": ["diff"],
                },
            ],
            "merged_findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 30,
                    "severity": "low",
                    "review_action": "follow_up",
                    "verification_status": "unchanged",
                    "category": "semantic-review",
                    "tool": "llm_diff_review",
                    "message": "Later finding",
                    "impact": "Some impact",
                    "evidence": ["diff"],
                },
                {
                    "file": "src/demo.cpp",
                    "line": 10,
                    "severity": "low",
                    "review_action": "follow_up",
                    "verification_status": "strengthened",
                    "category": "semantic-review",
                    "tool": "llm_diff_review",
                    "message": "First finding",
                    "impact": "Some impact",
                    "evidence": ["diff"],
                },
            ],
            "logs": [],
        }

        result = build_report(state)  # type: ignore[arg-type]

        self.assertEqual(result["report"]["top_issues"][0]["verification_status"], "strengthened")


if __name__ == "__main__":
    unittest.main()
