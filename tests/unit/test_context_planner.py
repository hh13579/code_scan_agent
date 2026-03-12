from __future__ import annotations

import unittest

from code_scan_agent.retrieval.context_planner import plan_review_context
from code_scan_agent.retrieval.specs import RetrievalHints


class ContextPlannerTest(unittest.TestCase):
    def test_resource_lifecycle_plan_contains_evidence_roles(self) -> None:
        plan = plan_review_context(
            {
                "path": "src/resource_bridge.cpp",
                "language": "cpp",
                "patch": "+PtrArr<RGEvent_t> events(...);\n+RG_SetSomething(events);\n",
            },
            risk_score=8.5,
            reasons=["resource_lifecycle"],
            suspected_bug_classes=["resource_lifecycle"],
            class_reasons={"resource_lifecycle": ["signal:allocator_or_free", "signal:cleanup_terms"]},
            retrieval_hints={
                "resource_lifecycle": RetrievalHints(
                    symbol_candidates=("PtrArr", "RGEvent_t", "RG_SetSomething"),
                    cleanup_terms=("save", "release", "pool"),
                )
            },
        )

        roles = {item.evidence_role for item in plan.items}
        self.assertIn("changed_entrypoint", roles)
        self.assertIn("helper_definition", roles)
        self.assertIn("cleanup_path", roles)
        self.assertIn("sibling_baseline", roles)

    def test_stale_state_plan_contains_state_roles(self) -> None:
        plan = plan_review_context(
            {
                "path": "src/cache/session_cache.cpp",
                "language": "cpp",
                "patch": "+lastRouteId = routeId;\n+m_currentState = kReady;\n",
            },
            risk_score=6.0,
            reasons=["stale_state"],
            suspected_bug_classes=["stale_state"],
            class_reasons={"stale_state": ["signal:state_field", "signal:reset_path"]},
            retrieval_hints={
                "stale_state": RetrievalHints(
                    symbol_candidates=("lastRouteId", "m_currentState"),
                    state_terms=("last", "current", "state", "reset"),
                )
            },
        )

        roles = {item.evidence_role for item in plan.items}
        self.assertIn("state_write_point", roles)
        self.assertIn("state_reset_path", roles)
        self.assertIn("destructor_or_clear", roles)

    def test_same_bug_class_template_applies_to_different_patch_shapes(self) -> None:
        plans = [
            plan_review_context(
                {"path": f"src/file_{idx}.cpp", "language": "cpp", "patch": patch},
                suspected_bug_classes=["resource_lifecycle"],
                class_reasons={"resource_lifecycle": ["signal:allocator_or_free"]},
                retrieval_hints={"resource_lifecycle": RetrievalHints(symbol_candidates=("buffer",))},
            )
            for idx, patch in enumerate(
                [
                    "+char* buffer = strdup(name);\n+return buffer;\n",
                    "+auto ptr = createHandle();\n+return wrap(ptr);\n",
                ]
            )
        ]

        role_sets = [{item.evidence_role for item in plan.items} for plan in plans]
        self.assertEqual(role_sets[0], role_sets[1])


if __name__ == "__main__":
    unittest.main()
