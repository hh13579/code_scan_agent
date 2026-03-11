from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_scan_agent.nodes.review_diff_with_llm import review_diff_with_llm


def _base_state(repo_path: Path) -> dict[str, object]:
    return {
        "request": {
            "repo_path": str(repo_path),
            "mode": "diff",
        },
        "repo_profile": {
            "repo_path": str(repo_path),
            "languages": ["cpp", "ts"],
        },
        "diff_files": [
            {
                "path": "src/demo.cpp",
                "language": "cpp",
                "status": "M",
                "changed_lines": [2, 3],
                "patch": "diff --git a/src/demo.cpp b/src/demo.cpp\n@@ -2 +2,2 @@\n-return a + b;\n+const int sum = a + b;\n+return sum;\n",
                "hunks": ["@@ -2 +2,2 @@\n-return a + b;\n+const int sum = a + b;\n+return sum;\n"],
            }
        ],
        "triaged_findings": [],
        "errors": [],
        "logs": [],
    }


class ReviewDiffWithLlmTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        repo_path = Path(self.temp_dir.name)
        (repo_path / "src").mkdir()
        (repo_path / "src" / "demo.cpp").write_text("int add(int a, int b) {\n    return a + b;\n}\n", encoding="utf-8")
        self.repo_path = repo_path

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_no_llm_skips_review(self) -> None:
        state = _base_state(self.repo_path)
        state["request"]["enable_llm_triage"] = False

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        self.assertEqual(result["llm_review_findings"], [])
        self.assertIn("review_diff_with_llm: skipped (--no-llm)", result["logs"])

    @patch("code_scan_agent.nodes.review_diff_with_llm._call_llm_diff_review")
    def test_mock_llm_response_produces_structured_findings(self, mock_call) -> None:
        mock_call.return_value = json.dumps(
            {
                "summary": {"overall_risk": "medium", "notes": ["check pointer lifetime"]},
                "findings": [
                    {
                        "file": "src/demo.cpp",
                        "line": 2,
                        "severity": "high",
                        "category": "memory",
                        "title": "Potential lifetime issue",
                        "message": "Returned reference may outlive local storage.",
                        "confidence": "high",
                        "evidence": "New code introduces a local temporary.",
                        "suggested_action": "Return by value or store data in owned storage.",
                    }
                ],
            },
            ensure_ascii=False,
        )
        state = _base_state(self.repo_path)

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        findings = result["llm_review_findings"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["tool"], "llm_diff_review")
        self.assertEqual(findings[0]["severity"], "high")
        self.assertEqual(findings[0]["file"], "src/demo.cpp")
        self.assertEqual(findings[0]["rule_id"], "semantic-review")

    @patch("code_scan_agent.nodes.review_diff_with_llm._call_llm_diff_review")
    def test_dirty_json_falls_back_to_empty_findings(self, mock_call) -> None:
        mock_call.return_value = "not-json-response"
        state = _base_state(self.repo_path)

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        self.assertEqual(result["llm_review_findings"], [])
        self.assertTrue(any("parse failed" in item.lower() for item in result["errors"]))

    def test_missing_diff_files_skips_review(self) -> None:
        state = _base_state(self.repo_path)
        state["diff_files"] = []

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        self.assertEqual(result["llm_review_findings"], [])
        self.assertIn("review_diff_with_llm: skipped (no diff_files)", result["logs"])


if __name__ == "__main__":
    unittest.main()
