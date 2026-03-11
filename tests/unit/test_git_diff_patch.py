from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from code_scan_agent.tools.repo.git_diff import get_git_diff_files


class GitDiffPatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_path = Path(self.temp_dir.name)
        self._run_git("init")
        self._run_git("config", "user.email", "codex@example.com")
        self._run_git("config", "user.name", "Codex")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _run_git(self, *args: str) -> None:
        subprocess.run(
            ["git", "-C", str(self.repo_path), *args],
            check=True,
            capture_output=True,
            text=True,
        )

    def test_get_git_diff_files_returns_patch_hunks_and_changed_lines(self) -> None:
        (self.repo_path / "src").mkdir()
        (self.repo_path / "src" / "demo.cpp").write_text("int add(int a, int b) {\n    return a + b;\n}\n", encoding="utf-8")
        (self.repo_path / "src" / "old.ts").write_text("export const oldValue = 1;\n", encoding="utf-8")
        self._run_git("add", ".")
        self._run_git("commit", "-m", "initial")

        (self.repo_path / "src" / "demo.cpp").write_text(
            "int add(int a, int b) {\n    const int sum = a + b;\n    return sum;\n}\n",
            encoding="utf-8",
        )
        self._run_git("mv", "src/old.ts", "src/new_name.ts")
        (self.repo_path / "src" / "app.ts").write_text("export const value = 2;\n", encoding="utf-8")
        self._run_git("add", ".")
        self._run_git("commit", "-m", "second")

        diff_files = get_git_diff_files(
            repo_path=self.repo_path,
            base_ref="HEAD~1",
            head_ref="HEAD",
            mode="triple",
            exclude_deleted=True,
        )

        by_path = {item["path"]: item for item in diff_files}
        self.assertIn("src/demo.cpp", by_path)
        self.assertIn("src/new_name.ts", by_path)
        self.assertIn("src/app.ts", by_path)

        demo = by_path["src/demo.cpp"]
        self.assertEqual(demo["status"], "M")
        self.assertEqual(demo["changed_lines"], [2, 3])
        self.assertTrue(demo["patch"].startswith("diff --git"))
        self.assertTrue(demo["hunks"])
        self.assertIn("@@ -2 +2,2 @@", demo["hunks"][0])

        renamed = by_path["src/new_name.ts"]
        self.assertEqual(renamed["status"], "R")
        self.assertEqual(renamed["old_path"], "src/old.ts")


if __name__ == "__main__":
    unittest.main()
