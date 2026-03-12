from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_scan_agent.retrieval.retrievers.function_retriever import get_function_context


class FunctionRetrieverTest(unittest.TestCase):
    def test_get_function_context_returns_enclosing_function(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)
            target = repo_path / "src" / "demo.cpp"
            target.parent.mkdir(parents=True)
            target.write_text(
                "int helper() {\n"
                "    return 1;\n"
                "}\n\n"
                "int compute(int value) {\n"
                "    if (value > 1) {\n"
                "        return value + helper();\n"
                "    }\n"
                "    return value;\n"
                "}\n",
                encoding="utf-8",
            )

            block = get_function_context(
                repo_path=repo_path,
                file="src/demo.cpp",
                language="cpp",
                changed_lines=[6],
            )

            self.assertIsNotNone(block)
            self.assertEqual(block["kind"], "function_context")
            self.assertEqual(block["symbol"], "compute")
            self.assertIn("return value + helper();", block["content"])


if __name__ == "__main__":
    unittest.main()
