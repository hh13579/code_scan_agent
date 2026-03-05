from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import TypedDict


class CommandResult(TypedDict, total=False):
    ok: bool
    cmd: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool
    error: str | None


def is_command_available(command: str) -> bool:
    """
    检查命令是否在 PATH 中可用。
    """
    return shutil.which(command) is not None


def run_command(
    cmd: list[str],
    cwd: str | Path | None = None,
    timeout_sec: int = 120,
    check: bool = False,
) -> CommandResult:
    """
    统一执行外部命令。
    - 捕获 stdout / stderr
    - 支持超时
    - 不默认抛异常（除非 check=True 且 exit_code != 0）
    """
    start = time.perf_counter()
    cwd_path = str(Path(cwd).resolve()) if cwd is not None else str(Path.cwd())

    try:
        completed = subprocess.run(
            cmd,
            cwd=cwd_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            check=False,
        )
        duration_ms = int((time.perf_counter() - start) * 1000)

        result: CommandResult = {
            "ok": completed.returncode == 0,
            "cmd": cmd,
            "cwd": cwd_path,
            "exit_code": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "duration_ms": duration_ms,
            "timed_out": False,
            "error": None,
        }

        if check and completed.returncode != 0:
            raise subprocess.CalledProcessError(
                completed.returncode,
                cmd,
                output=completed.stdout,
                stderr=completed.stderr,
            )

        return result

    except subprocess.TimeoutExpired as e:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return {
            "ok": False,
            "cmd": cmd,
            "cwd": cwd_path,
            "exit_code": -1,
            "stdout": e.stdout if isinstance(e.stdout, str) else "",
            "stderr": e.stderr if isinstance(e.stderr, str) else "",
            "duration_ms": duration_ms,
            "timed_out": True,
            "error": f"Command timed out after {timeout_sec}s",
        }
    except FileNotFoundError:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return {
            "ok": False,
            "cmd": cmd,
            "cwd": cwd_path,
            "exit_code": -1,
            "stdout": "",
            "stderr": "",
            "duration_ms": duration_ms,
            "timed_out": False,
            "error": f"Command not found: {cmd[0] if cmd else '<empty>'}",
        }
    except Exception as e:  # noqa: BLE001
        duration_ms = int((time.perf_counter() - start) * 1000)
        return {
            "ok": False,
            "cmd": cmd,
            "cwd": cwd_path,
            "exit_code": -1,
            "stdout": "",
            "stderr": "",
            "duration_ms": duration_ms,
            "timed_out": False,
            "error": f"{type(e).__name__}: {e}",
        }