# code_scan_agent：Context Retrieval Layer 接入 TODO Checklist

## 总目标

在现有 `diff -> review_diff_with_llm -> merge_review_findings -> build_report` 基础上，新增一个 **Context Retrieval Layer**，让 LLM review 不只看 patch，还能看到：

* 被改函数完整实现
* 类型定义
* 关键调用方 / 被调用方
* 相关测试片段

目标是把 LLM diff review 从“只看 patch 猜风险”升级成“结合局部代码上下文做审查”。

---

# Task 0：确认当前基础链路已存在

## 检查项

* [ ] `--mode diff` 已可运行
* [ ] `--base/--head` 已可用
* [ ] `--diff-findings-filter only|mark` 已可用
* [ ] `review_diff_with_llm.py` 已存在
* [ ] `merge_review_findings.py` 已存在
* [ ] `build_report.py` 已支持 merged/static/llm_review
* [ ] `prompts/diff_review_prompt.py` 已存在
* [ ] `tools/repo/git_diff.py` 已能提供 patch + changed_lines

这些能力和命令在仓库 README 里已经有公开描述，可作为实现基线。([GitHub][1])

## Done Definition

* [ ] 当前主链路不需要重写，只是在 LLM review 前插入上下文补全节点

---

# Task 1：新增 retrieval 目录骨架

## 目标目录

* [ ] `src/code_scan_agent/retrieval/__init__.py`
* [ ] `src/code_scan_agent/retrieval/risk_ranker.py`
* [ ] `src/code_scan_agent/retrieval/context_planner.py`
* [ ] `src/code_scan_agent/retrieval/context_bundle.py`
* [ ] `src/code_scan_agent/retrieval/language/__init__.py`
* [ ] `src/code_scan_agent/retrieval/language/common.py`
* [ ] `src/code_scan_agent/retrieval/language/cpp_context.py`
* [ ] `src/code_scan_agent/retrieval/language/java_context.py`
* [ ] `src/code_scan_agent/retrieval/language/ts_context.py`
* [ ] `src/code_scan_agent/retrieval/retrievers/__init__.py`
* [ ] `src/code_scan_agent/retrieval/retrievers/function_retriever.py`
* [ ] `src/code_scan_agent/retrieval/retrievers/type_retriever.py`
* [ ] `src/code_scan_agent/retrieval/retrievers/callsite_retriever.py`
* [ ] `src/code_scan_agent/retrieval/retrievers/test_retriever.py`

## 设计要求

* [ ] 第一版只做轻量实现，不要引入复杂 RAG/embedding
* [ ] 优先使用文件读取 + 正则/brace matching + grep 风格能力
* [ ] 所有 retrieval 都必须是 best-effort，不允许让主流程崩溃

## Done Definition

* [ ] 新目录结构建立完成
* [ ] 不影响现有代码运行

---

# Task 2：实现 `risk_ranker.py`

## 文件

* [ ] `src/code_scan_agent/retrieval/risk_ranker.py`

## 目标

为 `diff_files` 做轻量风险预排序，只挑最值得补上下文的文件 / hunk。

## 输入

* [ ] `diff_files`
* [ ] `triaged_findings`（可选）
* [ ] `normalized_findings`（可选）

## 输出

建议输出结构：

```python
[
  {
    "path": "src/order_service.ts",
    "language": "ts",
    "risk_score": 8.5,
    "reasons": ["conditional_change", "core_file", "static_high"]
  }
]
```

## 第一版启发式

出现以下特征加分：

* [ ] patch 中出现 `if`, `else`, `switch`, `return`, `throw`, `catch`
* [ ] 条件比较符变化：`>= -> >`, `== -> !=`, `null` 判断变化
* [ ] 默认值变化：`null`, `0`, `false`, `[]`, `{}` 等
* [ ] 函数签名变化
* [ ] 删除代码多于新增代码
* [ ] 文件命中 high/critical static finding
* [ ] 文件路径在核心目录（可先硬编码简单规则）

## Done Definition

* [ ] 能对 diff 文件生成稳定 risk_score
* [ ] 能输出 top risky files
* [ ] 不依赖 LLM

---

# Task 3：实现 `context_planner.py`

## 文件

* [ ] `src/code_scan_agent/retrieval/context_planner.py`

## 目标

根据某个 diff file / patch 的特征，决定需要补哪些上下文类型。

## 输入

* [ ] 单个 diff file（path, language, patch, changed_lines）
* [ ] risk_score / reasons（可选）

## 输出

建议输出结构：

```python
{
  "file": "src/order_service.ts",
  "needs": [
    "function_context",
    "type_definition",
    "related_tests"
  ]
}
```

## 第一版规则

* [ ] 有函数体逻辑改动 → `function_context`
* [ ] 有 `class/interface/struct/type/enum` 相关改动 → `type_definition`
* [ ] 有 public/exported/API/signature 改动 → `call_sites`
* [ ] 有条件判断 / 默认值 / 异常处理改动 → `related_tests`

## Done Definition

* [ ] Planner 能针对每个 diff file 输出 `needs`
* [ ] 结果可解释，不做黑盒打分

---

# Task 4：实现 `language/common.py`

## 文件

* [ ] `src/code_scan_agent/retrieval/language/common.py`

## 目标

提供通用辅助函数，避免不同语言重复写基础逻辑。

## 建议能力

* [ ] `read_file_text(path)`
* [ ] `safe_slice_lines(text, start, end)`
* [ ] `line_to_offset(text, line_no)`
* [ ] `guess_symbol_from_patch(patch)`
* [ ] `trim_block(text, max_chars)`
* [ ] `normalize_path(...)`

## Done Definition

* [ ] retrieval 子模块可以复用这些工具
* [ ] 文件读不到时返回空，不抛致命异常

---

# Task 5：实现 `function_retriever.py`

## 文件

* [ ] `src/code_scan_agent/retrieval/retrievers/function_retriever.py`

## 目标

根据 file + changed_lines，提取“覆盖改动行的函数/方法完整实现”。

## 输入

* [ ] `repo_path`
* [ ] `file`
* [ ] `language`
* [ ] `changed_lines`

## 输出

建议输出 block：

```python
{
  "file": "src/order_service.ts",
  "kind": "function_context",
  "symbol": "settleOrder",
  "content": "function settleOrder(...) { ... }"
}
```

## 第一版实现要求

* [ ] C++ / Java / TS 都先用“向上找声明 + brace matching”的轻量实现
* [ ] 精准解析失败时，退化为 changed_lines 前后 N 行（例如 30~50 行）
* [ ] 只返回 1 个最相关函数 block

## Done Definition

* [ ] 大多数普通函数改动都能拿到较完整函数体
* [ ] 失败时不崩，退化为邻域上下文

---

# Task 6：实现 `type_retriever.py`

## 文件

* [ ] `src/code_scan_agent/retrieval/retrievers/type_retriever.py`

## 目标

提取与改动最相关的类型定义。

## 输入

* [ ] `repo_path`
* [ ] `file`
* [ ] `language`
* [ ] `patch`
* [ ] `function_context`（可选）

## 输出

建议输出 block：

```python
{
  "file": "src/order_service.ts",
  "kind": "type_definition",
  "symbol": "Order",
  "content": "interface Order { ... }"
}
```

## 第一版策略

* [ ] 优先从 patch/function_context 中猜类型名
* [ ] 先在当前文件中查定义
* [ ] 当前文件没有时，再在 repo 内做有限 grep
* [ ] 最多返回 1~2 个最相关类型块

## Done Definition

* [ ] 对 interface/class/struct/enum/type 改动能补到定义
* [ ] 找不到时返回空列表，不报错

---

# Task 7：实现 `callsite_retriever.py`

## 文件

* [ ] `src/code_scan_agent/retrieval/retrievers/callsite_retriever.py`

## 目标

提取关键调用点，帮助判断“接口改了，调用链是否同步”。

## 输入

* [ ] `repo_path`
* [ ] `file`
* [ ] `language`
* [ ] `patch`
* [ ] `function_context`（可选）

## 输出

建议输出 block：

```python
{
  "file": "src/payment_controller.ts",
  "kind": "call_site",
  "symbol": "settleOrder",
  "content": "await settleOrder(order, threshold)"
}
```

## 第一版策略

* [ ] 先从 patch / function_context 猜符号名
* [ ] 用 repo 级别 grep 搜索 symbol
* [ ] 只取最相关前 3 个调用点
* [ ] 每个调用点只取前后少量上下文（如 15~25 行）

## Done Definition

* [ ] 至少能补充同模块/直接调用点
* [ ] 不要求完整 call graph

---

# Task 8：实现 `test_retriever.py`

## 文件

* [ ] `src/code_scan_agent/retrieval/retrievers/test_retriever.py`

## 目标

提取相关测试片段，帮助模型判断“行为是否被测试覆盖”。

## 输入

* [ ] `repo_path`
* [ ] `file`
* [ ] `language`
* [ ] `patch`
* [ ] `function_context`（可选）

## 输出

建议输出 block：

```python
{
  "file": "tests/order_service.test.ts",
  "kind": "related_test",
  "content": "it('applies discount when amount equals threshold', ...)"
}
```

## 第一版策略

按命名约定和路径启发式找：

* [ ] `foo.ts` → `foo.test.ts` / `foo.spec.ts`
* [ ] `Foo.java` → `FooTest.java`
* [ ] `foo.cpp` → `foo_test.cpp` / `test_foo.cpp`

补充：

* [ ] 若 patch / function_context 能猜出 symbol，可在测试文件里 grep symbol
* [ ] 每个文件最多取 1~2 段测试片段

## Done Definition

* [ ] 对常见命名约定的测试文件能命中
* [ ] 找不到测试时不报错

---

# Task 9：实现 `context_bundle.py`

## 文件

* [ ] `src/code_scan_agent/retrieval/context_bundle.py`

## 目标

把 function/type/callsite/test 检索结果整理成可直接喂给 prompt 的 `extra_context_blocks`。

## 输入

* [ ] retriever 输出的多个 blocks

## 输出

建议统一格式：

```python
[
  {
    "file": "src/order_service.ts",
    "kind": "function_context",
    "content": "..."
  },
  {
    "file": "src/order_service.ts",
    "kind": "type_definition",
    "content": "..."
  }
]
```

## 约束

* [ ] 控制总量，避免 token 爆炸
* [ ] 每类最多保留 1~2 个 block
* [ ] 每个 block 要裁剪长度
* [ ] 优先当前文件 > 同模块 > 全 repo

## Done Definition

* [ ] `extra_context_blocks` 可直接传给 `build_diff_review_messages(...)`
* [ ] 总长度可控

---

# Task 10：新增节点 `select_review_context.py`

## 文件

* [ ] `src/code_scan_agent/nodes/select_review_context.py`

## 目标

在 graph 中增加一个“上下文选择与检索”节点。

## 输入

从 state 读取：

* [ ] `request.repo_path`
* [ ] `diff_files`
* [ ] `triaged_findings` / `normalized_findings`

## 输出

写入：

```python
state["review_context_blocks"] = [...]
```

## 节点内部流程

* [ ] 调 `risk_ranker` 选高风险文件
* [ ] 对每个文件调 `context_planner`
* [ ] 根据 planner 调各类 retriever
* [ ] 用 `context_bundle` 打包结果
* [ ] 写入 state

## 第一版限制

* [ ] 只处理 risk top 5 文件
* [ ] 每文件最多 4 类上下文
* [ ] 每类最多 1~2 个 block

## 错误处理

* [ ] retrieval 失败只写 log/error，不阻断主流程
* [ ] `review_context_blocks` 至少保证存在（可为空）

## Done Definition

* [ ] diff 模式下，`state["review_context_blocks"]` 能产出内容
* [ ] `review_diff_with_llm.py` 可直接消费该字段

---

# Task 11：把 `select_review_context.py` 接入 graph

## 文件

* [ ] `src/code_scan_agent/graph/builder.py`

## 目标

把上下文检索节点插入 LLM diff review 之前。

## 推荐流程

从：

```text
normalize_findings
  -> llm_triage
  -> review_diff_with_llm
  -> merge_review_findings
  -> build_report
```

改成：

```text
normalize_findings
  -> llm_triage
  -> select_review_context
  -> review_diff_with_llm
  -> merge_review_findings
  -> build_report
```

## 要求

* [ ] `select_review_context` 只影响 LLM diff review，不影响静态扫描主流程
* [ ] `--no-llm` 时可以直接跳过或运行但无副作用
* [ ] full / selected 模式没有 `diff_files` 时应安全退化

## Done Definition

* [ ] graph 新节点接入成功
* [ ] diff 模式可跑通
* [ ] 没有 diff 时不会崩

---

# Task 12：更新 `review_diff_with_llm.py`，消费 `review_context_blocks`

## 文件

* [ ] `src/code_scan_agent/nodes/review_diff_with_llm.py`

## 目标

让 LLM review 真正吃到检索上下文。

## 要求

* [ ] 读取 `state["review_context_blocks"]`
* [ ] 传给 `build_diff_review_messages(..., extra_context_blocks=...)`
* [ ] 控制 messages 长度，避免无脑塞满
* [ ] 保留 `--no-llm`、JSON parse 失败、LLM 失败时的退化行为

## Done Definition

* [ ] LLM prompt 里不再只有 patch，也有 function/type/callsite/test blocks
* [ ] 失败不影响主流程

---

# Task 13：最小测试

## 建议新增测试文件

* [ ] `tests/unit/test_risk_ranker.py`
* [ ] `tests/unit/test_function_retriever.py`
* [ ] `tests/unit/test_type_retriever.py`
* [ ] `tests/unit/test_test_retriever.py`
* [ ] `tests/unit/test_select_review_context.py`

## 至少覆盖 case

### Case 1：函数上下文可提取

* [ ] changed_lines 在函数体内时，能返回函数块

### Case 2：类型定义可提取

* [ ] patch 改动 interface/class/struct 时，能补到定义

### Case 3：测试片段可提取

* [ ] 按命名约定可找到测试文件并切片

### Case 4：select_review_context 可写入 state

* [ ] `review_context_blocks` 存在
* [ ] 内容格式符合 prompt 要求

### Case 5：异常情况退化

* [ ] 找不到文件 / 解析失败 / grep 失败时不崩

## Done Definition

* [ ] retrieval 层至少有最小单测
* [ ] 节点级行为可验证

---

# Task 14：验收标准

## 功能验收

* [ ] diff 模式运行时，LLM review 输入里包含：

  * patch
  * function_context
  * type_definition（如果有）
  * call_site（如果有）
  * related_test（如果有）
* [ ] `llm_review_findings` 质量相比只看 patch 更稳定
* [ ] 报告中的 `impact`、`review_action`、`evidence` 更具体

## 运行验收

* [ ] `--no-llm` 模式不受影响
* [ ] 检索失败不会阻断静态扫描主链路
* [ ] Jenkins diff 模式仍可跑

---

# 建议提交顺序

## Commit 1

* [ ] Task 1 + Task 2 + Task 3

## Commit 2

* [ ] Task 4 + Task 5 + Task 6

## Commit 3

* [ ] Task 7 + Task 8 + Task 9

## Commit 4

* [ ] Task 10 + Task 11 + Task 12

## Commit 5

* [ ] Task 13 + Task 14

---

# 第一版实现边界（不要超做）

第一版**不要做**：

* [ ] embedding / vector search
* [ ] 完整 call graph
* [ ] tree-sitter 全量接入
* [ ] 自动 patch 修复
* [ ] 多轮 agent 交互
* [ ] MCP 集成

第一版**只做**：

* [ ] 轻量 risk ranking
* [ ] 局部上下文补全
* [ ] 把上下文安全地喂给 LLM diff review

---

# 最终目标

完成后，系统从：

```text
只看 diff patch 做 LLM review
```

升级成：

```text
看 diff patch + 函数实现 + 类型定义 + 关键调用点 + 相关测试 做 LLM review
```

这会显著提升：

* finding 的可信度
* evidence 的具体性
* impact 的准确性
* 整体报告的“像在审而不是像在猜”的程度

---