from __future__ import annotations

import unittest

from code_scan_agent.nodes.build_report import build_report


class BuildReportMergedTest(unittest.TestCase):
    def test_build_report_prefers_merged_findings_and_keeps_split_summaries(self) -> None:
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
                    "severity": "medium",
                    "category": "semantic-review",
                    "tool": "llm_diff_review",
                    "message": "LLM finding",
                }
            ],
            "merged_findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 10,
                    "severity": "high",
                    "category": "memory",
                    "tool": "cppcheck",
                    "message": "Static finding",
                },
                {
                    "file": "src/demo.cpp",
                    "line": 12,
                    "severity": "medium",
                    "category": "semantic-review",
                    "tool": "llm_diff_review",
                    "message": "LLM finding",
                },
            ],
            "logs": [],
        }

        result = build_report(state)  # type: ignore[arg-type]
        report = result["report"]

        self.assertEqual(report["summary"]["total"], 2)
        self.assertEqual(report["static_summary"]["total"], 1)
        self.assertEqual(report["llm_review_summary"]["total"], 1)
        self.assertEqual(report["merged_summary"]["total"], 2)
        self.assertEqual(report["findings"], result["merged_findings"])
        self.assertIn("merged_grouped_by_file", report)
        self.assertIn("merged_grouped_by_severity", report)
        self.assertIn("top_issues", report)

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


if __name__ == "__main__":
    unittest.main()
