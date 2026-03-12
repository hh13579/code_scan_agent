from __future__ import annotations

import unittest
from pathlib import Path

from code_scan_agent.tools.deepseek_cn_report import _build_cn_findings, build_payload, render_markdown


class DeepseekCnReportTest(unittest.TestCase):
    def test_build_payload_reads_code_context_from_git_ref(self) -> None:
        repo_path = Path("/Users/didi/work/sdk-env/navi-engine-v2").resolve()
        report = {
            "summary": {"total": 1, "high": 1, "medium": 0, "low": 0, "info": 0, "critical": 0},
            "findings": [
                {
                    "file": "dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_peak_fusion_strategy.cpp",
                    "line": 178,
                    "severity": "high",
                    "tool": "llm_diff_review",
                    "source": "llm_diff_review",
                    "rule_id": "semantic-review",
                    "title": "demo",
                    "message": "demo message",
                    "impact": "demo impact",
                    "confidence": "high",
                    "review_action": "block",
                    "evidence": ["demo evidence"],
                }
            ],
        }

        payload = build_payload(
            report=report,
            log_text="",
            repo_path=repo_path,
            display_repo_path=repo_path,
            base_ref="feature/driver/v9.2.12",
            head_ref="feature/driver/v9.2.14",
            context_lines=5,
            diff_context=5,
            max_findings=5,
        )

        self.assertIn("fused_peaks.front()", payload["findings"][0]["code_context"])
        self.assertNotIn("file not found", payload["findings"][0]["code_context"])
        self.assertTrue(payload["scan_meta"]["head_sha"])

    def test_render_markdown_shows_display_count_and_snapshot_note(self) -> None:
        payload = {
            "scan_meta": {
                "repo_path": "/repo",
                "effective_repo_path": "/tmp/ref_repo",
                "base_ref": "origin/main",
                "head_ref": "feature/demo",
                "head_sha": "abc1234567890",
                "current_checkout_ref": "feature/old",
                "current_checkout_sha": "def9876543210",
                "is_historical_snapshot": True,
            },
            "report_summary": {"total": 30, "high": 0, "medium": 1, "low": 29, "info": 0, "critical": 0},
            "displayed_findings_count": 20,
            "total_findings_count": 30,
            "key_logs": [],
            "findings": [],
        }
        analysis = {
            "title": "报告",
            "summary": {
                "scope": "demo",
                "overall_risk": "低",
                "conclusion": "demo conclusion",
                "tool_observations": [],
                "coverage_limits": [],
            },
            "findings": [],
            "next_actions": [],
        }

        markdown = render_markdown(analysis, payload, generated_by="DeepSeek")

        self.assertIn("head_sha=`abc1234567890`", markdown)
        self.assertIn("前 `20` 条 / 共 `30` 条", markdown)
        self.assertIn("历史快照", markdown)

    def test_cn_findings_preserve_structured_llm_fields(self) -> None:
        payload = {
            "findings": [
                {
                    "file": "src/demo.cpp",
                    "line": 10,
                    "severity": "high",
                    "tool": "llm_diff_review",
                    "source": "llm_diff_review",
                    "rule_id": "semantic-review",
                    "title": "Potential regression",
                    "message": "New branch may skip validation.",
                    "impact": "Requests may bypass validation.",
                    "confidence": "high",
                    "review_action": "block",
                    "evidence": ["Added early return before validation."],
                    "suggested_action": "Restore validation before return.",
                }
            ]
        }

        findings = _build_cn_findings(payload)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["judgement"], "建议修复")
        self.assertEqual(findings[0]["review_action"], "block")
        self.assertEqual(findings[0]["impact"], "Requests may bypass validation.")
        self.assertEqual(findings[0]["evidence"], ["Added early return before validation."])
        self.assertEqual(findings[0]["fix_advice"], "Restore validation before return.")


if __name__ == "__main__":
    unittest.main()
