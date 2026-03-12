from __future__ import annotations

import unittest

from code_scan_agent.prompts.diff_review_prompt import build_diff_review_prompt
from code_scan_agent.retrieval.specs import ContextBlock, RetrievalHints, RetrievalPlan, RetrievalPlanItem


class DiffReviewPromptTest(unittest.TestCase):
    def test_prompt_groups_context_by_subject_file(self) -> None:
        prompt = build_diff_review_prompt(
            repo_name="demo",
            base_ref="origin/main",
            head_ref="HEAD",
            changed_files=["R src/old_demo.cpp -> src/new_demo.cpp"],
            diff_blocks=[
                {
                    "file": "src/new_demo.cpp",
                    "old_path": "src/old_demo.cpp",
                    "status": "R",
                    "language": "cpp",
                    "patch": "diff --git a/src/old_demo.cpp b/src/new_demo.cpp\n@@ -1 +1 @@\n-old\n+new\n",
                }
            ],
            extra_context_blocks=[
                ContextBlock(
                    file="src/callers/demo_controller.cpp",
                    subject_file="src/new_demo.cpp",
                    kind="call_site",
                    content="if (ready) {\n    call_demo();\n}\n",
                    bug_class="contract_drift",
                    evidence_role="call_sites",
                    hop=2,
                    source_path="src/callers/demo_controller.cpp",
                    why_selected="Need callers to validate contract compatibility.",
                )
            ],
            retrieval_plans=[
                RetrievalPlan(
                    file="src/new_demo.cpp",
                    language="cpp",
                    suspected_bug_classes=("contract_drift",),
                    class_reasons={"contract_drift": ("signal:public_api",)},
                    retrieval_hints={"contract_drift": RetrievalHints(symbol_candidates=("call_demo",))},
                    items=(
                        RetrievalPlanItem(
                            bug_class="contract_drift",
                            evidence_role="call_sites",
                            hop=2,
                            why_selected="Need callers to validate contract compatibility.",
                            hints=RetrievalHints(symbol_candidates=("call_demo",)),
                        ),
                    ),
                    hop_strategy=("hop1", "hop2"),
                    why_selected=("contract_drift suspected",),
                )
            ],
        )

        self.assertIn("## Review File: src/new_demo.cpp", prompt)
        self.assertIn("Old Path: src/old_demo.cpp", prompt)
        self.assertIn("### Related Context", prompt)
        self.assertIn("#### call_site (src/callers/demo_controller.cpp)", prompt)
        self.assertIn("Bug Class Hypothesis & Evidence Plan", prompt)
        self.assertIn("Suspected Bug Classes: contract_drift", prompt)
        self.assertIn("hypothesis-driven", prompt.lower())
        self.assertIn("对于 rename / move / partial refactor 类 patch", prompt)
        self.assertIn("resource_lifecycle", prompt)
        self.assertIn("ownership_mismatch", prompt)
        self.assertIn("deep_free_missing", prompt)
        self.assertIn("wrapper_bypasses_existing_cleanup", prompt)
        self.assertIn("stale_state", prompt)
        self.assertIn("key_evidence_roles", prompt)
        self.assertIn("evidence_completeness", prompt)
        self.assertIn("memory leak / resource leak / ownership mismatch", prompt)
        self.assertIn("wrapper -> api -> manager -> data_mgr -> pool/cache/destroy path", prompt)
        self.assertIn("pb2c 可能为事件内部字段做深层堆分配", prompt)
        self.assertIn("PtrArr<T> 仅管理外层数组生命周期", prompt)
        self.assertIn("RG_SetCodeSection 与 RG_SetMarkers", prompt)


if __name__ == "__main__":
    unittest.main()
