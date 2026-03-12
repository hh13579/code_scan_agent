from __future__ import annotations

import unittest

from code_scan_agent.retrieval.risk_ranker import rank_diff_risk


class RiskRankerTest(unittest.TestCase):
    def test_rank_diff_risk_returns_top_five_in_priority_order(self) -> None:
        diff_files = [
            {
                "path": f"src/demo_{idx}.ts",
                "language": "ts",
                "patch": "if (value >= 0) {\n  return 0;\n}\n" if idx == 0 else f"const value = {idx};\n",
                "changed_lines": [1, 2] if idx == 0 else [1],
            }
            for idx in range(6)
        ]
        triaged_findings = [
            {"file": "src/demo_0.ts", "severity": "high"},
            {"file": "src/demo_2.ts", "severity": "low"},
        ]

        ranked = rank_diff_risk(diff_files, triaged_findings=triaged_findings)

        self.assertEqual(len(ranked), 5)
        self.assertEqual(ranked[0]["path"], "src/demo_0.ts")
        self.assertIn("conditional_change", ranked[0]["reasons"])
        self.assertIn("static_high", ranked[0]["reasons"])
        self.assertIsInstance(ranked[0]["suspected_bug_classes"], list)
        self.assertIsInstance(ranked[0]["class_reasons"], dict)
        self.assertIsInstance(ranked[0]["retrieval_hints"], dict)

    def test_rank_diff_risk_prioritizes_resource_lifecycle_patterns(self) -> None:
        diff_files = [
            {
                "path": "src/resource.cpp",
                "language": "cpp",
                "patch": (
                    "+PtrArr<RGEvent_t> events(pb.event());\n"
                    "+pb2c(dst, src);\n"
                    "+RG_SetCodeSection(handle, routeId, tag, endPoint, events.cnt, events);\n"
                ),
                "changed_lines": [1, 2],
            },
            {
                "path": "src/plain.cpp",
                "language": "cpp",
                "patch": "+int value = 1;\n",
                "changed_lines": [1],
            },
        ]

        ranked = rank_diff_risk(diff_files, max_items=2)

        self.assertEqual(ranked[0]["path"], "src/resource.cpp")
        self.assertIn("resource_lifecycle", ranked[0]["reasons"])
        self.assertIn("resource_lifecycle", ranked[0]["suspected_bug_classes"])
        self.assertIn("ownership_mismatch", ranked[0]["suspected_bug_classes"])
        self.assertIn("signal:helper_alloc_like", ranked[0]["class_reasons"]["resource_lifecycle"])
        hints = ranked[0]["retrieval_hints"]["resource_lifecycle"]
        self.assertIn("PtrArr", hints.symbol_candidates)
        self.assertIn("RGEvent_t", hints.symbol_candidates)
        self.assertIn("pb2c", hints.symbol_candidates)

    def test_rank_diff_risk_detects_stale_state_class_without_function_name_special_case(self) -> None:
        diff_files = [
            {
                "path": "src/session_cache.cpp",
                "language": "cpp",
                "patch": (
                    "+lastRouteId = routeId;\n"
                    "+m_currentState = kReady;\n"
                    "+if (needSwitch) {\n"
                    "+  return;\n"
                    "+}\n"
                ),
                "changed_lines": [1, 2, 3],
            }
        ]

        ranked = rank_diff_risk(diff_files, max_items=1)

        self.assertEqual(ranked[0]["path"], "src/session_cache.cpp")
        self.assertIn("stale_state", ranked[0]["suspected_bug_classes"])
        self.assertIn("signal:state_field", ranked[0]["class_reasons"]["stale_state"])


if __name__ == "__main__":
    unittest.main()
