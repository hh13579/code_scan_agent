from __future__ import annotations

import unittest

from code_scan_agent.nodes.verify_review_findings import verify_review_findings


class VerifyReviewFindingsTest(unittest.TestCase):
    def test_verify_review_findings_marks_strengthened_and_weak(self) -> None:
        state = {
            "llm_review_findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 10,
                    "severity": "high",
                    "review_action": "block",
                    "evidence": ["diff evidence"],
                },
                {
                    "file": "src/weak.cpp",
                    "line": 20,
                    "severity": "medium",
                    "review_action": "should_fix",
                    "evidence": [],
                },
            ],
            "review_context_blocks": [
                {
                    "file": "src/demo.cpp",
                    "subject_file": "src/demo.cpp",
                    "kind": "function_context",
                    "content": "int demo() { return 1; }",
                },
                {
                    "file": "tests/demo_test.cpp",
                    "subject_file": "src/demo.cpp",
                    "kind": "related_test",
                    "content": "TEST(Demo, Works) {}",
                },
            ],
            "logs": [],
        }

        result = verify_review_findings(state)  # type: ignore[arg-type]

        self.assertEqual(result["llm_review_findings"][0]["verification_status"], "strengthened")
        self.assertEqual(result["llm_review_findings"][1]["verification_status"], "weak")
        self.assertTrue(any("checked=2" in line for line in result["logs"]))


if __name__ == "__main__":
    unittest.main()
