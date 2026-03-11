from __future__ import annotations

from typing import Any


def _summary_value(summary: dict[str, Any], key: str) -> int:
    try:
        return int(summary.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def render_markdown_report_zh(report: dict[str, Any]) -> str:
    summary = dict(report.get("summary", {}))
    static_summary = dict(report.get("static_summary", summary))
    llm_review_summary = dict(report.get("llm_review_summary", {}))
    merged_summary = dict(report.get("merged_summary", summary))
    findings = list(report.get("findings", []))

    lines = [
        "# 代码扫描报告",
        "",
        "## 摘要",
        f"- 总计：{_summary_value(summary, 'total')} 条",
        f"- 静态扫描：{_summary_value(static_summary, 'total')} 条",
        f"- LLM语义审查：{_summary_value(llm_review_summary, 'total')} 条",
        f"- 合并结果：{_summary_value(merged_summary, 'total')} 条",
        f"- 严重级别分布：critical={_summary_value(summary, 'critical')}, high={_summary_value(summary, 'high')}, medium={_summary_value(summary, 'medium')}, low={_summary_value(summary, 'low')}, info={_summary_value(summary, 'info')}",
        "",
        "## Findings",
    ]

    if not findings:
        lines.append("- 无")
        return "\n".join(lines) + "\n"

    for index, item in enumerate(findings, start=1):
        file_path = str(item.get("file", "") or "(unknown)")
        line = item.get("line")
        location = f"{file_path}:{line}" if line else file_path
        lines.extend(
            [
                f"### {index}. {str(item.get('severity', 'info')).lower()} | {location}",
                f"- 来源：{item.get('source') or item.get('tool') or 'unknown'}",
                f"- 类别：{item.get('category', '') or 'unknown'}",
                f"- 规则：{item.get('rule_id', '') or 'unknown'}",
                f"- 标题：{item.get('title', '') or item.get('message', '') or '无'}",
                f"- 说明：{item.get('message', '') or '无'}",
                f"- 置信度：{item.get('confidence', '') or 'unknown'}",
            ]
        )
        if item.get("evidence"):
            lines.append(f"- 证据：{item.get('evidence')}")
        if item.get("suggested_action"):
            lines.append(f"- 建议：{item.get('suggested_action')}")
        if item.get("overlaps_static"):
            lines.append("- 备注：与静态扫描结果存在重叠")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
