from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


_SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

_REVIEW_ACTION_ZH = {
    "block": "阻塞合并",
    "should_fix": "建议本次修复",
    "follow_up": "建议后续跟进",
}
_VERIFICATION_STATUS_ZH = {
    "strengthened": "已增强",
    "unchanged": "未变化",
    "weak": "偏弱",
}


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _truncate(s: str, n: int = 160) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1] + "…"


def _as_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _sev_label(sev: str) -> str:
    return {
        "critical": "致命",
        "high": "高",
        "medium": "中",
        "low": "低",
        "info": "信息",
    }.get(sev, sev)


def _review_action_label(action: str) -> str:
    return _REVIEW_ACTION_ZH.get((action or "").strip(), action or "未说明")


def _verification_status_label(status: str) -> str:
    return _VERIFICATION_STATUS_ZH.get((status or "").strip(), status or "未校验")


def _status_from_summary(summary: dict[str, Any]) -> str:
    crit = _as_int(summary.get("critical", 0))
    high = _as_int(summary.get("high", 0))
    if crit > 0 or high > 0:
        return "❌ 不通过（存在致命/高优先级问题）"
    med = _as_int(summary.get("medium", 0))
    if med > 0:
        return "⚠️ 警告（存在中优先级问题）"
    return "✅ 通过（未发现阻塞问题）"


@dataclass
class ZhReportOptions:
    title: str = "代码静态扫描报告"
    max_findings_total: int = 200
    max_findings_per_file: int = 20
    max_files_in_summary: int = 30
    max_top_issues: int = 5
    show_tool: bool = True
    show_rule_id: bool = True
    show_summary_breakdown: bool = True
    show_source_summary: bool = True


def render_markdown_zh(report: dict[str, Any], opts: ZhReportOptions | None = None) -> str:
    """
    中文 Markdown 报告渲染器。
    兼容：
    - summary/findings/grouped_by_file/grouped_by_severity
    - static_summary / llm_review_summary / merged_summary
    - top_issues
    """
    opts = opts or ZhReportOptions()

    summary: dict[str, Any] = report.get("summary") or {}
    findings: list[dict[str, Any]] = report.get("findings") or []
    grouped_by_file: dict[str, list[dict[str, Any]]] = report.get("grouped_by_file") or {}

    static_summary: dict[str, Any] = report.get("static_summary") or {}
    llm_review_summary: dict[str, Any] = report.get("llm_review_summary") or {}
    merged_summary: dict[str, Any] = report.get("merged_summary") or summary

    static_findings: list[dict[str, Any]] = report.get("static_findings") or []
    llm_review_findings: list[dict[str, Any]] = report.get("llm_review_findings") or []
    top_issues: list[dict[str, Any]] = report.get("top_issues") or []

    def sort_key(f: dict[str, Any]):
        sev = str(f.get("severity", "info")).lower()
        file = str(f.get("file", ""))
        line = f.get("line")
        try:
            line_i = int(line) if line is not None else 10**9
        except Exception:
            line_i = 10**9
        source = str(f.get("source", ""))
        return (_SEV_ORDER.get(sev, 99), file, line_i, source)

    findings_sorted = sorted(findings, key=sort_key)[: opts.max_findings_total]
    # top_issues 已在 build_report 中按“最值得关注”排序，这里保留原顺序。
    top_issues_sorted = list(top_issues)[: opts.max_top_issues]

    lines: list[str] = []
    lines.append(f"# {opts.title}")
    lines.append("")
    lines.append(f"- 生成时间：{_now_str()}")
    lines.append(f"- 扫描结果：{_status_from_summary(summary)}")
    lines.append("")

    # 0. 最值得关注的问题（新加）
    lines.append("## 0. 本次最值得关注的问题")
    lines.append("")
    if not top_issues_sorted:
        lines.append("- 无特别需要优先关注的问题")
    else:
        lines.append("以下问题为本次变更中最值得优先查看和处理的事项：")
        lines.append("")
        for i, f in enumerate(top_issues_sorted, 1):
            lines.extend(_render_one_finding(f, i, opts))
    lines.append("")

    # 1. 摘要统计
    lines.append("## 1. 摘要统计")
    lines.append("")
    lines.append(f"- 总问题数：{_as_int(summary.get('total', len(findings)))}")
    lines.append(f"- 致命（critical）：{_as_int(summary.get('critical', 0))}")
    lines.append(f"- 高（high）：{_as_int(summary.get('high', 0))}")
    lines.append(f"- 中（medium）：{_as_int(summary.get('medium', 0))}")
    lines.append(f"- 低（low）：{_as_int(summary.get('low', 0))}")
    lines.append(f"- 信息（info）：{_as_int(summary.get('info', 0))}")
    lines.append("")

    if opts.show_source_summary:
        lines.append("### 1.1 分来源统计")
        lines.append("")
        lines.append(f"- 静态扫描：{_as_int(static_summary.get('total', len(static_findings)))} 条（仅作为 LLM 审查辅助证据，不单独展开）")
        lines.append(f"- LLM 语义审查：{_as_int(llm_review_summary.get('total', len(llm_review_findings)))} 条")
        lines.append(f"- 报告展示结果：{_as_int(merged_summary.get('total', len(findings)))} 条")
        lines.append("")

    # 2. 文件分布
    lines.append("## 2. 文件分布（Top）")
    lines.append("")
    file_counts = [(fp, len(lst)) for fp, lst in grouped_by_file.items()]
    file_counts.sort(key=lambda x: x[1], reverse=True)

    if not file_counts:
        lines.append("- 无问题")
    else:
        top_files = file_counts[: opts.max_files_in_summary]
        for fp, cnt in top_files:
            lines.append(f"- `{fp}`：{cnt} 条")
        if len(file_counts) > opts.max_files_in_summary:
            lines.append(f"- …（其余 {len(file_counts) - opts.max_files_in_summary} 个文件省略）")
    lines.append("")

    # 3. 高优先级问题
    lines.append("## 3. 高优先级问题（建议优先修复）")
    lines.append("")
    high_bucket = [
        f for f in findings_sorted
        if str(f.get("severity", "")).lower() in ("critical", "high")
        or str(f.get("review_action", "")).lower() == "block"
    ]

    if not high_bucket:
        lines.append("- 无致命/高优先级问题")
    else:
        for i, f in enumerate(high_bucket, 1):
            lines.extend(_render_one_finding(f, i, opts))
    lines.append("")

    # 4. LLM 语义审查补充
    lines.append("## 4. LLM 语义审查补充")
    lines.append("")
    if not llm_review_findings:
        lines.append("- 无 LLM 语义审查补充问题")
    else:
        llm_sorted = sorted(llm_review_findings, key=sort_key)[: opts.max_findings_total]
        for i, f in enumerate(llm_sorted, 1):
            lines.extend(_render_one_finding(f, i, opts))
        if len(llm_review_findings) > len(llm_sorted):
            lines.append(f"\n> 说明：LLM 语义审查问题共 {len(llm_review_findings)} 条，仅展示前 {len(llm_sorted)} 条。")
    lines.append("")

    # 5. 报告问题列表
    lines.append("## 5. 报告问题列表（仅展示 LLM 审查结果，按严重级排序，可能截断）")
    lines.append("")
    if not findings_sorted:
        lines.append("- 无问题")
    else:
        for i, f in enumerate(findings_sorted, 1):
            lines.extend(_render_one_finding(f, i, opts))
        if len(findings) > len(findings_sorted):
            lines.append(f"\n> 说明：问题总数 {len(findings)}，为避免过长仅展示前 {len(findings_sorted)} 条。")
    lines.append("")

    # 6. 按文件展开
    lines.append("## 6. 按文件展开（Top）")
    lines.append("")
    if not grouped_by_file:
        lines.append("- 无问题")
    else:
        for fp, _cnt in file_counts[: opts.max_files_in_summary]:
            flist = grouped_by_file.get(fp, [])
            flist_sorted = sorted(flist, key=sort_key)[: opts.max_findings_per_file]
            lines.append(f"### `{fp}`（{len(flist)} 条）")
            if not flist_sorted:
                lines.append("- 无")
                lines.append("")
                continue
            for i, f in enumerate(flist_sorted, 1):
                lines.extend(_render_one_finding(f, i, opts, compact=True))
            if len(flist) > len(flist_sorted):
                lines.append(f"\n> 该文件问题较多，仅展示前 {len(flist_sorted)} 条。")
            lines.append("")

    lines.append("---")
    lines.append("### 备注")
    lines.append("- 本报告由结构化扫描结果模板生成。")
    lines.append("- 静态分析结果默认仅用于辅助 LLM 判断，不在主报告中单独展开。")
    lines.append("- 建议优先处理：阻塞合并 / 致命 / 高优先级问题。")
    lines.append("- LLM 语义审查结果用于补充静态扫描难以发现的逻辑风险，不建议直接作为唯一 CI gate。")
    lines.append("")

    return "\n".join(lines)


def render_markdown_report_zh(
    report: dict[str, Any],
    opts: ZhReportOptions | None = None,
) -> str:
    """
    兼容旧调用入口。
    """
    return render_markdown_zh(report, opts)


def _render_one_finding(
    f: dict[str, Any],
    idx: int,
    opts: ZhReportOptions,
    compact: bool = False,
) -> list[str]:
    sev = str(f.get("severity", "info")).lower()
    file = str(f.get("file", ""))
    line = f.get("line")
    col = f.get("column")
    tool = str(f.get("tool", ""))
    rule = str(f.get("rule_id", ""))
    source = str(f.get("source", ""))
    category = str(f.get("category", ""))
    confidence = str(f.get("confidence", ""))
    title = str(f.get("title", "")).strip()
    message = _truncate(str(f.get("message", "")), 180 if not compact else 140)
    impact = _truncate(str(f.get("impact", "")), 180 if not compact else 140)
    review_action = str(f.get("review_action", "")).strip()
    verification_status = str(f.get("verification_status", "")).strip()
    suggested_action = _truncate(str(f.get("suggested_action", "")), 160 if not compact else 120)

    loc = file
    if line is not None:
        loc += f":{line}"
        if col is not None:
            loc += f":{col}"

    header_title = title if title else message
    header = f"{idx}. **[{_sev_label(sev)}]** `{loc}`"
    if header_title:
        header += f" — {header_title}"

    meta_parts = []
    if source:
        meta_parts.append(f"来源：`{source}`")
    if opts.show_tool and tool:
        meta_parts.append(f"工具：`{tool}`")
    if opts.show_rule_id and rule:
        meta_parts.append(f"规则：`{rule}`")
    if category:
        meta_parts.append(f"类别：`{category}`")
    if confidence:
        meta_parts.append(f"置信度：`{confidence}`")
    if review_action:
        meta_parts.append(f"建议动作：**{_review_action_label(review_action)}**")
    if verification_status:
        meta_parts.append(f"校验：`{_verification_status_label(verification_status)}`")

    out = [header]
    if meta_parts:
        out.append("   - " + "；".join(meta_parts))

    if message:
        out.append(f"   - 问题：{message}")

    if impact:
        out.append(f"   - 影响：{impact}")

    if suggested_action:
        out.append(f"   - 建议：{suggested_action}")

    evidence = f.get("evidence", [])
    shown: list[str] = []
    if isinstance(evidence, list):
        shown = [str(x).strip() for x in evidence if str(x).strip()][:3]
    elif isinstance(evidence, str) and evidence.strip():
        shown = [evidence.strip()]
    if shown:
        out.append("   - 证据：")
        for ev in shown:
            out.append(f"     - {ev}")

    verification_notes = f.get("verification_notes", [])
    if isinstance(verification_notes, str):
        verification_notes = [verification_notes] if verification_notes.strip() else []
    shown_notes = [str(x).strip() for x in verification_notes if str(x).strip()][:3]
    if shown_notes:
        out.append("   - 校验说明：")
        for note in shown_notes:
            out.append(f"     - {note}")

    return out
