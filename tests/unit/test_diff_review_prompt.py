from __future__ import annotations

import unittest

from code_scan_agent.prompts.diff_review_prompt import build_diff_review_prompt


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
                {
                    "file": "src/callers/demo_controller.cpp",
                    "subject_file": "src/new_demo.cpp",
                    "kind": "call_site",
                    "content": "if (ready) {\n    call_demo();\n}\n",
                }
            ],
        )

        self.assertIn("## Review File: src/new_demo.cpp", prompt)
        self.assertIn("Old Path: src/old_demo.cpp", prompt)
        self.assertIn("### Related Context", prompt)
        self.assertIn("#### call_site (src/callers/demo_controller.cpp)", prompt)
        self.assertIn("对于 rename / move / partial refactor 类 patch", prompt)


if __name__ == "__main__":
    unittest.main()
