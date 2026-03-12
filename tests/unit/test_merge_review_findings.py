from __future__ import annotations

import unittest

from code_scan_agent.nodes.merge_review_findings import merge_review_findings


class MergeReviewFindingsTest(unittest.TestCase):
    def test_merge_marks_overlap_and_reports_only_llm_findings(self) -> None:
        state = {
            "triaged_findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 10,
                    "category": "memory",
                    "severity": "high",
                    "message": "Static finding",
                    "tool": "cppcheck",
                }
            ],
            "llm_review_findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 11,
                    "category": "memory",
                    "severity": "high",
                    "message": "LLM finding",
                    "tool": "llm_diff_review",
                },
                {
                    "file": "src/other.cpp",
                    "line": 20,
                    "category": "api",
                    "severity": "medium",
                    "message": "Another LLM finding",
                    "tool": "llm_diff_review",
                },
            ],
            "logs": [],
        }

        result = merge_review_findings(state)  # type: ignore[arg-type]

        self.assertEqual(len(result["static_findings"]), 1)
        self.assertEqual(len(result["llm_review_findings"]), 2)
        self.assertEqual(len(result["merged_findings"]), 2)
        self.assertTrue(result["llm_review_findings"][0]["overlaps_static"])

    def test_merge_without_llm_results_is_empty_report_set(self) -> None:
        state = {
            "triaged_findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 10,
                    "category": "memory",
                    "severity": "high",
                    "message": "Static finding",
                    "tool": "cppcheck",
                }
            ],
            "llm_review_findings": [],
            "logs": [],
        }

        result = merge_review_findings(state)  # type: ignore[arg-type]

        self.assertEqual(result["static_findings"], state["triaged_findings"])
        self.assertEqual(result["merged_findings"], [])


if __name__ == "__main__":
    unittest.main()
