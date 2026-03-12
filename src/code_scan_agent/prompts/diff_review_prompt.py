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
8. 资源生命周期 / 所有权 / 内存泄露 / 句柄泄露 / 池化与缓存回收链断裂
9. 可能影响线上稳定性的风险

你的输出目标不是“穷举潜在问题”，而是“筛出最值得关注的问题”。

严格遵守以下原则：
- 仅基于提供的 diff 和上下文做判断
- 如果证据不足，不要武断下结论，应降低 severity 和 confidence，或直接不输出
- 不要编造不存在的代码、变量、接口、业务背景或调用链
- 不要重复静态扫描工具已经擅长发现的纯规则问题，除非它与语义风险直接相关
- 资源生命周期、所有权错配、内存泄露、句柄泄露、池化/缓存回收链断裂不属于“纯规则问题”，它们属于高价值语义风险
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
      "bug_class": "resource_lifecycle | ownership_mismatch | stale_state | contract_drift | partial_init_outward_struct | semantic_misuse | sibling_api_asymmetry | error_path_cleanup_missing | other",
      "severity": "high | medium | low",
      "review_action": "block | should_fix | follow_up",
      "category": "logic_regression | boundary_condition | contract_mismatch | exception_handling | state_consistency | concurrency | config_behavior_change | partial_refactor | resource_lifecycle | ownership_mismatch | deep_free_missing | wrapper_bypasses_existing_cleanup | stale_state | contract_drift | partial_init_outward_struct | semantic_misuse | sibling_api_asymmetry | error_path_cleanup_missing | other",
      "file": "string",
      "line": 123,
      "title": "一句话标题",
      "message": "说明问题本身，必须结合 diff 和上下文，不要空泛。",
      "impact": "说明这个问题可能导致什么具体行为错误、稳定性风险或业务影响。",
      "confidence": "low | medium | high",
      "key_evidence_roles": [
        "changed_entrypoint",
        "cleanup_path"
      ],
      "evidence_completeness": "partial | strong | complete",
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
- bug_class 与 category 尽量保持一致；如果 category 偏通用，bug_class 仍应指向最可能的问题类别
- key_evidence_roles 需要列出你实际使用到的关键证据角色
- evidence_completeness:
  - partial：只拿到局部证据，不足以完全闭环
  - strong：已有两段关键证据，但仍缺少一个次级环节
  - complete：证据链基本闭环，足以支撑明确结论
- 对于 resource_lifecycle 类 finding，evidence 至少要同时覆盖：
  1. 分配点 / 所有权引入点 / 托管入口
  2. 缺失的释放 / 销毁 / 回收 / 交接证据
"""


def _safe_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def _get_value(item: Any, name: str, default: Any = "") -> Any:
    if isinstance(item, dict):
        return item.get(name, default)
    return getattr(item, name, default)


def _group_blocks_by_subject(
    diff_blocks: list[dict[str, Any]],
    extra_context_blocks: list[Any],
) -> tuple[list[str], dict[str, list[dict[str, Any]]], dict[str, list[dict[str, Any]]]]:
    ordered_files: list[str] = []
    diff_by_file: dict[str, list[dict[str, Any]]] = {}
    context_by_subject: dict[str, list[dict[str, Any]]] = {}

    for block in diff_blocks:
        file_path = str(block.get("file", "")).strip()
        if not file_path:
            continue
        if file_path not in diff_by_file:
            ordered_files.append(file_path)
            diff_by_file[file_path] = []
        diff_by_file[file_path].append(block)

    for item in extra_context_blocks:
        file_path = str(_get_value(item, "file", "")).strip()
        subject_file = str(_get_value(item, "subject_file", "")).strip() or file_path
        if not subject_file or not file_path:
            continue
        context_by_subject.setdefault(subject_file, []).append(
            item if isinstance(item, dict) else item.to_dict()
        )
        if subject_file not in diff_by_file and subject_file not in ordered_files:
            ordered_files.append(subject_file)

    return ordered_files, diff_by_file, context_by_subject


def _group_plans_by_file(retrieval_plans: list[Any]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for plan in retrieval_plans:
        file_path = str(_get_value(plan, "file", "")).strip()
        if not file_path:
            continue
        suspected_bug_classes = list(_get_value(plan, "suspected_bug_classes", ()) or ())
        items = list(_get_value(plan, "items", ()) or ())
        lines: list[str] = []
        if suspected_bug_classes:
            lines.append(f"Suspected Bug Classes: {', '.join(suspected_bug_classes)}")
        for item in items:
            lines.append(
                f"- hop{_get_value(item, 'hop', 0)} / {_get_value(item, 'bug_class', 'generic_review')} / "
                f"{_get_value(item, 'evidence_role', '')}: {_get_value(item, 'why_selected', '')}"
            )
        grouped[file_path] = lines
    return grouped


def build_diff_review_prompt(
    *,
    repo_name: str,
    base_ref: str,
    head_ref: str,
    changed_files: list[str],
    diff_blocks: list[dict[str, Any]],
    static_findings: list[dict[str, Any]] | None = None,
    extra_context_blocks: list[Any] | None = None,
    retrieval_plans: list[Any] | None = None,
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
    retrieval_plans = retrieval_plans or []

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

    ordered_files, diff_by_file, context_by_subject = _group_blocks_by_subject(diff_blocks, extra_context_blocks)
    plans_by_file = _group_plans_by_file(retrieval_plans)
    review_units: list[str] = []
    for file in ordered_files:
        file_diff_blocks = diff_by_file.get(file, [])
        file_context_blocks = context_by_subject.get(file, [])
        file_plans = plans_by_file.get(file, [])
        if not file_diff_blocks and not file_context_blocks:
            continue

        section = [f"## Review File: {file}"]
        if file_plans:
            section.append("### Bug Class Hypothesis & Evidence Plan")
            section.extend(file_plans)
        if file_diff_blocks:
            first = file_diff_blocks[0]
            status = str(first.get("status", "")).strip()
            old_path = str(first.get("old_path", "")).strip()
            language = str(first.get("language", "")).strip()
            if status:
                section.append(f"Status: {status}")
            if old_path and old_path != file:
                section.append(f"Old Path: {old_path}")
            if language:
                section.append(f"Language: {language}")
            for index, block in enumerate(file_diff_blocks, start=1):
                patch = str(block.get("patch", "")).rstrip()
                if not patch:
                    continue
                section.append(f"### Diff Block {index}")
                section.append("```diff")
                section.append(patch)
                section.append("```")
        if file_context_blocks:
            section.append("### Related Context")
            for item in file_context_blocks:
                source_file = str(item.get("file", "")).strip()
                kind = str(item.get("kind", "")).strip()
                bug_class = str(item.get("bug_class", "")).strip()
                evidence_role = str(item.get("evidence_role", "")).strip()
                hop = str(item.get("hop", "")).strip()
                why_selected = str(item.get("why_selected", "")).strip()
                content = str(item.get("content", "")).rstrip()
                if not source_file or not content:
                    continue
                header = f"#### {kind or 'context'}"
                if source_file != file:
                    header += f" ({source_file})"
                if bug_class or evidence_role or hop:
                    header += f" [bug_class={bug_class or 'generic_review'}, role={evidence_role or 'context'}, hop={hop or '?'}]"
                section.append(header)
                if why_selected:
                    section.append(f"Why Selected: {why_selected}")
                section.append("```")
                section.append(content)
                section.append("```")
        review_units.append("\n".join(section))

    prompt = f"""[TASK]
请对以下代码变更做“语义审查”，你的目标不是穷举所有潜在问题，而是输出“最值得工程师采取行动的问题”。

请优先识别以下高价值风险：
- 改动引入的逻辑回归
- 边界条件变化导致的行为偏差
- 接口契约变化但调用链未完全同步
- 默认值、异常处理、配置条件变化导致的行为改变
- 状态一致性、缓存、副作用问题
- 局部重构导致的遗漏修改
- 资源生命周期 / 所有权 / 内存泄露 / 句柄泄露 / pool-cache-clear-destroy 链断裂
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
- memory leak / resource leak / ownership mismatch 不要视为“纯规则问题”，这类问题应进入高价值 findings

[HYPOTHESIS_DRIVEN_REVIEW]
请按 hypothesis-driven review 的流程审查：
1. 先基于 diff 和 evidence plan 判断“最可能的 bug class”
2. 再检查该 bug class 的证据链是否闭环
3. 只有在关键证据角色满足最小要求时，才能给出较高 confidence 或较高 severity
4. 如果证据链不完整，请降低 confidence，并把 evidence_completeness 标成 partial 或 strong

重点 bug class 的最小证据要求：
- resource_lifecycle / ownership_mismatch
  - 至少有 allocation / ownership 引入点证据
  - 至少有 cleanup / clear / destroy 缺失或不对称证据
- stale_state
  - 至少有状态写入点
  - 至少有 reset / clear / end / destructor 缺失证据
- contract_drift
  - 至少有 declaration 与 implementation 或 call site 的不一致
- partial_init_outward_struct
  - 至少有类型定义
  - 至少有部分初始化
  - 至少有 outward exposure
- semantic_misuse
  - 至少有值来源
  - 至少有值消费者
  - 至少有 domain invariant 或 sibling baseline

[DIFF_AND_CONTEXT_BY_FILE]
{"无" if not review_units else chr(10).join(review_units)}

[DECISION_RULES]
你必须站在“代码审查决策”的角度输出问题：
- 这个问题是否会导致行为错误、稳定性风险或明显回归？
- 这个问题是否值得阻塞合并？
- 如果不值得阻塞，是否仍建议本次修复？
- 如果只是低置信度提醒，应标为 follow_up，而不是 block
- 对资源生命周期问题，不要因为“像是内存规则问题”就忽略；如果能指出所有权断裂、释放链缺失或热路径泄露，应把它当成和逻辑回归同级的高价值风险
- 对 resource_lifecycle / ownership_mismatch / deep_free_missing / wrapper_bypasses_existing_cleanup，不要把它们当成“静态扫描重复项”；这类问题本身就是高价值审查结论

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
- 对于 rename / move / partial refactor 类 patch，不能仅凭“某段旧代码被删掉了”就断言行为回归；必须结合新代码、调用方上下文或迁移后的实现一起判断
- 如果提供的调用点上下文已经显示调用方保证了某个前置条件，不要把“被调函数内部少了一层同类保护”直接判成 high 或 block，除非你还能指出该函数在提供的上下文里存在其他未受保护入口
- 如果某个 helper / 类型 / 处理逻辑只是从当前文件迁移出去，而不是明确消失，不要把它写成行为回归
- 如果 diff 中涉及资源分配、托管、释放、回收、池化、缓存、句柄关闭、pb2c/parse/decode/clone/create 等模式，你必须主动检查资源生命周期，而不是只看表层逻辑
- 对新增或修改的资源链，必须明确检查：
  1. 分配点在哪里
  2. 谁接管所有权
  3. 正常路径是否释放
  4. 异常路径 / 早返回路径是否释放
  5. 深层字段、数组元素、子对象是否也被释放
  6. 新接口是否绕过了旧接口已有的 save/release/pool/clear/destroy 机制
- 对 helper / 转换器 / wrapper 的隐式分配要保持敏感：pb2c / parse / decode / clone / create / bridge API 也可能引入所有权，而不是只有裸 new/malloc 才算分配点
- 如果某个 helper 会隐式分配资源，也要把它当成分配点；不要只盯裸 new/malloc
- 要主动检查跨层 ownership 是否断裂：wrapper -> api -> manager -> data_mgr -> pool/cache/destroy path 是否一致
- 如果判断的是 resource_lifecycle 问题，evidence 至少应同时覆盖“分配或所有权引入点”和“缺失的托管/释放/销毁证据”
- 对每次请求、每次算路、每次事件构造、热循环、热路径都会触发的泄露，不要自动压低 severity
- 对 delete[] / 容器 wrapper / PtrArr 一类析构逻辑，要额外确认它是否只释放外层数组，而没有递归释放元素内部深层指针
- 如果仓库里已经存在 sibling API，必须对比新旧链路是否复用了同一套 save/release/pool/clear/destroy 机制；例如 RG_SetCodeSection 与 RG_SetMarkers 这种对照是必要步骤
- 本仓库上下文里，pb2c 可能为事件内部字段做深层堆分配，例如 `ttsContent`、`missionDisplayPb`
- 本仓库上下文里，PtrArr<T> 仅管理外层数组生命周期；不能把它当成“事件内部深层字段也会自动释放”的证据

[RESOURCE_LIFECYCLE_HIGH_RISK_PATTERNS]
如果 diff 或上下文出现以下模式，要把该文件视为高风险审查对象，并优先检查资源生命周期：
- new / new[] / malloc / calloc / realloc / strdup
- delete / delete[] / free / close / fclose / shutdown / release / reset / destroy / clear
- pool / cache / PtrArr / vector<*> / unique_ptr / shared_ptr / raw pointer ownership
- pb2c / parse / decode / clone / create / alloc / init / open / acquire / retain
- wrapper / api / manager / data_mgr / pool / cache / destroy 路径上的所有权传递
- RGEvent_t / PtrArr / pb2c / saveEventsAllocPointerToPool / releaseEventsAllocPointer / clearEventsAllocPointerPool / RG_SetMarkers / RG_SetCodeSection 一类桥接与清理链符号

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
    extra_context_blocks: list[Any] | None = None,
    retrieval_plans: list[Any] | None = None,
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
        retrieval_plans=retrieval_plans,
        max_findings=max_findings,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
