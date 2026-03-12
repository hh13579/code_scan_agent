from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_scan_agent.retrieval.retrievers.test_retriever import find_related_tests


class TestRetrieverTest(unittest.TestCase):
    def test_find_related_tests_uses_naming_convention_and_symbol(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)
            (repo_path / "src").mkdir()
            (repo_path / "tests").mkdir()
            (repo_path / "src" / "order_service.ts").write_text(
                "export function settleOrder(value: number) {\n  return value;\n}\n",
                encoding="utf-8",
            )
            (repo_path / "tests" / "order_service.test.ts").write_text(
                "import { settleOrder } from '../src/order_service';\n"
                "it('settles order', () => {\n"
                "  expect(settleOrder(1)).toBe(1);\n"
                "});\n",
                encoding="utf-8",
            )

            blocks = find_related_tests(
                repo_path=repo_path,
                file="src/order_service.ts",
                language="ts",
                patch="@@\n-export function settleOrder(value: number) {\n+export function settleOrder(value: number) {\n",
                function_context={"symbol": "settleOrder"},
            )

            self.assertEqual(len(blocks), 1)
            self.assertEqual(blocks[0]["kind"], "related_test")
            self.assertIn("settleOrder", blocks[0]["content"])


if __name__ == "__main__":
    unittest.main()
