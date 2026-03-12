from __future__ import annotations

import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from code_scan_agent.tools.shell_runner import run_command


def _run_git(repo_path: Path, args: list[str]) -> None:
    result = run_command(["git", "-C", str(repo_path), *args], cwd=repo_path, timeout_sec=180, check=False)
    if result.get("error"):
        raise RuntimeError(str(result["error"]))
    if int(result.get("exit_code", 0)) != 0:
        stderr = str(result.get("stderr", "")).strip()
        raise RuntimeError(stderr or f"git exited with {result.get('exit_code')}")


@contextmanager
def detached_ref_workspace(repo_path: str | Path, git_ref: str) -> Iterator[Path]:
    source_repo = Path(repo_path).expanduser().resolve()
    temp_dir = Path(tempfile.mkdtemp(prefix="code_scan_agent_ref_"))
    cleanup_error: Exception | None = None

    try:
        _run_git(source_repo, ["worktree", "add", "--detach", "--force", str(temp_dir), git_ref])
        yield temp_dir
    finally:
        try:
            _run_git(source_repo, ["worktree", "remove", "--force", str(temp_dir)])
        except Exception as exc:  # noqa: BLE001
            cleanup_error = exc
        shutil.rmtree(temp_dir, ignore_errors=True)
        if cleanup_error is not None:
            raise cleanup_error
