from __future__ import annotations

from typing import Any


_SARIF_LEVEL_MAP = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
    "info": "note",
}


def _build_rule_index(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for item in findings:
        rule_id = str(item.get("rule_id", "") or "unknown")
        if rule_id in seen:
            continue
        seen[rule_id] = {
            "id": rule_id,
            "name": str(item.get("title", "") or rule_id),
            "shortDescription": {
                "text": str(item.get("category", "") or rule_id),
            },
            "properties": {
                "tool": str(item.get("tool", "") or "unknown"),
                "source": str(item.get("source", "") or item.get("tool", "") or "unknown"),
            },
        }
    return list(seen.values())


def render_sarif_report(report: dict[str, Any]) -> dict[str, Any]:
    findings = list(report.get("findings") or report.get("merged_findings") or [])
    results: list[dict[str, Any]] = []

    for item in findings:
        file_path = str(item.get("file", "") or "")
        line = item.get("line")
        evidence = item.get("evidence", [])
        if isinstance(evidence, str):
            evidence_text = evidence
        elif isinstance(evidence, list):
            evidence_text = " | ".join(str(part) for part in evidence if str(part).strip())
        else:
            evidence_text = ""
        location: dict[str, Any] | None = None
        if file_path:
            location = {
                "physicalLocation": {
                    "artifactLocation": {"uri": file_path},
                }
            }
            if isinstance(line, int) and line > 0:
                location["physicalLocation"]["region"] = {"startLine": line}

        result: dict[str, Any] = {
            "ruleId": str(item.get("rule_id", "") or "unknown"),
            "level": _SARIF_LEVEL_MAP.get(str(item.get("severity", "info")).lower(), "warning"),
            "message": {"text": str(item.get("message", "") or item.get("title", "") or "finding")},
            "properties": {
                "tool": str(item.get("tool", "") or "unknown"),
                "source": str(item.get("source", "") or item.get("tool", "") or "unknown"),
                "category": str(item.get("category", "") or ""),
                "confidence": str(item.get("confidence", "") or ""),
                "review_action": str(item.get("review_action", "") or ""),
                "impact": str(item.get("impact", "") or ""),
                "evidence": evidence_text,
                "suggested_action": str(item.get("suggested_action", "") or ""),
                "overlaps_static": bool(item.get("overlaps_static", False)),
            },
        }
        if location is not None:
            result["locations"] = [location]
        results.append(result)

    return {
        "version": "2.1.0",
        "$schema": "https://schemastore.azurewebsites.net/schemas/json/sarif-2.1.0-rtm.5.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "code_scan_agent",
                        "informationUri": "https://openai.com",
                        "rules": _build_rule_index(findings),
                    }
                },
                "results": results,
            }
        ],
    }
