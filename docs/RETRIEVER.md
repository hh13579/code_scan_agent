下面是一版**可以直接丢给 Codex 的“命令式 Prompt”**。
它不是解释，而是 **明确让 Codex按步骤修改代码**。
你可以直接复制这段给 Codex / Cursor / OpenAI Codex。

（我根据你仓库当前结构写的：`graph/ nodes/ prompts/ reporters/ tools/`，并保持 README 里的 diff/CI 命令兼容。）

---

# 给 Codex 的命令式 Prompt

你正在修改仓库：

```
code_scan_agent
```

目标：
**提升 LLM diff review 的质量**，让模型不仅看到 diff patch，还能看到关键代码上下文。

当前流程：

```
diff
-> static scan
-> llm review
-> merge findings
-> report
```

需要升级为：

```
diff
-> risk ranking
-> context retrieval
-> llm semantic review
-> verification
-> merge findings
-> report
```

**重要约束**

必须遵守：

1. 不要破坏现有 CLI 行为
2. 不要改变 diff 扫描语义
3. 不要增加新的 CLI 参数
4. 不要引入 embedding / vector db / MCP
5. 所有新逻辑必须安全退化（失败不能中断主流程）

---

# Step 1 — 新建 Context Retrieval 模块

在 `src/code_scan_agent/` 下新增目录：

```
retrieval/
  __init__.py
  risk_ranker.py
  context_planner.py
  context_bundle.py
  retrievers/
    __init__.py
    function_retriever.py
    type_retriever.py
    test_retriever.py
```

该模块负责：

* 选高风险 diff
* 提取代码上下文
* 提供给 LLM review

不要改动现有 modules。

---

# Step 2 — 实现 risk_ranker.py

实现函数：

```python
rank_diff_risk(diff_files, triaged_findings=None) -> List[Dict]
```

输入：

```
diff_files
triaged_findings (optional)
```

输出示例：

```python
[
  {
    "path": "src/order_service.ts",
    "risk_score": 8.3,
    "reasons": ["conditional_change", "static_high"]
  }
]
```

评分规则（启发式）：

增加 risk_score：

* patch 包含 `if / else / switch / return / throw`
* 比较符变化 `>= -> >`
* 默认值变化 `null / false / 0`
* 命中 high / critical static finding

只返回 **top 5 风险文件**。

如果失败返回空列表。

---

# Step 3 — 实现 function_retriever.py

实现函数：

```
get_function_context(repo_path, file, language, changed_lines)
```

目标：

返回 **覆盖 changed_lines 的完整函数实现**。

返回格式：

```python
{
  "file": "...",
  "kind": "function_context",
  "symbol": "...",
  "content": "完整函数体"
}
```

实现策略：

1. 向上寻找函数声明
2. 使用 brace matching 找函数范围
3. 如果失败

退化为：

```
changed_lines ± 40 行
```

每个文件最多返回 **1 个函数 block**。

---

# Step 4 — 实现 type_retriever.py

实现函数：

```
get_related_types(repo_path, file, language, patch)
```

目标：

提取 patch 中涉及的类型定义。

返回：

```python
{
  "file": "...",
  "kind": "type_definition",
  "symbol": "...",
  "content": "class/interface/struct/type 定义"
}
```

策略：

1. 从 patch 中猜 symbol
2. 先查当前文件
3. 再 repo grep
4. 最多返回 2 个 block

---

# Step 5 — 实现 test_retriever.py

实现函数：

```
find_related_tests(repo_path, file, language)
```

根据命名约定查测试：

```
foo.ts -> foo.test.ts
Foo.java -> FooTest.java
foo.cpp -> foo_test.cpp
```

返回：

```python
{
  "file": "tests/foo.test.ts",
  "kind": "related_test",
  "content": "相关测试片段"
}
```

最多返回 **2 个片段**。

---

# Step 6 — 实现 context_planner.py

实现函数：

```
plan_context(diff_file, patch)
```

输出：

```python
{
  "file": "...",
  "needs": [
    "function_context",
    "type_definition",
    "related_test"
  ]
}
```

规则：

如果 patch 包含：

```
if / return / throw
```

需要：

```
function_context
```

如果 patch 包含：

```
class / interface / type
```

需要：

```
type_definition
```

如果 patch 包含：

```
条件逻辑变化
```

需要：

```
related_test
```

---

# Step 7 — 实现 context_bundle.py

实现函数：

```
bundle_context(context_blocks)
```

输入：

多个 retrieval block。

输出：

```
extra_context_blocks
```

结构：

```python
[
  {
    "file": "...",
    "kind": "...",
    "content": "..."
  }
]
```

限制：

* 每类最多 2 个 block
* 每个 block 最大 800 行
* 优先当前文件

---

# Step 8 — 新增节点 select_review_context.py

新增文件：

```
src/code_scan_agent/nodes/select_review_context.py
```

实现 node：

```
select_review_context(state)
```

逻辑：

```
1. 读取 diff_files
2. 调 risk_ranker
3. 选 top risky files
4. 调 context_planner
5. 调 retrievers
6. bundle context
7. 写入 state
```

写入：

```
state["review_context_blocks"]
```

失败必须安全退化。

---

# Step 9 — 修改 review_diff_with_llm.py

让 LLM prompt 额外接收：

```
extra_context_blocks
```

来源：

```
state["review_context_blocks"]
```

调用：

```
build_diff_review_messages(
    patch,
    extra_context_blocks=context_blocks
)
```

要求：

* 不影响 `--no-llm`
* LLM 失败仍可继续 pipeline

---

# Step 10 — 新增 verify_review_findings.py

新增 node：

```
verify_review_findings.py
```

逻辑：

对 top 3 LLM findings 做轻量验证：

验证：

* evidence 是否存在
* 类型是否存在
* 测试是否存在

可更新字段：

```
verification_status
verification_notes
```

状态：

```
strengthened
unchanged
weak
```

---

# Step 11 — 更新 graph/builder.py

修改 pipeline：

从：

```
normalize_findings
-> llm_triage
-> review_diff_with_llm
-> merge_review_findings
```

改为：

```
normalize_findings
-> llm_triage
-> select_review_context
-> review_diff_with_llm
-> verify_review_findings
-> merge_review_findings
```

要求：

* 旧模式仍可运行
* 无 diff 时跳过 retrieval

---

# Step 12 — 更新 build_report.py

增强 `top_issues` 选择逻辑：

提高权重：

```
review_action = block
impact 存在
evidence 存在
verification_status = strengthened
```

不要只按 severity 排序。

---

# Step 13 — 不允许修改

不要修改：

```
CLI 参数
Jenkinsfile
diff 扫描逻辑
README 命令示例
static analyzer 调用
```

不要增加：

```
embedding
vector search
tree-sitter
MCP
```

---

# 期望结果

修改后系统能够：

```
diff patch
+ function context
+ type definition
+ related tests
-> LLM review
-> better findings
```

最终报告中的字段：

```
impact
evidence
review_action
confidence
verification_status
```

必须更加具体和可信。

---

如果你愿意，我可以再帮你写一版 **“Codex 执行版 Prompt（一步生成 PR）”**，就是 Codex 会直接按顺序改文件并生成 commit。

