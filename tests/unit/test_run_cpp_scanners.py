from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from code_scan_agent.nodes.run_cpp_scanners import _build_filtered_compile_db


class RunCppScannersTest(unittest.TestCase):
    def test_filtered_compile_db_drops_generated_protobuf_units(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)
            compile_db_path = repo_path / "compile_commands.json"
            (repo_path / "src").mkdir()
            compile_db_path.write_text(
                json.dumps(
                    [
                        {
                            "directory": str(repo_path),
                            "file": "src/demo.cpp",
                            "command": "c++ -c src/demo.cpp",
                        },
                        {
                            "directory": str(repo_path),
                            "file": "src/demo.pb.cc",
                            "command": "c++ -c src/demo.pb.cc",
                        },
                    ]
                ),
                encoding="utf-8",
            )

            filtered_path, logs = _build_filtered_compile_db(
                repo_path=repo_path,
                compile_db_path=str(compile_db_path),
                include_files=["src/demo.cpp", "src/demo.pb.cc"],
            )

            self.assertIsNotNone(filtered_path)
            self.assertTrue(any("kept=1/2" in line for line in logs))
            filtered = json.loads(Path(filtered_path).read_text(encoding="utf-8"))
            self.assertEqual([entry["file"] for entry in filtered], ["src/demo.cpp"])
            Path(filtered_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
