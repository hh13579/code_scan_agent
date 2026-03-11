# code_scan_agent

基于 LangGraph 的代码扫描 Agent，支持：
- C/C++: `clang-tidy` + `cppcheck`
- Security: `semgrep`
- LLM 归并与优先级整理: DeepSeek（失败自动降级为本地 triage）

## 1. 环境准备

### 1.1 Python

建议 Python 3.9+。

### 1.2 安装扫描器

macOS（Homebrew）：

```bash
brew install llvm cppcheck semgrep
```

`clang-tidy` 在 `llvm` 里，通常不在默认 PATH，需要：

```bash
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
```

## 2. 配置 DeepSeek

至少设置：

```bash
export DEEPSEEK_API_KEY="sk-xxxx"
```

可选配置见下文「环境变量」。

## 3. 全量扫描

```bash
cd /Users/didi/work/sdk-env/code_scan_agent
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
export DEEPSEEK_API_KEY="sk-xxxx"
python3 main.py /path/to/repo > /tmp/code_scan_report.txt
```

报告结构：
- JSON 报告（`summary/findings/grouped_by_file/grouped_by_severity`）
- `Errors:`（节点报错，非致命也会记录）
- `Logs:`（各节点运行日志与统计）

## 4. 单文件扫描（仅一个 C++ 文件）

现在支持直接传文件路径，和全量扫描一样用 `main.py`：

```bash
cd /Users/didi/work/sdk-env/code_scan_agent
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
export DEEPSEEK_API_KEY="你的 key"
python3 main.py /Users/didi/work/sdk-env/navi-engine-v2/RGMap/RGMap/business/CaseMaker/RGCaseMakerToolkit.cpp > /tmp/code_scan_single_cpp.txt
```

结果文件：`/tmp/code_scan_single_cpp.txt`

## 5. Diff 扫描（只扫改动）

### 5.1 扫当前工作区改动（staged + unstaged）

```bash
cd /Users/didi/work/sdk-env/code_scan_agent
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
export DEEPSEEK_API_KEY="你的 key"
python3 main.py /path/to/repo --mode diff > /tmp/code_scan_diff_report.txt
```

### 5.2 扫两个 ref 之间的改动（PR 场景）

```bash
python3 main.py /path/to/repo --mode diff --base origin/main --head HEAD > /tmp/code_scan_diff_report.txt
```

`--base/--head` 是 `--diff-base-ref/--diff-head-ref` 的简写。
只传 `--diff-base-ref` 或 `--base` 时，默认比较 `base...HEAD`。
可通过 `--diff-range-mode double` 改为 `base..HEAD`。

### 5.3 扫某一个 commit 引入的改动

```bash
python3 main.py /path/to/repo --mode diff --diff-commit 2492cad > /tmp/code_scan_diff_report.txt
```

`--diff-commit` 不能与 `--diff-base-ref/--diff-head-ref` 同时使用。

### 5.4 只保留“命中改动行”的 findings

```bash
python3 main.py /path/to/repo --mode diff --diff-findings-filter only > /tmp/code_scan_diff_report.txt
```

`--diff-findings-filter` 可选：
- `only`: 只保留命中改动行的 finding（推荐，默认）
- `mark`: 保留全部 finding，并标记 `in_diff=true/false`

默认 `DIFF_ENABLE_LLM=0`：diff 模式下只做本地 triage（更快更稳定）。

### 5.5 Jenkins / CI 推荐命令

```bash
python3 main.py /path/to/repo \
  --mode diff \
  --base origin/main \
  --head HEAD \
  --no-llm \
  --diff-findings-filter only \
  --out artifacts/report.json \
  --fail-on high
```

- `--no-llm`: 关闭 DeepSeek，固定走本地 triage
- `--out`: 把 JSON 报告写到文件
- `--fail-on high`: 存在 `high` 或 `critical` finding 时返回 exit code `2`

## 6. 环境变量

### 6.1 DeepSeek

- `DEEPSEEK_API_KEY`: 必填
- `DEEPSEEK_MODEL`: 默认 `deepseek-chat`
- `DEEPSEEK_BASE_URL`: 默认 `https://api.deepseek.com`
- `DEEPSEEK_TIMEOUT_SEC`: 默认 `45`
- `DEEPSEEK_TRIAGE_MAX_ITEMS`: 默认 `60`
- `DEEPSEEK_BATCH_SIZE`: 单次提交给 DeepSeek 的 finding 数（默认 `8`，网络慢时建议 `5-8`）
- `DEEPSEEK_RETRY`: DeepSeek 失败后的重试次数（默认 `1`）
- `DEEPSEEK_RETRY_BACKOFF_SEC`: 重试退避秒数基准（默认 `1.0`）

### 6.2 C++ 扫描

- `CLANG_TIDY_TIMEOUT_SEC`: `clang-tidy` 单文件超时（默认 `60`）
- `CLANG_TIDY_EXTRA_ARGS`: 额外参数
- `CLANG_TIDY_LOG_PER_FILE`: `1` 打印逐文件日志，默认 `0`
- `CPPCHECK_TIMEOUT_SEC`: `cppcheck` 超时（默认 `180`）
- `CPPCHECK_EXTRA_ARGS`: 额外参数
- `CPP_SCAN_MAX_FILES`: C++ 最大扫描文件数，`0` 表示不限制
- `CPP_THIRD_PARTY_EXCLUDES`: 额外三方目录前缀，逗号分隔

### 6.3 Semgrep

- `SEMGREP_CONFIG`: 默认 `p/security-audit`
- `SEMGREP_METRICS`: `on/off/auto`，默认规则见代码
- `SEMGREP_TIMEOUT_SEC`: 命令超时（默认 `300`）
- `SEMGREP_RULE_TIMEOUT_SEC`: 单规则超时（默认 `15`）
- `SEMGREP_EXTRA_ARGS`: 额外参数

### 6.4 Diff 模式

- `DIFF_BASE_REF`: 等价于 `--diff-base-ref`
- `DIFF_HEAD_REF`: 等价于 `--diff-head-ref`
- `DIFF_COMMIT`: 等价于 `--diff-commit`
- `DIFF_STAGED`: `1` 表示只看 staged 变更（当未指定 base/head 时）
- `DIFF_RANGE_MODE`: `triple` 或 `double`（默认 `triple`）
- `GIT_DIFF_TIMEOUT_SEC`: git diff 超时（默认 `30`）
- `DIFF_FINDINGS_FILTER`: `mark` 或 `only`（默认 `only`）
- `DIFF_ENABLE_LLM`: diff 模式是否启用 DeepSeek 分诊（默认 `0`，设置 `1` 开启）

## 7. 常见问题

### 7.1 `llm_triage: DeepSeek failed ... timed out`

说明 DeepSeek 接口在当前超时窗口内没有返回。可调：

```bash
export DEEPSEEK_TIMEOUT_SEC=180
export DEEPSEEK_TRIAGE_MAX_ITEMS=20
```

### 7.2 `clang-tidy not found in PATH`

```bash
export PATH="/opt/homebrew/opt/llvm/bin:$PATH"
```

### 7.3 `semgrep` 无结果或报配置错误

建议使用显式规则集：

```bash
export SEMGREP_CONFIG="p/security-audit"
export SEMGREP_METRICS="off"
```
