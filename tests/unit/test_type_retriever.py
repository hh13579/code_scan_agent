from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_scan_agent.retrieval.retrievers.type_retriever import get_related_types


class TypeRetrieverTest(unittest.TestCase):
    def test_get_related_types_extracts_type_definition_from_current_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)
            target = repo_path / "src" / "order_service.ts"
            target.parent.mkdir(parents=True)
            target.write_text(
                "export interface Order {\n"
                "  id: string;\n"
                "  amount: number;\n"
                "}\n\n"
                "export function settleOrder(order: Order) {\n"
                "  return order.amount;\n"
                "}\n",
                encoding="utf-8",
            )

            blocks = get_related_types(
                repo_path=repo_path,
                file="src/order_service.ts",
                language="ts",
                patch="@@\n-export function settleOrder(order: Order) {\n+export function settleOrder(order: Order) {\n",
            )

            self.assertEqual(len(blocks), 1)
            self.assertEqual(blocks[0]["kind"], "type_definition")
            self.assertEqual(blocks[0]["symbol"], "Order")
            self.assertIn("interface Order", blocks[0]["content"])


if __name__ == "__main__":
    unittest.main()
