from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """你是一个资深代码审查工程师，负责基于代码 diff 进行“语义层”的变更审查。

你的任务不是重复静态扫描工具的结果，也不是做风格检查，而是识别“真正值得工程师采取行动”的高价值问题。

你要重点识别的问题类型：
1. 逻辑回归
2. 边界条件错误
3. 接口契约不一致
4. 状态管理、缓存、一致性、副作用问题
5. 异常处理遗漏
6. 重构导致的调用链遗漏
7. 配置、默认值、条件判断变化带来的行为改变
8. 可能影响线上稳定性的风险

你的输出目标不是“穷举潜在问题”，而是“筛出最值得关注的问题”。

严格遵守以下原则：
- 仅基于提供的 diff 和上下文做判断
- 如果证据不足，不要武断下结论，应降低 severity 和 confidence，或直接不输出
- 不要编造不存在的代码、变量、接口、业务背景或调用链
- 不要重复静态扫描工具已经擅长发现的纯规则问题，除非它与语义风险直接相关
- 不要输出纯风格、命名、格式、注释类问题
- 不要输出空泛建议，例如“建议补测试”“建议关注这里”
- 每个 finding 必须说明“为什么有问题”以及“可能导致什么具体后果”
- 每个 finding 必须引用至少 1 条具体证据（diff 或上下文）
- 如果无法指出明确行为后果，就不要输出该 finding
- 只输出值得工程师采取行动的问题
- 输出必须是严格 JSON，不要输出 markdown，不要输出额外解释
"""


OUTPUT_SCHEMA_TEXT = """请严格输出如下 JSON，对象字段必须完整，禁止输出 JSON 之外的任何内容：

{
  "summary": {
    "overall_risk": "low | medium | high",
    "review_confidence": "low | medium | high",
    "merge_recommendation": "approve | caution | block"
  },
  "findings": [
    {
      "severity": "high | medium | low",
      "review_action": "block | should_fix | follow_up",
      "category": "logic_regression | boundary_condition | contract_mismatch | exception_handling | state_consistency | concurrency | config_behavior_change | partial_refactor | other",
      "file": "string",
      "line": 123,
      "title": "一句话标题",
      "message": "说明问题本身，必须结合 diff 和上下文，不要空泛。",
      "impact": "说明这个问题可能导致什么具体行为错误、稳定性风险或业务影响。",
      "confidence": "low | medium | high",
      "evidence": [
        "引用哪一处 diff 或上下文支持你的判断"
      ],
      "suggested_action": "建议工程师如何验证、修复或进一步确认"
    }
  ]
}

硬约束：
- 最多输出 8 条 findings
- 如果没有发现高价值问题，返回 findings: []
- file 必须是提供的改动文件路径之一
- line 必须尽量对应新代码侧的行号；如果无法确定，可以写 null
- severity 不要滥用 high，只有在明显可能导致行为错误、稳定性问题或高风险回归时才使用 high
- review_action 含义：
  - block：建议阻塞合并
  - should_fix：建议本次修复
  - follow_up：建议后续跟踪，不阻塞本次合并
- 如果 evidence 不能明确支持结论，请降低 confidence，或不要输出该 finding
- 如果某条问题只是“有一点可疑”，但没有明确后果，请不要输出
"""


def _safe_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def build_diff_review_prompt(
    *,
    repo_name: str,
    base_ref: str,
    head_ref: str,
    changed_files: list[str],
    diff_blocks: list[dict[str, Any]],
    static_findings: list[dict[str, Any]] | None = None,
    extra_context_blocks: list[dict[str, Any]] | None = None,
    max_findings: int = 8,
) -> str:
    """
    生成单字符串 prompt，适合直接发给 chat/completions 接口。

    diff_blocks 每项建议形如：
    {
      "file": "src/foo.ts",
      "patch": "... unified diff ...",
      "language": "ts"
    }

    static_findings 每项建议形如：
    {
      "file": "src/foo.ts",
      "line": 12,
      "severity": "medium",
      "tool": "eslint",
      "rule_id": "no-unused-vars",
      "message": "..."
    }

    extra_context_blocks 每项建议形如：
    {
      "file": "src/foo.ts",
      "kind": "function_context" | "type_definition" | "related_code",
      "content": "..."
    }
    """
    static_findings = static_findings or []
    extra_context_blocks = extra_context_blocks or []

    diff_text_parts: list[str] = []
    for block in diff_blocks:
        file = str(block.get("file", "")).strip()
        language = str(block.get("language", "")).strip()
        patch = str(block.get("patch", "")).rstrip()

        if not file or not patch:
            continue

        section = [f"### File: {file}"]
        if language:
            section.append(f"Language: {language}")
        section.append("```diff")
        section.append(patch)
        section.append("```")
        diff_text_parts.append("\n".join(section))

    static_text_parts: list[str] = []
    for item in static_findings:
        file = item.get("file")
        line = item.get("line")
        severity = item.get("severity")
        tool = item.get("tool")
        rule_id = item.get("rule_id")
        message = item.get("message")
        static_text_parts.append(
            f"- {file}:{line} [{severity}] {tool} / {rule_id} / {message}"
        )

    context_text_parts: list[str] = []
    for item in extra_context_blocks:
        file = str(item.get("file", "")).strip()
        kind = str(item.get("kind", "")).strip()
        content = str(item.get("content", "")).rstrip()

        if not file or not content:
            continue

        section = [f"### Context File: {file}"]
        if kind:
            section.append(f"Context Type: {kind}")
        section.append("```")
        section.append(content)
        section.append("```")
        context_text_parts.append("\n".join(section))

    prompt = f"""[TASK]
请对以下代码变更做“语义审查”，你的目标不是穷举所有潜在问题，而是输出“最值得工程师采取行动的问题”。

请优先识别以下高价值风险：
- 改动引入的逻辑回归
- 边界条件变化导致的行为偏差
- 接口契约变化但调用链未完全同步
- 默认值、异常处理、配置条件变化导致的行为改变
- 状态一致性、缓存、副作用问题
- 局部重构导致的遗漏修改
- 静态扫描难以发现、但从变更语义上值得重点关注的问题

请不要输出以下低价值内容：
- 纯风格、格式、命名、注释问题
- 没有明确行为后果的问题
- 证据不足的泛化猜测
- 与静态扫描结果重复、且没有新增解释价值的问题
- “建议补测试”“建议关注这里”之类空泛结论

本次最多输出 {max_findings} 条高价值 findings。

[REVIEW_META]
repo: {repo_name}
base_ref: {base_ref}
head_ref: {head_ref}
changed_files_count: {len(changed_files)}

[CHANGED_FILES]
{_safe_json(changed_files)}

[STATIC_FINDINGS]
{"无" if not static_text_parts else chr(10).join(static_text_parts)}

说明：
- 静态扫描结果仅作为辅助参考
- 不要重复纯规则问题
- 如果静态扫描结果与语义风险直接相关，可以引用并补充其行为后果

[DIFF]
{"无" if not diff_text_parts else chr(10).join(diff_text_parts)}

[EXTRA_CONTEXT]
{"无" if not context_text_parts else chr(10).join(context_text_parts)}

[DECISION_RULES]
你必须站在“代码审查决策”的角度输出问题：
- 这个问题是否会导致行为错误、稳定性风险或明显回归？
- 这个问题是否值得阻塞合并？
- 如果不值得阻塞，是否仍建议本次修复？
- 如果只是低置信度提醒，应标为 follow_up，而不是 block

review_action 定义：
- block：建议阻塞合并
- should_fix：建议本次修复
- follow_up：建议后续跟进，不阻塞本次合并

[IMPORTANT_CONSTRAINTS]
- 仅基于提供的 diff 和上下文做判断
- 不要臆测未提供的业务背景
- 如果证据不足，请降低 severity 和 confidence，或不要输出
- 每个 finding 必须说明具体行为后果（impact）
- 每个 finding 必须提供至少 1 条 evidence
- 只保留值得工程师采取行动的问题
- 如果没有发现高价值问题，返回 findings: []

[OUTPUT_SCHEMA]
{OUTPUT_SCHEMA_TEXT}
"""
    return prompt


def build_diff_review_messages(
    *,
    repo_name: str,
    base_ref: str,
    head_ref: str,
    changed_files: list[str],
    diff_blocks: list[dict[str, Any]],
    static_findings: list[dict[str, Any]] | None = None,
    extra_context_blocks: list[dict[str, Any]] | None = None,
    max_findings: int = 8,
) -> list[dict[str, str]]:
    """
    生成 chat messages，适合 OpenAI / DeepSeek Chat API。
    """
    user_prompt = build_diff_review_prompt(
        repo_name=repo_name,
        base_ref=base_ref,
        head_ref=head_ref,
        changed_files=changed_files,
        diff_blocks=diff_blocks,
        static_findings=static_findings,
        extra_context_blocks=extra_context_blocks,
        max_findings=max_findings,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]