from __future__ import annotations

import json
import os
import re
import time
from typing import Any
from urllib import error, request

from code_scan_agent.graph.state import GraphState


_SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


_VALID_SEVERITY = {"critical", "high", "medium", "low", "info"}
_VALID_CONFIDENCE = {"high", "medium", "low"}


def _get_int_env(name: str, default: int, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except ValueError:
            value = default

    if min_value is not None and value < min_value:
        return min_value
    return value


def _get_float_env(name: str, default: float, min_value: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            value = default

    if min_value is not None and value < min_value:
        return min_value
    return value


def _append_error(state: GraphState, message: str) -> None:
    bucket = state.get("errors")
    if not isinstance(bucket, list):
        bucket = []
        state["errors"] = bucket
    bucket.append(message)


def _local_triage(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    triaged: list[dict[str, Any]] = []
    for f in findings:
        enriched = dict(f)
        enriched["message"] = f"[triaged-local] {f.get('message', '')}"
        triaged.append(enriched)
    return triaged


def _build_api_url() -> str:
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    if base_url.endswith("/v1"):
        return f"{base_url}/chat/completions"
    return f"{base_url}/v1/chat/completions"


def _extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_+-]*\n?", "", stripped)
        stripped = re.sub(r"\n?```$", "", stripped)

    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{[\s\S]*\}", stripped)
    if not m:
        return {}

    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _call_deepseek(findings: list[dict[str, Any]]) -> dict[str, Any]:
    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")

    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    timeout_sec = _get_int_env("DEEPSEEK_TIMEOUT_SEC", 45, min_value=1)

    compact_findings = []
    for idx, f in enumerate(findings):
        compact_findings.append(
            {
                "idx": idx,
                "tool": str(f.get("tool", "")),
                "rule_id": str(f.get("rule_id", "")),
                "severity": str(f.get("severity", "info")).lower(),
                "file": str(f.get("file", "")),
                "line": f.get("line"),
                "message": str(f.get("message", ""))[:300],
            }
        )

    system_prompt = (
        "You are a senior secure code reviewer. "
        "Given findings, refine severity/confidence and rewrite message for actionability. "
        "Output strict JSON only."
    )
    user_prompt = (
        "Return JSON object with key 'triaged', value is a list of items.\n"
        "Each item fields: idx(int), severity(one of critical/high/medium/low/info), "
        "confidence(one of high/medium/low), category(string), message(string), "
        "autofix_available(boolean).\n"
        "Do not add extra keys at top level.\n\n"
        f"findings={json.dumps(compact_findings, ensure_ascii=False)}"
    )

    payload = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }

    req = request.Request(
        _build_api_url(),
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"DeepSeek HTTP {e.code}: {detail[:500]}") from e
    except error.URLError as e:
        raise RuntimeError(f"DeepSeek connection failed: {e}") from e

    try:
        api_json = json.loads(body)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"DeepSeek returned non-JSON body: {body[:300]}") from e

    try:
        content = api_json["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError(f"DeepSeek malformed response: {api_json}") from e

    triaged_json = _extract_json(str(content))
    if not isinstance(triaged_json, dict):
        raise RuntimeError("DeepSeek triage parse failed")
    return triaged_json


def _call_deepseek_with_retry(findings: list[dict[str, Any]]) -> dict[str, Any]:
    retry = _get_int_env("DEEPSEEK_RETRY", 1, min_value=0)
    backoff_sec = _get_float_env("DEEPSEEK_RETRY_BACKOFF_SEC", 1.0, min_value=0.0)
    last_error: Exception | None = None

    for attempt in range(retry + 1):
        try:
            return _call_deepseek(findings)
        except Exception as e:  # noqa: BLE001
            last_error = e
            if attempt >= retry:
                break
            time.sleep(backoff_sec * (attempt + 1))

    if last_error is None:
        raise RuntimeError("DeepSeek retry failed with unknown error")
    raise last_error


def _apply_triage(
    original: list[dict[str, Any]],
    triaged_json: dict[str, Any],
) -> list[dict[str, Any]]:
    triaged_list = triaged_json.get("triaged", [])
    if not isinstance(triaged_list, list):
        return _local_triage(original)

    by_idx: dict[int, dict[str, Any]] = {}
    for item in triaged_list:
        if not isinstance(item, dict):
            continue
        idx = item.get("idx")
        if isinstance(idx, int):
            by_idx[idx] = item

    result: list[dict[str, Any]] = []
    for idx, f in enumerate(original):
        out = dict(f)
        incoming = by_idx.get(idx, {})

        severity = str(incoming.get("severity", out.get("severity", "info"))).lower()
        if severity in _VALID_SEVERITY:
            out["severity"] = severity

        confidence = str(incoming.get("confidence", out.get("confidence", "high"))).lower()
        if confidence in _VALID_CONFIDENCE:
            out["confidence"] = confidence

        category = str(incoming.get("category", out.get("category", "static_analysis"))).strip()
        if category:
            out["category"] = category

        message = str(incoming.get("message", out.get("message", ""))).strip()
        if message:
            out["message"] = f"[triaged-llm] {message}"
        else:
            out["message"] = f"[triaged-local] {out.get('message', '')}"

        autofix = incoming.get("autofix_available")
        if isinstance(autofix, bool):
            out["autofix_available"] = autofix

        result.append(out)

    return result


def llm_triage(state: GraphState) -> GraphState:
    findings = list(state.get("normalized_findings", []))
    if not findings:
        state["triaged_findings"] = []
        state.setdefault("logs", []).append("llm_triage: no findings")
        return state

    request = state.get("request", {})
    mode = str(request.get("mode", "full"))
    req_enable_llm = request.get("enable_llm_triage")
    if isinstance(req_enable_llm, bool):
        enable_llm = req_enable_llm
    elif mode == "diff":
        enable_llm = _get_int_env("DIFF_ENABLE_LLM", 0, min_value=0) > 0
    else:
        enable_llm = True

    if not enable_llm:
        triaged = _local_triage(findings)
        state["triaged_findings"] = triaged
        state.setdefault("logs", []).append(
            f"llm_triage: disabled (mode={mode}), fallback_local={len(findings)}"
        )
        state.setdefault("logs", []).append(f"llm_triage: triaged={len(triaged)}")
        return state

    findings.sort(
        key=lambda x: (
            _SEVERITY_ORDER.get(x.get("severity", "info"), 99),
            x.get("file", ""),
            x.get("line") if x.get("line") is not None else 10**9,
        )
    )

    max_items = _get_int_env("DEEPSEEK_TRIAGE_MAX_ITEMS", 60, min_value=0)
    batch_size = _get_int_env("DEEPSEEK_BATCH_SIZE", 8, min_value=1)
    candidate = findings[:max_items]
    remaining = findings[max_items:]

    triaged_batches: list[dict[str, Any]] = []
    deepseek_ok = 0
    deepseek_failed = 0

    for i in range(0, len(candidate), batch_size):
        batch = candidate[i:i + batch_size]
        batch_id = i // batch_size + 1
        started_at = time.time()
        try:
            triaged_json = _call_deepseek_with_retry(batch)
            triaged_batches.extend(_apply_triage(batch, triaged_json))
            deepseek_ok += len(batch)
            state.setdefault("logs", []).append(
                f"llm_triage detail: batch={batch_id}, size={len(batch)}, status=ok, latency_sec={time.time() - started_at:.2f}"
            )
        except Exception as e:  # noqa: BLE001
            triaged_batches.extend(_local_triage(batch))
            deepseek_failed += len(batch)
            state.setdefault("logs", []).append(
                f"llm_triage detail: batch={batch_id}, size={len(batch)}, status=fallback, latency_sec={time.time() - started_at:.2f}, error_type={type(e).__name__}"
            )
            _append_error(
                state,
                f"llm_triage: DeepSeek failed on batch {batch_id}, fallback to local: {type(e).__name__}: {e}",
            )

    triaged = triaged_batches + _local_triage(remaining)
    state.setdefault("logs", []).append(
        "llm_triage: "
        f"deepseek_triaged={deepseek_ok}, "
        f"fallback_local={deepseek_failed + len(remaining)}, "
        f"batch_size={batch_size}"
    )

    state["triaged_findings"] = triaged
    state.setdefault("logs", []).append(f"llm_triage: triaged={len(triaged)}")
    return state
