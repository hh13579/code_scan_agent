# code_scan_agent：LLM Diff Review 接入 TODO Checklist

## 总目标

在现有静态扫描链路上增加一条 **LLM diff review** 通道，形成如下主链路：

```text
git diff(with patch)
  -> diff_files
  -> review_diff_with_llm
  -> merge_review_findings
  -> build_report
```

最终 `report` 需要同时包含：

* `static_findings`
* `llm_review_findings`
* `merged_findings`

并保持旧流程兼容。

---

# Task 0：先确认当前基础是否存在

## 检查项

* [x] `src/code_scan_agent/tools/repo/git_diff.py` 已存在
* [x] `src/code_scan_agent/prompts/diff_review_prompt.py` 已存在
* [x] `src/code_scan_agent/nodes/review_diff_with_llm.py` 已存在
* [x] `src/code_scan_agent/nodes/merge_review_findings.py` 已存在
* [x] `src/code_scan_agent/nodes/build_report.py` 已改成支持 merged/static/llm_review
* [x] `src/code_scan_agent/main.py` 已支持 `--mode diff --base --head --no-llm`

## Done Definition

* [x] 如果以上文件不存在，先补齐再进入后续任务

---

# Task 1：扩展 `git_diff.py`，确保返回 patch

## 文件

* [x] `src/code_scan_agent/tools/repo/git_diff.py`

## 目标

让 `get_git_diff_files(...)` 返回的 `DiffFile` 包含：

* [x] `path`
* [x] `status`
* [x] `changed_lines`
* [x] `patch`
* [x] `hunks`
* [x] `old_path`

## 要求

* [x] 使用 `git diff -U0`
* [x] `changed_lines` 是新文件侧行号
* [x] `patch` 是文件级 unified diff 文本
* [x] `hunks` 是按 hunk 拆分的 patch 片段
* [x] 删除文件默认可排除（`exclude_deleted=True`）

## Done Definition

* [x] 调用 `get_git_diff_files(...)` 后，返回对象里能看到 `patch`
* [x] `changed_lines` 与 `patch` 同时可用
* [x] rename/new file/delete 不会导致崩溃

---

# Task 2：修改 `collect_targets.py`，把 `diff_files` 写进 state

## 文件

* [x] `src/code_scan_agent/nodes/collect_targets.py`

## 目标

在 `mode=diff` 时，除了生成 `targets`，还要写入：

```python
state["diff_files"] = [
    {
        "path": "...",
        "language": "...",
        "patch": "...",
        "changed_lines": [...],
        "status": "...",
        "old_path": "...",
    }
]
```

## 要求

* [x] 继续保留现有 `targets` 逻辑
* [x] `diff_files` 只保留代码文件（cpp/java/ts）
* [x] `language` 根据后缀推断
* [x] `patch` 为空时也允许写入，但尽量正常传递
* [x] 目录忽略规则继续生效（build/node_modules/third_party 等）

## Done Definition

* [x] diff 模式运行后，`state["diff_files"]` 存在
* [x] `state["targets"]` 仍然正确
* [x] 对旧的 full/selected 模式不产生破坏

---

# Task 3：确认 `diff_review_prompt.py` 可直接被节点调用

## 文件

* [x] `src/code_scan_agent/prompts/diff_review_prompt.py`

## 目标

保证存在以下接口：

* [x] `SYSTEM_PROMPT`
* [x] `build_diff_review_prompt(...)`
* [x] `build_diff_review_messages(...)`

## 要求

`build_diff_review_messages(...)` 输入支持：

* [x] `repo_name`
* [x] `base_ref`
* [x] `head_ref`
* [x] `changed_files`
* [x] `diff_blocks`
* [x] `static_findings`
* [x] `extra_context_blocks`
* [x] `max_findings`

## Done Definition

* [x] 节点里可直接 import 并构造 messages
* [x] prompt 输出要求是严格 JSON，不带 markdown 解释

---

# Task 4：实现 `review_diff_with_llm.py`

## 文件

* [x] `src/code_scan_agent/nodes/review_diff_with_llm.py`

## 目标

新增 LLM diff review 节点。

## 输入

从 `state` 读取：

* [x] `request.repo_path`
* [x] `request.base_ref`
* [x] `request.head_ref`
* [x] `request.no_llm`
* [x] `diff_files`
* [x] `triaged_findings` 或 `normalized_findings`
* [x] `review_context_blocks`（可选）

## 输出

写入：

```python
state["llm_review_findings"] = [...]
```

## 行为要求

* [x] `--no-llm` 时直接跳过
* [x] `diff_files` 为空时直接跳过
* [x] LLM 失败时不抛致命异常
* [x] JSON parse 失败时记录 error/log，但不阻断主流程
* [x] 输出结构必须是 finding-like dict

## 推荐 finding 结构

* [x] `tool = "llm_diff_review"`
* [x] `rule_id = "semantic-review"`
* [x] `source = "llm_diff_review"`
* [x] 包含 `category/severity/file/line/title/message/confidence/evidence/suggested_action`

## Done Definition

* [x] 节点执行后，`state["llm_review_findings"]` 总是存在（可能为空）
* [x] mock LLM 返回时，能产出结构化 findings
* [x] 失败时主流程继续

---

# Task 5：在 `review_diff_with_llm.py` 里接入 LLM 调用抽象层

## 文件

* [x] `src/code_scan_agent/nodes/review_diff_with_llm.py`

## 目标

保留一个单独的 LLM 调用函数，例如：

```python
def _call_llm_diff_review(messages, state) -> str:
    ...
```

## 要求

* [x] 第一版允许先用 mock / placeholder
* [x] 不要把大段调用逻辑散落在主节点里
* [x] 便于后面接 DeepSeek / OpenAI / 本地 mock

## Done Definition

* [x] 节点主逻辑和模型调用解耦
* [x] 后续替换模型 client 时只改一个函数

---

# Task 6：实现 `merge_review_findings.py`

## 文件

* [x] `src/code_scan_agent/nodes/merge_review_findings.py`

## 目标

合并：

* [x] `triaged_findings`
* [x] `llm_review_findings`

生成：

* [x] `static_findings`
* [x] `llm_review_findings`
* [x] `merged_findings`

## 合并策略

* [x] 静态 findings 全保留
* [x] LLM findings 默认保留
* [x] 如果 file/line/category 高度重叠，则做弱去重
* [x] overlap 的 LLM finding 可保留，但加 `overlaps_static=True`

## Done Definition

* [x] `merged_findings` 存在
* [x] `static_findings` 和 `llm_review_findings` 分开保留
* [x] 没有 LLM findings 时，`merged_findings == static_findings`

---

# Task 7：修改 `build_report.py`

## 文件

* [x] `src/code_scan_agent/nodes/build_report.py`

## 目标

让最终 report 支持三路输出。

## 要求

默认优先级：

```python
merged_findings > triaged_findings > normalized_findings
```

最终 report 应包含：

* [x] `summary`
* [x] `findings`
* [x] `grouped_by_file`
* [x] `grouped_by_severity`
* [x] `static_summary`
* [x] `llm_review_summary`
* [x] `merged_summary`
* [x] `static_findings`
* [x] `llm_review_findings`
* [x] `merged_findings`
* [x] `static_grouped_by_file`
* [x] `static_grouped_by_severity`
* [x] `llm_review_grouped_by_file`
* [x] `llm_review_grouped_by_severity`

## Done Definition

* [x] 没有 merged/llm_review 时仍兼容旧流程
* [x] `report["findings"]` 默认等于 merged 结果
* [x] `report["summary"]` 默认等于 merged summary

---

# Task 8：修改 `graph/builder.py`，接入新节点

## 文件

* [x] `src/code_scan_agent/graph/builder.py`

## 目标

把新链路接入主 graph。

## 当前目标流程

从：

```text
normalize_findings -> llm_triage -> build_report -> finalize
```

改成：

```text
normalize_findings
  -> llm_triage
  -> review_diff_with_llm
  -> merge_review_findings
  -> build_report
  -> finalize
```

## 要求

* [x] `review_diff_with_llm` 在 `llm_triage` 之后
* [x] `merge_review_findings` 在 `build_report` 之前
* [x] 不破坏现有 full/selected 模式

## Done Definition

* [x] 新节点已进入 graph
* [x] 执行 graph 时不会因新字段缺失报错
* [x] 旧模式仍可运行

---

# Task 9：确保 `--no-llm` 对两类 LLM 行为都生效

## 文件

* [x] `src/code_scan_agent/nodes/llm_triage.py`
* [x] `src/code_scan_agent/nodes/review_diff_with_llm.py`

## 要求

`--no-llm` 时：

* [x] 跳过 triage 重写
* [x] 跳过 diff semantic review
* [x] 静态扫描仍正常运行
* [x] JSON/Markdown/SARIF 仍正常输出

## Done Definition

* [x] `--no-llm` 模式下，`llm_review_findings == []`
* [x] `merged_findings == static_findings`

---

# Task 10：更新中文 Markdown 报告（可选但推荐）

## 文件

* [x] `src/code_scan_agent/reporters/markdown_reporter_zh.py`

## 目标

中文报告中展示三路摘要：

* [x] 静态扫描发现问题数
* [x] LLM 语义审查发现问题数
* [x] 合并后问题数

## 建议输出

在摘要区新增：

* [x] `静态扫描：X 条`
* [x] `LLM语义审查：Y 条`
* [x] `合并结果：Z 条`

## Done Definition

* [x] 报告更清楚地区分两类问题来源
* [x] 对旧 report 仍兼容

---

# Task 11：更新 SARIF 输出（可选但推荐）

## 文件

* [x] `src/code_scan_agent/reporters/sarif_reporter.py`

## 目标

默认输出 `merged_findings`，并保留来源信息。

## 要求

* [x] `tool` / `source` 字段映射到 SARIF `properties`
* [x] `llm_diff_review` 结果也能进入 SARIF
* [x] 不要求第一版做 inline fix

## Done Definition

* [x] merged 结果可输出到 SARIF
* [x] 静态与 LLM 来源可区分

---

# Task 12：补最小测试（至少 4 个）

## 建议测试文件

* [x] `tests/unit/test_git_diff_patch.py`
* [x] `tests/unit/test_review_diff_with_llm.py`
* [x] `tests/unit/test_merge_review_findings.py`
* [x] `tests/unit/test_build_report_merged.py`

## 至少覆盖的 case

### Case 1：`--no-llm`

* [x] `llm_review_findings == []`
* [x] `merged_findings == static_findings`

### Case 2：mock LLM 正常返回

* [x] `llm_review_findings` 非空
* [x] `merged_findings` 同时包含 static + llm

### Case 3：mock LLM 返回脏 JSON

* [x] 不崩
* [x] `llm_review_findings == []`
* [x] 主流程继续

### Case 4：没有 `diff_files`

* [x] 节点跳过
* [x] 主流程继续

---

# Task 13：最终验收命令

## 命令

* [x] 运行以下命令可成功执行：

```bash
python3 -m code_scan_agent.main . \
  --mode diff \
  --base origin/main \
  --head HEAD \
  --fail-on high \
  --out artifacts/report.json \
  --out-zh artifacts/report_zh.md \
  --out-sarif artifacts/report.sarif
```

## 验收结果

* [x] `report.json` 中有：

  * `static_findings`
  * `llm_review_findings`
  * `merged_findings`
* [x] `report_zh.md` 可读
* [x] `report.sarif` 可生成
* [x] `--no-llm` 模式可正常跑通
* [x] LLM 失败时静态扫描结果仍能输出

---

# 建议的提交顺序（让 Codex 分步改）

## PR/Commit 1

* [x] Task 1 + Task 2

## PR/Commit 2

* [x] Task 4 + Task 5

## PR/Commit 3

* [x] Task 6 + Task 7

## PR/Commit 4

* [x] Task 8 + Task 9

## PR/Commit 5

* [x] Task 10 + Task 11 + Task 12

---

# 最终目标

完成后，系统应具备：

* [x] 静态扫描发现规则问题
* [x] LLM diff review 发现语义问题
* [x] 两路结果合并输出
* [x] CI 仍以静态扫描为 gate
* [x] LLM review 作为增强层，不影响主流程稳定性
