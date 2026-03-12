from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_scan_agent.nodes.run_security_scanners import _build_semgrep_cmd


class RunSecurityScannersTest(unittest.TestCase):
    def test_semgrep_cmd_excludes_generated_protobuf_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)
            state = {
                "request": {
                    "repo_path": str(repo_path),
                    "mode": "full",
                },
                "targets": [],
            }

            cmd = _build_semgrep_cmd(repo_path, state)  # type: ignore[arg-type]

            self.assertIn("--exclude", cmd)
            self.assertIn("*.pb.h", cmd)
            self.assertIn("*.pb.cc", cmd)


if __name__ == "__main__":
    unittest.main()
