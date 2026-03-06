# Code Scan Agent - AI Coding Guidelines

## Overview
This is a LangGraph-orchestrated multi-language code scanner supporting C++, Java, TypeScript, and security scans. It normalizes findings from various tools and uses LLM (DeepSeek) for triage and prioritization.

## Architecture
- **Graph Flow**: `discover_repo` → `collect_targets` → `choose_toolchains` → language scanners → `normalize_findings` → `llm_triage` → `build_report`
- **State Management**: All nodes operate on `GraphState` TypedDict, passing data immutably
- **Fallback**: Pure Python execution if LangGraph unavailable
- **Modes**: `full` (repo scan), `diff` (git changes), `selected` (single file)

## Key Workflows
- **Run Scan**: `python3 main.py /path/to/repo [--mode diff --diff-commit <hash>] > report.json`
- **Setup**: `export DEEPSEEK_API_KEY=sk-...; export PATH="/opt/homebrew/opt/llvm/bin:$PATH"`
- **Diff Mode**: Automatically filters findings to changed lines using `git diff`
- **Single File**: `python3 main.py /path/to/file.cpp` (auto-detects repo root)

## Conventions
- **Node Functions**: Pure functions `def node(state: GraphState) -> GraphState`, append to `errors`/`logs` lists
- **Tool Integration**: Wrap external commands in `ToolResult` with `success`, `exit_code`, `stdout`/`stderr`
- **LLM Triage**: Batch findings to DeepSeek API with retry/backoff; fallback to local rules if API fails
- **Path Handling**: Always use absolute paths in state, relative in reports; exclude `build/`, `node_modules/`, etc.
- **Config**: Extensive env vars (e.g., `DEEPSEEK_TIMEOUT_SEC=90`, `CLANG_TIDY_TIMEOUT_SEC=60`)
- **Error Handling**: Continue processing on failures, log errors but don't abort

## Examples
- **Add New Scanner**: Create `nodes/run_xyz_scanners.py`, add to `builder.py` routing, return `ToolResult` list
- **Finding Normalization**: Map tool-specific severity to `critical|high|medium|low|info`, add `category` from rule_id/message
- **LLM Prompt**: Compress findings to `tool/rule_id/severity/file/line/message`, request re-severity + explanation

Reference: [ARCHITECTURE_REPORT.md](ARCHITECTURE_REPORT.md) for detailed design rationale.