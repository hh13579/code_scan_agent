from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_scan_agent.nodes.collect_targets import collect_targets


class CollectTargetsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)
        (self.repo_path / "src").mkdir()
        (self.repo_path / "src" / "demo.cpp").write_text("int main() { return 0; }\n", encoding="utf-8")
        (self.repo_path / "src" / "demo.pb.h").write_text("// generated\n", encoding="utf-8")
        (self.repo_path / "src" / "demo.pb.cc").write_text("// generated\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _base_state(self, mode: str) -> dict[str, object]:
        return {
            "request": {
                "repo_path": str(self.repo_path),
                "mode": mode,
            },
            "repo_profile": {
                "repo_path": str(self.repo_path),
                "languages": ["cpp"],
            },
            "logs": [],
            "errors": [],
        }

    def test_full_mode_skips_generated_protobuf_files(self) -> None:
        state = self._base_state("full")

        result = collect_targets(state)  # type: ignore[arg-type]

        target_paths = sorted(Path(item["path"]).name for item in result["targets"])
        self.assertEqual(target_paths, ["demo.cpp"])
        self.assertTrue(any("skipped_generated=2" in line for line in result["logs"]))

    @patch("code_scan_agent.nodes.collect_targets.get_git_diff_files")
    def test_diff_mode_skips_generated_protobuf_files(self, mock_get_git_diff_files) -> None:
        mock_get_git_diff_files.return_value = [
            {
                "path": "src/demo.cpp",
                "status": "M",
                "changed_lines": [1],
                "patch": "diff --git a/src/demo.cpp b/src/demo.cpp\n@@ -1 +1 @@\n-int a;\n+int b;\n",
                "hunks": ["@@ -1 +1 @@\n-int a;\n+int b;\n"],
                "old_path": "",
            },
            {
                "path": "src/demo.pb.h",
                "status": "M",
                "changed_lines": [1],
                "patch": "diff --git a/src/demo.pb.h b/src/demo.pb.h\n@@ -1 +1 @@\n-old\n+new\n",
                "hunks": ["@@ -1 +1 @@\n-old\n+new\n"],
                "old_path": "",
            },
        ]
        state = self._base_state("diff")
        state["request"]["base_ref"] = "HEAD~1"  # type: ignore[index]
        state["request"]["head_ref"] = "HEAD"  # type: ignore[index]

        result = collect_targets(state)  # type: ignore[arg-type]

        self.assertEqual([item["path"] for item in result["diff_files"]], ["src/demo.cpp"])
        target_paths = sorted(Path(item["path"]).name for item in result["targets"])
        self.assertEqual(target_paths, ["demo.cpp"])


if __name__ == "__main__":
    unittest.main()
