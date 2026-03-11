# C/C++ 代码审查报告

> 生成方式：DeepSeek

## 范围
- 本次审查基于静态扫描结果和 diff 模式分析，覆盖了代码变更中的 9 个发现，重点关注新增的弯道融合策略和重构的曲线管理器。
- 结论：代码变更引入了新的弯道融合策略和重构了曲线管理器，整体设计合理，但存在几处潜在的空指针访问风险需要修复。其他问题多为代码质量或文档完善性建议。
- 总体风险：中

## 扫描摘要
- 原始 summary：`{"total": 9, "critical": 0, "high": 2, "medium": 1, "low": 5, "info": 1}`

## 工具观察
- 扫描工具在 diff 模式下运行，仅分析变更代码，覆盖了 7 个文件，原始扫描发现 259 条，经 diff 过滤后保留 9 条。
- 工具使用了 clang-tidy、cppcheck 和 semgrep，但 semgrep 未发现安全问题。
- LLM 辅助审查识别了语义层面的变更风险，如空指针访问和逻辑缺失。

## 覆盖限制
- 扫描基于 diff 模式，仅覆盖变更行，未分析完整文件的上下文，可能导致某些跨函数依赖风险未被发现。
- code_context 字段显示 'file not found in working tree'，表明审查时无法获取完整文件内容，依赖 diff hunk 判断，可能影响准确性。
- 安全扫描工具 semgrep 未输出任何发现，可能配置或规则集未覆盖特定 C++ 模式。

## Findings
### 1. high | dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_peak_fusion_strategy.cpp:178
- 工具：`llm_diff_review`
- 规则：`semantic-review`
- 判断：建议修复
- 置信度：高
- 原因：diff hunk 显示新增代码中，在 fused_peaks 为空时直接返回错误码，但未检查空向量就调用 front() 和 back()。虽然代码逻辑上 fused_peaks 为空时会提前返回，但 BuildFusedOutput 函数内部可能未做空检查，存在空指针解引用风险。
- 影响：若 fused_peaks 为空且 BuildFusedOutput 未处理，调用 front() 或 back() 将导致未定义行为，可能崩溃。
- 建议：在 BuildFusedOutput 函数入口添加空向量检查，或确保 ClusterNeighborPeaks 失败时 fused_peaks 不为空但包含默认值。

### 2. high | dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp:165
- 工具：`llm_diff_review`
- 规则：`semantic-review`
- 判断：建议修复
- 置信度：高
- 原因：diff hunk 显示 EmitSegment 函数被调用时，merged_bends 可能为空，但函数内部未检查就直接访问 front() 和 back()。虽然 SlideAndFuse 后有空检查并返回错误码，但 EmitSegment 的实现未在 diff 中给出，存在潜在风险。
- 影响：若 merged_bends 为空且 EmitSegment 未处理，访问 front() 或 back() 将导致程序崩溃。
- 建议：在 EmitSegment 函数入口添加空向量检查，或确保调用前 merged_bends 非空。

### 3. medium | dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp:10
- 工具：`llm_diff_review`
- 规则：`semantic-review`
- 判断：需要人工确认
- 置信度：中
- 原因：diff hunk 显示 ShouldSkipGentleBends 函数被移除，但代码上下文中未提供该函数的具体实现或调用点。可能这是重构的一部分，逻辑被合并或移至他处，需确认是否影响弯道过滤逻辑。
- 影响：若该函数原本用于跳过轻微弯道，移除后可能导致不必要的融合，影响弯道检测精度。
- 建议：审查代码变更，确认 ShouldSkipGentleBends 的逻辑是否被其他函数替代，或是否需要重新实现。

### 4. low | dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp:70
- 工具：`llm_diff_review`
- 规则：`semantic-review`
- 判断：可暂缓
- 置信度：中
- 原因：diff hunk 显示 out.handling_type_ 设置为 CurveBendType::kOutOfPolicy 的代码被移除，但未提供完整上下文。可能这是重构的一部分，handling_type_ 的计算逻辑已变更，需结合其他代码确认。
- 影响：若下游代码依赖 kOutOfPolicy 类型，可能影响错误处理或日志记录，但风险较低。
- 建议：检查下游使用 handling_type_ 的代码，确保类型变更不会导致逻辑错误。

### 5. low | dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.h:55
- 工具：`llm_diff_review`
- 规则：`semantic-review`
- 判断：可暂缓
- 置信度：高
- 原因：diff hunk 显示注释被截断，但实际代码中注释完整描述了 TrimByLargeGap 函数的功能。工具可能误报了注释不完整的问题，实际影响可维护性但风险低。
- 影响：注释不完整可能降低代码可读性，但不影响功能。
- 建议：无需立即修复，可在后续代码整理中完善注释。

### 6. low | dd_src/dd_route_guide/dd_bezier_curve_refactored/dd_curve_manager.cpp:154
- 工具：`cppcheck`
- 规则：`constParameterReference`
- 判断：建议修复
- 置信度：高
- 原因：code context 显示 CheckFallbackCondition 函数的 projected_point 参数未被修改，可声明为 const 引用以提高代码安全性和可读性。
- 影响：无功能影响，但优化后能防止意外修改，提升代码质量。
- 建议：将参数类型改为 const RGGPSPoint_t& projected_point。

### 7. low | dd_src/dd_route_guide/dd_bezier_curve_refactored/dd_curve_manager.h:91
- 工具：`cppcheck`
- 规则：`functionStatic`
- 判断：需要人工确认
- 置信度：高
- 原因：code context 显示 ShouldFallbackArcCCW 函数未访问类成员，可声明为 static。但需确认函数是否在类外部调用或依赖类状态。
- 影响：无功能影响，但声明为 static 可明确函数作用域，可能提升性能。
- 建议：检查函数使用情况，若确实不依赖实例，可添加 static 关键字。

### 8. low | dd_src/dd_route_guide/dd_event_checker/dd_rg_event_checker_voice.cpp:4983
- 工具：`cppcheck`
- 规则：`shadowFunction`
- 判断：疑似误报
- 置信度：高
- 原因：code context 显示局部变量 isCanPlay 并未遮蔽外层函数，外层无同名函数。工具可能误判了变量名与函数名的冲突。
- 影响：无实际风险，代码逻辑正确。
- 建议：无需修复，可忽略此告警。

### 9. info | dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/dd_bend_candidate_collector.cpp:1
- 工具：`llm_diff_review`
- 规则：`semantic-review`
- 判断：需要人工确认
- 置信度：高
- 原因：diff hunk 显示新增了 184 行代码的文件，引入了弯道候选收集逻辑。需确认新逻辑与原有系统的集成是否完整，例如是否替换了旧有收集器。
- 影响：新增代码可能影响弯道检测的准确性和性能，需测试验证。
- 建议：运行相关测试用例，确保新收集器与下游融合策略协同工作正常。

## 建议动作
- 优先修复两个 high 严重性的空指针访问风险，确保 fused_peaks 和 merged_bends 在访问前非空。
- 人工确认 ShouldSkipGentleBends 函数的移除是否影响业务逻辑，必要时补充测试。
- 优化代码质量，将 CheckFallbackCondition 的参数改为 const 引用。
- 验证新增的 dd_bend_candidate_collector.cpp 与现有系统的集成，执行回归测试。
- 定期运行完整代码扫描，以覆盖 diff 模式未分析的部分。

## 附录：关键日志
- discover_repo: languages=['cpp', 'java'], build_systems=['cmake', 'clang_compile_db', 'gradle']
- collect_targets detail: diff_candidates=33, code_diff_files=30, changed_lines=1686
- collect_targets: mode=diff, total_targets=12
- choose_toolchains: mode=diff, languages=['cpp'], toolchains={'cpp': ['clang-tidy', 'cppcheck'], 'security': ['semgrep']}
- run_cpp_scanners: using compile_db intersection units=7 (diff_targets=7)
- run_cpp_scanners: diff mode -> cppcheck uses explicit file list
- run_cpp_scanners: processed 7 files, findings=259
- run_security_scanners: exit=0, findings=0
- normalize_findings(enhanced): normalized=3, dropped=0, diff_filtered=256, diff_files=12, diff_filter=only
- llm_triage: disabled (mode=diff), fallback_local=3
- llm_triage: triaged=3
- build_report: summary={'total': 9, 'critical': 0, 'high': 2, 'medium': 1, 'low': 5, 'info': 1}, static={'total': 3, 'critical': 0, 'high': 0, 'medium': 0, 'low': 3, 'info': 0}, llm_review={'total': 6, 'critical': 0, 'high': 2, 'medium': 1, 'low': 2, 'info': 1}, merged={'total': 9, 'critical': 0, 'high': 2, 'medium': 1, 'low': 5, 'info': 1}
- Report written to: /Users/didi/work/sdk-env/code_scan_agent/artifacts/report.json

## 附录：命中代码上下文
### 1. dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_peak_fusion_strategy.cpp:178

```cpp
(code context unavailable: file not found in working tree)
```

```diff
diff --git a/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_peak_fusion_strategy.cpp b/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_peak_fusion_strategy.cpp
new file mode 100644
index 000000000..39388d995
--- /dev/null
+++ b/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_peak_fusion_strategy.cpp
@@ -0,0 +1,183 @@
+// dd_peak_fusion_strategy.cpp
+#include "dd_peak_fusion_strategy.h"
+#include "logger.h"
+#include <algorithm>
+#include <cmath>
+#include <numeric>
+
+namespace dd_curve {
+
+namespace {
+
+// 避免重载歧义的绝对值
+inline double absd(double x) { return x >= 0.0 ? x : -x; }
+
+// i..j 的弧长近似（累加 arc_len_）
+static double ArcLenBetween(const std::vector<CurveBendCandidate>& input, size_t i, size_t j) {
+    if (input.empty() || i == j) return 0.0;
+    if (i > j) std::swap(i, j);
+    double s = 0.0;
+    for (size_t k = i + 1; k <= j; ++k) s += std::max(0.0, input[k].geometry_.next_bend_dis_len_);
+    return s;
+}
+
+// 峰强度比较：strength > |turn| > |curvature| > 早路网索引
+static bool StrongerPeakFirst(const CurveBendCandidate& a, const CurveBendCandidate& b) {
+    const auto& geom_a = a.geometry_;
+    const auto& geom_b = b.geometry_;
+    const auto& kin_a  = a.kinematics_;
+    const auto& kin_b  = b.kinematics_;
+    
+    // 1. 优先比较弯道强度（大在前）
+    if (geom_a.strength_ != geom_b.strength_) {
+        return geom_a.strength_ > geom_b.strength_;
+    }
+    
+    // 2. 次要比较转角绝对值（大在前）
+    const double turn_a = std::fabs(geom_a.turn_deg_);
+    const double turn_b = std::fabs(geom_b.turn_deg_);
+    if (turn_a != turn_b) {
+        return turn_a > turn_b;
+    }
+    
+    // 3. 再比较曲率绝对值（大在前）
+    const double curv_a = std::fabs(geom_a.curvature_);
+    const double curv_b = std::fabs(geom_b.curvature_);
+    if (curv_a != curv_b) {
+        return curv_a > curv_b;
+    }
+    
+    // 4. 最后用索引（小在前，保证稳定性）
+    return kin_a.route_idx_ < kin_b.route_idx_;
+}
+
+
+} // namespace
+
+// ---------- PeakFusionStrategy ----------
+
+void PeakFusionStrategy::Reset() {
+    peak_buffer_.clear();
+}
+
+int PeakFusionStrategy::Fuse(const std::vector<CurveBendCandidate>& raw_candidates, CurveBendSegment& segment) {
+    peak_buffer_.clear();
+    if (raw_candidates.empty()) {
+        return static_cast<int>(FusionError::kEmptyInput);
+    }
+
+    // 1) 初筛：收集局部峰索引（带最小转角阈值）
+    std::vector<size_t> peak_indices;
+    if (!CollectLocalPeaks(raw_candidates, peak_indices)) {
+        return static_cast<int>(FusionError::kNoLocalPeaks);
+    }
+
+    // 2) 邻峰聚类：同向 + 近距离 合并为代表峰；反向（S 型）不合并
+    std::vector<MergedBendPoint> fused_peaks;
+    ClusterNeighborPeaks(raw_candidates, peak_indices, fused_peaks);
+    if (fused_peaks.empty()) {
+        return static_cast<int>(FusionError::kNoFusedPeaks);
+    }
+
+    // 3) 写出结果 + 缓存
+    BuildFusedOutput(fused_peaks, segment);
+    peak_buffer_.insert(peak_buffer_.end(), fused_peaks.begin(), fused_peaks.end());
+
+    return static_cast<int>(FusionError::kSuccess);
+}
+
+// ========== 私有辅助：单点局部峰判定 ==========
+inline bool PeakFusionStrategy::IsLocalPeak(const std::vector<CurveBendCandidate>& input, size_t i) const {
+    const size_t n = input.size();
+    const auto& center_geom = input[i].geometry_;
+    const double center_turn = absd(center_geom.turn_deg_);
+    const double center_curv = absd(center_geom.curvature_);
+    
+    const auto* left_geom  = (i > 0)     ? &input[i - 1].geometry_ : nullptr;
+    const auto* right_geom = (i + 1 < n) ? &input[i + 1].geometry_ : nullptr;
+
+    // 限制邻居：仅当相对弧长 <= 5m 才算有效
+    bool has_valid_left  = left_geom  != nullptr && center_geom.next_bend_dis_len_ <= 2.0;
+    bool has_valid_right = right_geom != nullptr && right_geom->next_bend_dis_len_ <= 2.0;
+    
+    const double left_turn  = has_valid_left  ? absd(left_geom->turn_deg_)      : -1.0;
+    const double right_turn = has_valid_right ? absd(right_geom->turn_deg_)     : -1.0;
+
+    // turn 为主信号：右侧严格小，避免平台重复入选
+    const bool peak_turn = (center_turn >= left_turn) && (center_turn > right_turn);
+    if (peak_turn) return true;
+
+    // curvature 兜底
+    const double left_curv  = has_valid_left  ? absd(left_geom->curvature_)  : -1.0;
+    const double right_curv = has_valid_right ? absd(right_geom->curvature_) : -1.0;
+    const bool peak_curv = (center_curv >= left_curv) && (center_curv > right_curv);
+    return peak_curv;
```

### 2. dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp:165

```cpp
(code context unavailable: file not found in working tree)
```

```diff
diff --git a/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp b/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp
new file mode 100644
index 000000000..f7569a411
--- /dev/null
+++ b/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp
@@ -0,0 +1,170 @@
+#include "dd_window_fusion_strategy.h"
+#include <algorithm>
+#include <cmath>
+#include "logger.h"
+
+namespace dd_curve {
+
+// 清空内部状态（本策略无内部缓存）
+void WindowFusionStrategy::Reset() {
+    
+}
+
+// 融合一个窗口内的拐点为代表点
+MergedBendPoint WindowFusionStrategy::FuseWindowToRepresentative(const std::vector<CurveBendCandidate>& window_slice) const {
+    constexpr double kDeg2Rad = M_PI / 180.0;
+    constexpr double kMinArcLen = 1e-3;
+
+    MergedBendPoint merged;
+    if (window_slice.empty()) {
+        sdklog(Logger::LogTarget::LBAMAI, Logger::LogLevel::LINFO,
+               "FuseWindowToRepresentative: empty input window_slice, return default MergedBendPoint");
+        return merged;
+    }
+
+    // === Step 1: 找出主控点（角度最大的拐点） ===
+    std::size_t main_idx = 0;
+    double max_abs_turn = 0.0;
+    for (std::size_t i = 0; i < window_slice.size(); ++i) {
+        double abs_turn = std::fabs(window_slice[i].geometry_.turn_deg_);
+        if (abs_turn > max_abs_turn) {
+            max_abs_turn = abs_turn;
+            main_idx = i;
+        }
+    }
+    merged.main_corner_ = window_slice[main_idx];
+
+    // === Step 2: 累积窗口总转角与总弧长，重新计算曲率与强度 ===
+    double arc_sum = 0.0, turn_sum = 0.0;
+    for (const auto& bend_candidate : window_slice) {
+        arc_sum  += std::max(bend_candidate.geometry_.next_bend_dis_len_, 0.0);
+        turn_sum += bend_candidate.geometry_.turn_deg_;
+    }
+    
+    arc_sum = std::max(arc_sum, kMinArcLen);
+    double turn_rad = turn_sum * kDeg2Rad;
+    double curvature = turn_rad / arc_sum;
+    double strength = std::fabs(turn_rad) * std::fabs(curvature);
+
+    auto& geo = merged.main_corner_.geometry_;
+    geo.next_bend_dis_len_   = arc_sum;
+    geo.turn_deg_  = turn_sum;
+    geo.curvature_ = curvature;
+    geo.strength_  = strength;
+
+    merged.bend_start_ = window_slice.front().kinematics_;
+    merged.bend_end_   = window_slice.back().kinematics_;
+    return merged;
+}
+
+// 主函数：滑窗融合入口
+int WindowFusionStrategy::Fuse(const std::vector<CurveBendCandidate>& input, CurveBendSegment& out) {
+    if (input.empty()) return (int)FusionError::kEmptyInput;
+    std::vector<CurveBendCandidate> bend_candidates;
+    
+    if (!SanitizeAndSort(input, bend_candidates)) {
+        return (int)FusionError::kSanitizeFailed;
+    }
+    
+    // 对头部大间距进行截断处理
+    if (!TrimByLargeGap(bend_candidates)) {
+        return (int)FusionError::kLargeGapTrimFailed;
+    }
+ 
+    // 滑窗参数设置
+    double window_span_m       = std::max(5.0, window_fusion_cfg_.window_span_m);
+    double window_stride_ratio = std::min(std::max(window_fusion_cfg_.window_step_ratio, 0.1), 1.0);
+    double window_stride_m     = std::max(1.0, window_span_m * window_stride_ratio);
+    if (bend_candidates.size() < 3) {
+        window_span_m   = 18.0;
+        window_stride_m = 6.0;
+    }
+
+    std::vector<MergedBendPoint> merged_bends;
+    SlideAndFuse(bend_candidates, window_span_m, window_stride_m, merged_bends);
+    if (merged_bends.empty()) {
+        sdklog(Logger::LogTarget::LBAMAI, Logger::LogLevel::LINFO,
+               "WindowFusionStrategy::Fuse: no merged result after sliding window fusion. points size=%zu", bend_candidates.size());
+        return (int)FusionError::kNoMergedResult;
+    }
+
+    EmitSegment(merged_bends, out);
+    return (int)FusionError::kSuccess;
+}
+
+// 对前缀大间距拐点进行裁剪
+bool WindowFusionStrategy::TrimByLargeGap(std::vector<CurveBendCandidate>& bend_candidates) const {
+    const double gap_thresh_m = 40.0;
+    std::size_t i = 1;
+    while (i < bend_candidates.size()) {
+        double gap = std::max(0.0, bend_candidates[i].geometry_.next_bend_dis_len_);
+        if (gap > gap_thresh_m) break;
+        ++i;
+    }
+    if (i < bend_candidates.size()) {
+        bend_candidates.resize(i);
+    }
+    return !bend_candidates.empty();
+}
+
+// 清洗输入
+bool WindowFusionStrategy::SanitizeAndSort(const std::vector<CurveBendCandidate>& in, std::vector<CurveBendCandidate>& out) {
+    out.clear();
+    for (const auto& bend_candidate : in) {
+        const auto& g = bend_candidate.geometry_;
```

### 3. dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp:10

```cpp
(code context unavailable: file not found in working tree)
```

```diff
diff --git a/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp b/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp
new file mode 100644
index 000000000..f7569a411
--- /dev/null
+++ b/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp
@@ -0,0 +1,170 @@
+#include "dd_window_fusion_strategy.h"
+#include <algorithm>
+#include <cmath>
+#include "logger.h"
+
+namespace dd_curve {
+
+// 清空内部状态（本策略无内部缓存）
+void WindowFusionStrategy::Reset() {
+    
+}
+
+// 融合一个窗口内的拐点为代表点
+MergedBendPoint WindowFusionStrategy::FuseWindowToRepresentative(const std::vector<CurveBendCandidate>& window_slice) const {
+    constexpr double kDeg2Rad = M_PI / 180.0;
+    constexpr double kMinArcLen = 1e-3;
+
+    MergedBendPoint merged;
+    if (window_slice.empty()) {
+        sdklog(Logger::LogTarget::LBAMAI, Logger::LogLevel::LINFO,
+               "FuseWindowToRepresentative: empty input window_slice, return default MergedBendPoint");
+        return merged;
+    }
+
+    // === Step 1: 找出主控点（角度最大的拐点） ===
+    std::size_t main_idx = 0;
+    double max_abs_turn = 0.0;
+    for (std::size_t i = 0; i < window_slice.size(); ++i) {
+        double abs_turn = std::fabs(window_slice[i].geometry_.turn_deg_);
+        if (abs_turn > max_abs_turn) {
+            max_abs_turn = abs_turn;
+            main_idx = i;
+        }
+    }
+    merged.main_corner_ = window_slice[main_idx];
+
+    // === Step 2: 累积窗口总转角与总弧长，重新计算曲率与强度 ===
+    double arc_sum = 0.0, turn_sum = 0.0;
+    for (const auto& bend_candidate : window_slice) {
+        arc_sum  += std::max(bend_candidate.geometry_.next_bend_dis_len_, 0.0);
+        turn_sum += bend_candidate.geometry_.turn_deg_;
+    }
+    
+    arc_sum = std::max(arc_sum, kMinArcLen);
+    double turn_rad = turn_sum * kDeg2Rad;
+    double curvature = turn_rad / arc_sum;
+    double strength = std::fabs(turn_rad) * std::fabs(curvature);
+
+    auto& geo = merged.main_corner_.geometry_;
+    geo.next_bend_dis_len_   = arc_sum;
+    geo.turn_deg_  = turn_sum;
+    geo.curvature_ = curvature;
+    geo.strength_  = strength;
+
+    merged.bend_start_ = window_slice.front().kinematics_;
+    merged.bend_end_   = window_slice.back().kinematics_;
+    return merged;
+}
+
+// 主函数：滑窗融合入口
+int WindowFusionStrategy::Fuse(const std::vector<CurveBendCandidate>& input, CurveBendSegment& out) {
+    if (input.empty()) return (int)FusionError::kEmptyInput;
+    std::vector<CurveBendCandidate> bend_candidates;
+    
+    if (!SanitizeAndSort(input, bend_candidates)) {
+        return (int)FusionError::kSanitizeFailed;
+    }
+    
+    // 对头部大间距进行截断处理
+    if (!TrimByLargeGap(bend_candidates)) {
+        return (int)FusionError::kLargeGapTrimFailed;
+    }
+ 
+    // 滑窗参数设置
+    double window_span_m       = std::max(5.0, window_fusion_cfg_.window_span_m);
+    double window_stride_ratio = std::min(std::max(window_fusion_cfg_.window_step_ratio, 0.1), 1.0);
+    double window_stride_m     = std::max(1.0, window_span_m * window_stride_ratio);
+    if (bend_candidates.size() < 3) {
+        window_span_m   = 18.0;
+        window_stride_m = 6.0;
+    }
+
+    std::vector<MergedBendPoint> merged_bends;
+    SlideAndFuse(bend_candidates, window_span_m, window_stride_m, merged_bends);
+    if (merged_bends.empty()) {
+        sdklog(Logger::LogTarget::LBAMAI, Logger::LogLevel::LINFO,
+               "WindowFusionStrategy::Fuse: no merged result after sliding window fusion. points size=%zu", bend_candidates.size());
+        return (int)FusionError::kNoMergedResult;
+    }
+
+    EmitSegment(merged_bends, out);
+    return (int)FusionError::kSuccess;
+}
+
+// 对前缀大间距拐点进行裁剪
+bool WindowFusionStrategy::TrimByLargeGap(std::vector<CurveBendCandidate>& bend_candidates) const {
+    const double gap_thresh_m = 40.0;
+    std::size_t i = 1;
+    while (i < bend_candidates.size()) {
+        double gap = std::max(0.0, bend_candidates[i].geometry_.next_bend_dis_len_);
+        if (gap > gap_thresh_m) break;
+        ++i;
+    }
+    if (i < bend_candidates.size()) {
+        bend_candidates.resize(i);
+    }
+    return !bend_candidates.empty();
+}
+
+// 清洗输入
+bool WindowFusionStrategy::SanitizeAndSort(const std::vector<CurveBendCandidate>& in, std::vector<CurveBendCandidate>& out) {
+    out.clear();
+    for (const auto& bend_candidate : in) {
+        const auto& g = bend_candidate.geometry_;
```

### 4. dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp:70

```cpp
(code context unavailable: file not found in working tree)
```

```diff
diff --git a/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp b/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp
new file mode 100644
index 000000000..f7569a411
--- /dev/null
+++ b/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.cpp
@@ -0,0 +1,170 @@
+#include "dd_window_fusion_strategy.h"
+#include <algorithm>
+#include <cmath>
+#include "logger.h"
+
+namespace dd_curve {
+
+// 清空内部状态（本策略无内部缓存）
+void WindowFusionStrategy::Reset() {
+    
+}
+
+// 融合一个窗口内的拐点为代表点
+MergedBendPoint WindowFusionStrategy::FuseWindowToRepresentative(const std::vector<CurveBendCandidate>& window_slice) const {
+    constexpr double kDeg2Rad = M_PI / 180.0;
+    constexpr double kMinArcLen = 1e-3;
+
+    MergedBendPoint merged;
+    if (window_slice.empty()) {
+        sdklog(Logger::LogTarget::LBAMAI, Logger::LogLevel::LINFO,
+               "FuseWindowToRepresentative: empty input window_slice, return default MergedBendPoint");
+        return merged;
+    }
+
+    // === Step 1: 找出主控点（角度最大的拐点） ===
+    std::size_t main_idx = 0;
+    double max_abs_turn = 0.0;
+    for (std::size_t i = 0; i < window_slice.size(); ++i) {
+        double abs_turn = std::fabs(window_slice[i].geometry_.turn_deg_);
+        if (abs_turn > max_abs_turn) {
+            max_abs_turn = abs_turn;
+            main_idx = i;
+        }
+    }
+    merged.main_corner_ = window_slice[main_idx];
+
+    // === Step 2: 累积窗口总转角与总弧长，重新计算曲率与强度 ===
+    double arc_sum = 0.0, turn_sum = 0.0;
+    for (const auto& bend_candidate : window_slice) {
+        arc_sum  += std::max(bend_candidate.geometry_.next_bend_dis_len_, 0.0);
+        turn_sum += bend_candidate.geometry_.turn_deg_;
+    }
+    
+    arc_sum = std::max(arc_sum, kMinArcLen);
+    double turn_rad = turn_sum * kDeg2Rad;
+    double curvature = turn_rad / arc_sum;
+    double strength = std::fabs(turn_rad) * std::fabs(curvature);
+
+    auto& geo = merged.main_corner_.geometry_;
+    geo.next_bend_dis_len_   = arc_sum;
+    geo.turn_deg_  = turn_sum;
+    geo.curvature_ = curvature;
+    geo.strength_  = strength;
+
+    merged.bend_start_ = window_slice.front().kinematics_;
+    merged.bend_end_   = window_slice.back().kinematics_;
+    return merged;
+}
+
+// 主函数：滑窗融合入口
+int WindowFusionStrategy::Fuse(const std::vector<CurveBendCandidate>& input, CurveBendSegment& out) {
+    if (input.empty()) return (int)FusionError::kEmptyInput;
+    std::vector<CurveBendCandidate> bend_candidates;
+    
+    if (!SanitizeAndSort(input, bend_candidates)) {
+        return (int)FusionError::kSanitizeFailed;
+    }
+    
+    // 对头部大间距进行截断处理
+    if (!TrimByLargeGap(bend_candidates)) {
+        return (int)FusionError::kLargeGapTrimFailed;
+    }
+ 
+    // 滑窗参数设置
+    double window_span_m       = std::max(5.0, window_fusion_cfg_.window_span_m);
+    double window_stride_ratio = std::min(std::max(window_fusion_cfg_.window_step_ratio, 0.1), 1.0);
+    double window_stride_m     = std::max(1.0, window_span_m * window_stride_ratio);
+    if (bend_candidates.size() < 3) {
+        window_span_m   = 18.0;
+        window_stride_m = 6.0;
+    }
+
+    std::vector<MergedBendPoint> merged_bends;
+    SlideAndFuse(bend_candidates, window_span_m, window_stride_m, merged_bends);
+    if (merged_bends.empty()) {
+        sdklog(Logger::LogTarget::LBAMAI, Logger::LogLevel::LINFO,
+               "WindowFusionStrategy::Fuse: no merged result after sliding window fusion. points size=%zu", bend_candidates.size());
+        return (int)FusionError::kNoMergedResult;
+    }
+
+    EmitSegment(merged_bends, out);
+    return (int)FusionError::kSuccess;
+}
+
+// 对前缀大间距拐点进行裁剪
+bool WindowFusionStrategy::TrimByLargeGap(std::vector<CurveBendCandidate>& bend_candidates) const {
+    const double gap_thresh_m = 40.0;
+    std::size_t i = 1;
+    while (i < bend_candidates.size()) {
+        double gap = std::max(0.0, bend_candidates[i].geometry_.next_bend_dis_len_);
+        if (gap > gap_thresh_m) break;
+        ++i;
+    }
+    if (i < bend_candidates.size()) {
+        bend_candidates.resize(i);
+    }
+    return !bend_candidates.empty();
+}
+
+// 清洗输入
+bool WindowFusionStrategy::SanitizeAndSort(const std::vector<CurveBendCandidate>& in, std::vector<CurveBendCandidate>& out) {
+    out.clear();
+    for (const auto& bend_candidate : in) {
+        const auto& g = bend_candidate.geometry_;
```

### 5. dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.h:55

```cpp
(code context unavailable: file not found in working tree)
```

```diff
diff --git a/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.h b/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.h
new file mode 100644
index 000000000..a2746b7de
--- /dev/null
+++ b/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/bend_fusion_strategy/dd_window_fusion_strategy.h
@@ -0,0 +1,131 @@
+#ifndef DD_WINDOW_FUSION_STRATEGY_H_
+#define DD_WINDOW_FUSION_STRATEGY_H_
+
+#include <vector>
+#include "dd_curve_types.h"
+#include "dd_bend_fusion_strategy.h"
+
+namespace dd_curve {
+
+/**
+ * @brief 滑窗融合策略
+ *
+ * 目标：
+ *  - 在同向候选点序列上，按“窗口跨度(米) + 步长占比”构造滑窗；
+ *  - 每个窗口内进行候选聚合（以最强拐点为锚，按总转角/总弧长重算特征），输出单一代表点；
+ *  - 输出段的 corner_indices_ 即为这些“窗口代表点”序列，主拐点取 |turn| 最大者。
+ *
+ * 说明：
+ *  - corner_indices_ 中存储的是 CurveBendCandidate（而非索引）。
+ *  - 若上游已保证“天然有序 & 同向”，本策略主要在长度维度做滑窗与聚合。
+ *  - 窗口参数与阈值来自 window_fusion_cfg_（见 WindowFusionConfig）。
+ */
+class WindowFusionStrategy : public BendFusionStrategy {
+public:
+    WindowFusionStrategy() = default;
+    ~WindowFusionStrategy() override = default;
+
+    /// @return 策略名称
+    const char* Name() const override { return "WindowFusion"; }
+
+    /**
+     * @brief 重置内部状态
+     *
+     * 当前实现无持久状态，留空以便后续扩展（如缓存上一次窗口）。
+     */
+    void Reset() override;
+
+    /**
+     * @brief 滑窗融合主流程
+     *
+     * 步骤：
+     *  1) SanitizeAndSort：过滤 NaN/Inf 并按 route_idx_ 升序（如上游已有序，这一步等价稳妥拷贝+确认）；
+     *  2) ShouldSkipGentleBends：若为“连续小弯”（同向且角度都很小），直接早退；
+     *  3) 计算窗口参数（window_span_m / window_step_ratio → window_stride_m）；
+     *  4) SlideAndFuse：按窗口跨度/步长推进，对每个窗口 FuseWindowToRepresentative 生成代表点；
+     *  5) EmitSegment：写入 corner_indices_、primary_corner_idx_、bend_window_end_idx_ 等。
+     *
+     * @param input  输入候选点集合（建议已同向、按路线前进顺序；函数内仍会稳妥处理）
+     * @param out    输出融合后的弯道片段
+     * @return true  产生有效输出；false 无需输出（如输入为空/全被过滤/被判定为连续小弯）
+     */
+    virtual int Fuse(const std::vector<CurveBendCandidate>& input, CurveBendSegment& out) override;
+    
+private:
+    // ===================== 内部工具 =====================
+
+    /**
+     * @brief 将一个窗口内的候选聚合为“代表拐点”
+     *
+     * 规则：
+     *  - 选 |turn| 最大的候选作为几何锚（route_idx_/heading 等沿用它）；
+     *  - 对窗口内候选求总弧长与总转角，并据此重算 curvature/strength；
+     *  - 标记 is_primary_ = true。
+     *
+     * @param window 窗口内候选（建议已同向）
+     * @return 融合后的代表点
+     */
+    MergedBendPoint FuseWindowToRepresentative(const std::vector<CurveBendCandidate>& window) const;
+
+    /**
+     * @brief 过滤 NaN/Inf 并按 route_idx_ 升序
+     *
+     * 若上游已保证“天然有序”，此函数等价于“稳定过滤 + 再确认顺序”。
+     *
+     * @param in  原始输入
+     * @param out 过滤/排序后的输出
+     * @return true  out 非空
+     * @return false out 为空（无可用候选）
+     */
+    bool SanitizeAndSort(const std::vector<CurveBendCandidate>& in, std::vector<CurveBendCandidate>& out);
+
+    /**
+     * @brief 滑窗推进 + 聚合：在长度维度（弧长近似）上构造窗口并生成代表点
+     *
+     * 策略：非重叠滑窗。累计窗口跨度达到 window_span_m 或达到 window_stride_m
+     * 的“步长目标”且再吞一个会明显超窗时收窗；窗口内容交由 FuseWindowToRepresentative 聚合。
+     *
+     * @param candidates      已清洗&有序的候选序列
+     * @param window_span_m   单窗目标跨度（米）
+     * @param window_stride_m 窗口推进步长（米），通常 = window_span_m * window_step_ratio
+     * @param reps            输出：每个窗口对应的代表点
+     */
+    void SlideAndFuse(const std::vector<CurveBendCandidate>& candidates, double window_span_m, double window_stride_m, std::vector<MergedBendPoint>& reps) const;
+    /**
+     * @brief 按“大间距”裁剪候选拐点序列
+     *
+     * 功能：
+     *   - 在候选拐点序列中，从第 2 个点开始依次检查相邻点之间的弧长（arc_len_）。
+     *   - 一旦发现某个弧长 gap 超过阈值（split_gap_thresh_m，默认 40m），
+     *     就截断序列，只保留 [0, i) 的前缀，不包含大间距后的点。
+     *   - 若未发现大间距，则保留原序列。
+     *
+     * 使用场景：
+     *   - 用于处理「弯-直-弯」场景，避免把直线后的第二个弯合并进当前弯道片段。
+     *   - 常在融合阶段调用，长缓弯判定失败后，再做一次裁剪。
+     *
+     * @param candidates [in/out] 候选拐点序列，函数内会原地截断
+     * @return true  剩余序列非空，可继续处理
+     * @return false 剩余序列为空（极端情况），应直接返回无效结果
+     */
+    bool TrimByLargeGap(std::vector<CurveBendCandidate>& candidates) const;
+    /**
+     * @brief 将代表点序列写入输出段（挑选主拐点等）
+     *
```

### 6. dd_src/dd_route_guide/dd_bezier_curve_refactored/dd_curve_manager.cpp:154

```cpp
   134 |     return project_point;
   135 | }
   136 | 
   137 | const CurveStateMachine& DdCurveManager::Fsm() const {
   138 |     assert(fsm_ && "Fsm() called before fsm_ is initialized");
   139 |     return *fsm_;
   140 | }
   141 | 
   142 | const CurveSegmentDetector& DdCurveManager::Detector() const {
   143 |     assert(detector_ && "Detector() called before detector_ is initialized");
   144 |     return *detector_;
   145 | }
   146 | 
   147 | 
   148 | void DdCurveManager::ClearCache() {
   149 |     last_point_valid_ = false;
   150 |     ops_.ClearCache();
   151 |     if (detector_) detector_->ResetState();
   152 | }
   153 | 
>  154 | bool DdCurveManager::CheckFallbackCondition(const CurveBendSegment& bend_segment, const RGGPSPoint_t& matched_point, RGGPSPoint_t& projected_point) const {
   155 |     if (bend_segment.handling_type_ == CurveBendType::kLongGentle) return true;
   156 | 
   157 |     auto* cps_ptr = ops_.GetControlPoints();
   158 |     if (cps_ptr == nullptr || cps_ptr->empty()) return true;
   159 |     const auto& cps = *cps_ptr;
   160 | 
   161 |     const RGGeoPoint_t& ref  = last_point_valid_ ? last_point_.routeMapPos.geoPoint : matched_point.routeMapPos.geoPoint;
   162 |     const RGGeoPoint_t& proj = projected_point.routeMapPos.geoPoint;
   163 | 
   164 |     if (ops_.GetStrategyType() == CurveGenerationStrategyType::Arc && cps.size() > 2) {
   165 |         return ShouldFallbackArcCCW(cps, ref, proj);
   166 |     }
   167 |     return ShouldFallbackGeneric(cps, ref, proj, matched_point.heading, last_point_valid_);
   168 | }
   169 | 
   170 | void DdCurveManager::ClampProjectionForward(const CurveBendSegment& bend_segment, const RGGPSPoint_t& matched_point, RGGPSPoint_t& projected_point, float heading) const {
   171 |     // 1. 状态检查：Active及以下无需修正（尚未退出阶段）
   172 |     if (!last_point_valid_ && fsm_->GetState() <= CurveStateMachine::BendStateID::Active) {
   173 |         return;
   174 |     }
```

```diff
diff --git a/dd_src/dd_route_guide/dd_bezier_curve_refactored/dd_curve_manager.cpp b/dd_src/dd_route_guide/dd_bezier_curve_refactored/dd_curve_manager.cpp
index 68cdc4111..658c65ea0 100644
--- a/dd_src/dd_route_guide/dd_bezier_curve_refactored/dd_curve_manager.cpp
+++ b/dd_src/dd_route_guide/dd_bezier_curve_refactored/dd_curve_manager.cpp
@@ -1,280 +1,166 @@
 // dd_curve_manager.cpp
 #include "dd_curve_manager.h"
-#include "dd_curve_segment_detector.h"
+#include "bend_segment_builder/dd_curve_segment_pipeline.h"
+#include "dd_projection_processor.h"
 #include "dd_curve_state_machine.h"
-#include "dd_curve_tools.h"
+#include "dd_curve_types.h"
 #include "curve_strategy/dd_arc_curve_strategy.h"
 #include "curve_strategy/dd_de_casteljau_strategy.h"
 #include "logger.h"
 #include <cassert>
-#include <utility>
 #include <memory>
 
 namespace dd_curve {
 // ========================== DdCurveManager::InternalOps ==========================
 
 DdCurveManager::InternalOps::InternalOps(const StrategyMap* strategies)
 : strategies_(strategies) {
     assert(strategies_ != nullptr && "strategies_ must not be null");
 }
 
 DdCurveManager::InternalOps::~InternalOps() {}
 
 int DdCurveManager::InternalOps::Project(const CurveBendSegment& window, const RGGPSPoint_t& gps, RGGPSPoint_t& project_point, const DDRouteData& route) {
     if (strategies_ == nullptr || strategies_->empty()) {
         sdklog(Logger::LogTarget::LBAMAI, Logger::LogLevel::LINFO,
                "DdCurveManager::InternalOps::Project: Invalid parameters");
         return static_cast<int>(CurveStatus::kManager_NoStrategies);
     }
 
-    if (window.handling_type_ == CurveBendType::kLongGentle ||
-        window.handling_type_ == CurveBendType::kCircular) {
+    if (!window.is_handling_type_allowed()) {
         sdklog(Logger::LogTarget::LBAMAI, Logger::LogLevel::LINFO,
                "DdCurveManager::InternalOps::Project: Long gentle/circular bend, no curve projection");
         return static_cast<int>(CurveStatus::kNotSupported);
     }
-    
-    switch (window.handling_type_) {
-        case CurveBendType::kUBendUturn:
-        case CurveBendType::kSingleLinkPreUturn:
-        case CurveBendType::kSingleLinkUturn:
-        case CurveBendType::kUBendPreUturn:
-            strategy_type_ = CurveGenerationStrategyType::Arc;
-            break;
-        default:
-            strategy_type_ = CurveGenerationStrategyType::BezierDeCasteljau;
-            break;
-    }
 
+    strategy_type_ = window.preferred_strategy();
     auto it_find = strategies_->find(strategy_type_);
     if (it_find == strategies_->end()) {
         return static_cast<int>(CurveStatus::kManager_StrategyNotFound);
     }
 
     DDCurveGenerationStrategy* bez = it_find->second.get();
     if (bez == nullptr) {
         return static_cast<int>(CurveStatus::kManager_StrategyNull);
     }
 
     return bez->Project(route, window, gps, project_point);
 }
 
 
 // =============================== DdCurveManager 本体 ===============================
 DdCurveManager::DdCurveManager()
 : fsm_(nullptr),
-detector_(nullptr),
+pipeline_(nullptr),
 ops_(&strategies_),
 route_data_(nullptr),
 route_id_(0),
-last_point_valid_(false) {
+last_point_valid_(false),
+projection_count_(0) {
     RegisterStrategy(CurveGenerationStrategyType::BezierDeCasteljau, std::unique_ptr<DDCurveGenerationStrategy>(new DeCasteljauStrategy()));
     // 注册圆弧拟合策略
     RegisterStrategy(CurveGenerationStrategyType::Arc,std::unique_ptr<DDCurveGenerationStrategy>(new ArcCurveStrategy()));
 }
 
 DdCurveManager::~DdCurveManager() {
     ClearCache();
 }
 
 void DdCurveManager::RegisterStrategy(CurveGenerationStrategyType type, std::unique_ptr<DDCurveGenerationStrategy>&& strategy) {
     strategies_[type] = std::move(strategy);
 }
 
 void DdCurveManager::UpdateRouteContext(const DDRouteData* route_data, ng_uint64 route_id, bool in_reverse_link) {
     const bool changed = (route_id_ != route_id) || (route_data_ != route_data);
     route_data_ = route_data;
     route_id_   = route_id;
     
-    if (!detector_) detector_.reset(new CurveSegmentDetector());
+    if (!pipeline_) pipeline_.reset(new CurveSegmentPipeline());
     if (!fsm_)      fsm_.reset(new CurveStateMachine());
     
-    detector_->UpdateCache(in_reverse_link);
+    pipeline_->UpdateCache(in_reverse_link);
     if (changed) {
         ClearCache();
     }
 }
 
 RGGPSPoint_t DdCurveManager::Tick(const RGGPSPoint_t& gps, const RGGPSPoint_t& matchedPoint) {
-    if (!route_data_ || !detector_ || !fsm_) return matchedPoint;
-    if(fsm_->GetState() == CurveStateMachine::BendStateID::Idle) {
-        detector_->DetectSegment(matchedPoint, *route_data_);
+    if (!route_data_ || !pipeline_ || !fsm_) return matchedPoint;
+
+    // 1. 状态重置：Idle 状态下更新 Pipeline 并清理缓存
+    if (fsm_->GetState() == CurveStateMachine::BendStateID::Idle) {
```

### 7. dd_src/dd_route_guide/dd_bezier_curve_refactored/dd_curve_manager.h:91

```cpp
    71 |         const std::vector<RGGeoPoint_t>* GetControlPoints() const {
    72 |             const auto* strategy = GetCurrentStrategy();
    73 |             if (!strategy) {
    74 |                 return nullptr;
    75 |             }
    76 |             return &strategy->GetControlPoints();
    77 |         }
    78 |         
    79 |         
    80 |     private:
    81 |         const StrategyMap*              strategies_;   // 不拥有，只读
    82 |         CurveGenerationStrategyType     strategy_type_;
    83 |     };
    84 |     
    85 | private:
    86 |     void ClearCache();
    87 |     // 将投影点夹到不落后于上一帧或绑路点
    88 |     void ClampProjectionForward(const CurveBendSegment& bend_segment, const RGGPSPoint_t& matched_point, RGGPSPoint_t& projected_point, float heading) const;
    89 |     // 返回 true 表示需要回退到绑路点
    90 |     bool CheckFallbackCondition(const CurveBendSegment& bend_segment, const RGGPSPoint_t& matched_point, RGGPSPoint_t& projected_point) const;
>   91 |     bool ShouldFallbackArcCCW(const std::vector<RGGeoPoint_t>& cps, const RGGeoPoint_t& ref, const RGGeoPoint_t& proj) const;
    92 |     bool ShouldFallbackGeneric(const std::vector<RGGeoPoint_t>& cps, const RGGeoPoint_t& ref, const RGGeoPoint_t& proj, double heading_deg, bool has_last) const;
    93 |     void EnforceExitMonotonicity(const CurveBendSegment& bend_segment, const RGGPSPoint_t& matched_point, RGGPSPoint_t& projected_point) const;
    94 |     
    95 |     void ApplyCurveType(const CurveBendSegment& window, RGGPSPoint_t& matched_point) const;
    96 |     
    97 | private:
    98 |     // —— 核心状态组件 —— //
    99 |     std::unique_ptr<CurveStateMachine>    fsm_;       ///< 弯道状态机：管理进入/保持/退出状态
   100 |     std::unique_ptr<CurveSegmentDetector> detector_;  ///< 拐点检测器：逐帧扫描前方路径，产出候选弯道片段
   101 |     
   102 |     // —— 曲线生成策略 —— //
   103 |     StrategyMap                           strategies_; ///< 策略集合：按类型持有具体曲线生成算法实现
   104 |     InternalOps                           ops_;        ///< 内部工具：封装策略选择、投影、运算操作（不拥有策略本身）
   105 |     
   106 |     // —— 路网上下文 —— //
   107 |     const DDRouteData*                    route_data_; ///< 当前绑定的路线数据（不拥有；调用方需保证存活期有效）
   108 |     ng_uint64                             route_id_;   ///< 当前路线 ID（用于判定是否需要清理并重建策略/缓存）
   109 |     ///<
   110 |     RGGPSPoint_t last_point_;  //位置
   111 |     bool last_point_valid_;
```

```diff
diff --git a/dd_src/dd_route_guide/dd_bezier_curve_refactored/dd_curve_manager.h b/dd_src/dd_route_guide/dd_bezier_curve_refactored/dd_curve_manager.h
index 67d9dfb83..8846f0a1d 100644
--- a/dd_src/dd_route_guide/dd_bezier_curve_refactored/dd_curve_manager.h
+++ b/dd_src/dd_route_guide/dd_bezier_curve_refactored/dd_curve_manager.h
@@ -67,48 +68,44 @@ public:
             }
             return it->second.get();
         }
         
         const std::vector<RGGeoPoint_t>* GetControlPoints() const {
             const auto* strategy = GetCurrentStrategy();
             if (!strategy) {
                 return nullptr;
             }
             return &strategy->GetControlPoints();
         }
         
         
     private:
         const StrategyMap*              strategies_;   // 不拥有，只读
         CurveGenerationStrategyType     strategy_type_;
     };
     
 private:
     void ClearCache();
-    // 将投影点夹到不落后于上一帧或绑路点
-    void ClampProjectionForward(const CurveBendSegment& bend_segment, const RGGPSPoint_t& matched_point, RGGPSPoint_t& projected_point, float heading) const;
-    // 返回 true 表示需要回退到绑路点
-    bool CheckFallbackCondition(const CurveBendSegment& bend_segment, const RGGPSPoint_t& matched_point, RGGPSPoint_t& projected_point) const;
-    bool ShouldFallbackArcCCW(const std::vector<RGGeoPoint_t>& cps, const RGGeoPoint_t& ref, const RGGeoPoint_t& proj) const;
-    bool ShouldFallbackGeneric(const std::vector<RGGeoPoint_t>& cps, const RGGeoPoint_t& ref, const RGGeoPoint_t& proj, double heading_deg, bool has_last) const;
-    void EnforceExitMonotonicity(const CurveBendSegment& bend_segment, const RGGPSPoint_t& matched_point, RGGPSPoint_t& projected_point) const;
-    
-    void ApplyCurveType(const CurveBendSegment& window, RGGPSPoint_t& matched_point) const;
+    void RefineProjection(const CurveBendSegment& bend_segment,
+                          const RGGPSPoint_t& matched_point,
+                          RGGPSPoint_t& projected_point,
+                          float heading) const;
     
 private:
     // —— 核心状态组件 —— //
     std::unique_ptr<CurveStateMachine>    fsm_;       ///< 弯道状态机：管理进入/保持/退出状态
-    std::unique_ptr<CurveSegmentDetector> detector_;  ///< 拐点检测器：逐帧扫描前方路径，产出候选弯道片段
+    std::unique_ptr<CurveSegmentPipeline> pipeline_;  ///< 弯道片段生成器：逐帧扫描前方路径，产出候选弯道片段
     
     // —— 曲线生成策略 —— //
     StrategyMap                           strategies_; ///< 策略集合：按类型持有具体曲线生成算法实现
     InternalOps                           ops_;        ///< 内部工具：封装策略选择、投影、运算操作（不拥有策略本身）
     
     // —— 路网上下文 —— //
     const DDRouteData*                    route_data_; ///< 当前绑定的路线数据（不拥有；调用方需保证存活期有效）
     ng_uint64                             route_id_;   ///< 当前路线 ID（用于判定是否需要清理并重建策略/缓存）
     ///<
     RGGPSPoint_t last_point_;  //位置
     bool last_point_valid_;
+    int projection_count_;
 };
 }
 #endif  // DD_CURVE_MANAGER_H_
```

### 8. dd_src/dd_route_guide/dd_event_checker/dd_rg_event_checker_voice.cpp:4983

```cpp
  4963 |             hasQLY = true;
  4964 |         }
  4965 | 
  4966 |         if (pstEvent.viInfo.targetSubKind == (int)VoiceMission_Snow) {
  4967 |             sdklog(Logger::LogTarget::LHAWAII, Logger::LogLevel::LINFO, "Snow-QLY=%d", hasQLY);
  4968 |         }
  4969 | 
  4970 |     }
  4971 | 
  4972 |     return hasQLY;
  4973 | }
  4974 | //----------------------------------------------------------------------------//
  4975 | // Func : 在有效timing内过滤事件
  4976 | // Param :
  4977 | // Return :
  4978 | //----------------------------------------------------------------------------//
  4979 | void DDRGEventCheckerVoice::filterGuideTypeValidEvents()
  4980 | {
  4981 |     for (int i = 0; i < (int) m_vectTmpSearchEvent.size(); i++) {
  4982 |         const RGEvent_t *pstEvent = m_vectTmpSearchEvent[i];
> 4983 |         bool isCanPlay = true;
  4984 |         // 是否事故高发地
  4985 |         const bool isDangerous = (RGVoiceTargetKind_WarningSign == pstEvent->viInfo.targetKind
  4986 |                                   &&
  4987 |                                   RGWarningSignKind_AccidentProneSections ==
  4988 |                                   pstEvent->viInfo.targetSubKind);
  4989 |         const bool isAiSafeNotify = (RGVoiceTargetKind_SDKAdd_SafetyNotify == pstEvent->viInfo.targetKind);
  4990 |         const bool isNGSafeNotify = (RGVoiceTargetKind_SAFETY_TIP == pstEvent->viInfo.targetKind &&
  4991 |                                     SafetyTipKind_Unknow != pstEvent->viInfo.targetSubKind && SafetyTipKind_UnpavedRoad != pstEvent->viInfo.targetSubKind);
  4992 |         const int guideType = m_pMgrDirectAccess->getGuideType_Direct();
  4993 |         const bool playQLY = m_playQLYAtLightGuide && hasQLYContent(*pstEvent);
  4994 |         switch (guideType) {
  4995 |             case RGEventGuide_EasyGuideType:    // 司机端轻导航只播事故高发地
  4996 |                 if ((!m_isForcePlayAccidentVoice || !isDangerous) && !isAiSafeNotify && !isNGSafeNotify && !playQLY) {
  4997 |                     isCanPlay = false;
  4998 |                 }
  4999 |                 break;
  5000 |             case RGEventGuide_Dolphin_FindWay:  // 探路模式只播电子眼和事故高发地
  5001 |             case RGEventGuide_Dolphin_Fast_FindWay: {
  5002 |                 // 是否电子眼
  5003 |                 const bool isCameraMonitor = (
```

```diff
diff --git a/dd_src/dd_route_guide/dd_event_checker/dd_rg_event_checker_voice.cpp b/dd_src/dd_route_guide/dd_event_checker/dd_rg_event_checker_voice.cpp
index 643bcfdc9..cb10bb5b5 100644
--- a/dd_src/dd_route_guide/dd_event_checker/dd_rg_event_checker_voice.cpp
+++ b/dd_src/dd_route_guide/dd_event_checker/dd_rg_event_checker_voice.cpp
@@ -4961,40 +4961,43 @@ bool DDRGEventCheckerVoice::hasQLYContent(const RGEvent_t& pstEvent) {
 
         if(hasUerEducationContent(&pstEvent)) {
             hasQLY = true;
         }
 
         if (pstEvent.viInfo.targetSubKind == (int)VoiceMission_Snow) {
             sdklog(Logger::LogTarget::LHAWAII, Logger::LogLevel::LINFO, "Snow-QLY=%d", hasQLY);
         }
 
     }
 
     return hasQLY;
 }
 //----------------------------------------------------------------------------//
 // Func : 在有效timing内过滤事件
 // Param :
 // Return :
 //----------------------------------------------------------------------------//
 void DDRGEventCheckerVoice::filterGuideTypeValidEvents()
 {
+    if (!m_pMgrDirectAccess) {
+	  return;
+	}
     for (int i = 0; i < (int) m_vectTmpSearchEvent.size(); i++) {
         const RGEvent_t *pstEvent = m_vectTmpSearchEvent[i];
         bool isCanPlay = true;
         // 是否事故高发地
         const bool isDangerous = (RGVoiceTargetKind_WarningSign == pstEvent->viInfo.targetKind
                                   &&
                                   RGWarningSignKind_AccidentProneSections ==
                                   pstEvent->viInfo.targetSubKind);
         const bool isAiSafeNotify = (RGVoiceTargetKind_SDKAdd_SafetyNotify == pstEvent->viInfo.targetKind);
         const bool isNGSafeNotify = (RGVoiceTargetKind_SAFETY_TIP == pstEvent->viInfo.targetKind &&
                                     SafetyTipKind_Unknow != pstEvent->viInfo.targetSubKind && SafetyTipKind_UnpavedRoad != pstEvent->viInfo.targetSubKind);
         const int guideType = m_pMgrDirectAccess->getGuideType_Direct();
         const bool playQLY = m_playQLYAtLightGuide && hasQLYContent(*pstEvent);
         switch (guideType) {
             case RGEventGuide_EasyGuideType:    // 司机端轻导航只播事故高发地
                 if ((!m_isForcePlayAccidentVoice || !isDangerous) && !isAiSafeNotify && !isNGSafeNotify && !playQLY) {
                     isCanPlay = false;
                 }
                 break;
             case RGEventGuide_Dolphin_FindWay:  // 探路模式只播电子眼和事故高发地
```

### 9. dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/dd_bend_candidate_collector.cpp:1

```cpp
(code context unavailable: file not found in working tree)
```

```diff
diff --git a/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/dd_bend_candidate_collector.cpp b/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/dd_bend_candidate_collector.cpp
new file mode 100644
index 000000000..0f3859f7e
--- /dev/null
+++ b/dd_src/dd_route_guide/dd_bezier_curve_refactored/bend_segment_builder/dd_bend_candidate_collector.cpp
@@ -0,0 +1,184 @@
+// bend_detection/dd_bend_candidate_collector.cpp
+
+#include "dd_bend_candidate_collector.h"
+#include "dd_curve_tools.h"
+#include "dd_route_data.h"
+#include "logger.h"
+
+#include <algorithm>
+#include <cmath>
+
+namespace dd_curve {
+
+bool BendCandidateCollector::CollectBendCandidates(const DDRouteData& route,
+                                                   const RGGPSPoint_t& gps,
+                                                   std::vector<CurveBendCandidate>& out_bends) {
+    const auto& pts = route.m_vectGeoPoint;
+    out_bends.clear();
+
+    int cur_idx = gps.routeMapPos.coorIdx;
+    int skip_budget = 3;
+    double total_arc_len = 0.0;
+
+    for (int steps = 0; steps < 216 && cur_idx <= static_cast<int>(pts.size()) - 3; ++steps) {
+        CurveBendCandidate bend;
+        if (!BuildBendCandidateAt(route, cur_idx, bend)) break;
+       
+        // 2. 边界拦截：第一个候选点必须在范围内且足够近
+        if (out_bends.empty() && !CheckForwardSearchLimit(route, gps, bend.kinematics_.route_idx_, 100.0)) break; 
+
+        // 3. 评估策略：Accept 之外的处理（跳点或停止）
+        if (AssessBendCandidate(route, out_bends.empty() ? nullptr : &out_bends.back(), bend, total_arc_len) != BendCollectDecision::Accept) {
+            if (--skip_budget < 0) break;
+            cur_idx = FindNextDistantPoint(route, cur_idx);
+            if (cur_idx < 0) break;
+            continue;
+        }
+
+        // 5. 接纳并更新状态
+        out_bends.push_back(bend);
+        if (out_bends.size() >= 10) break;
+
+        cur_idx = std::max(out_bends.back().kinematics_.route_idx_, cur_idx + 1);
+        skip_budget = 3; // 重置跳点预算
+    }
+    
+    FillNextBendDistFromPrev(out_bends);
+    return !out_bends.empty();
+}
+
+bool BendCandidateCollector::BuildBendCandidateAt(const DDRouteData& route,
+                                                 int start_idx,
+                                                 CurveBendCandidate& out_candidate) {
+    const std::vector<RGGeoPoint_t>& geo_points = route.m_vectGeoPoint;
+    if (start_idx < 0 || start_idx >= static_cast<int>(geo_points.size())) return false;
+
+    // 1) 三点：A-B-C
+    const RGGeoPoint_t& point_a = geo_points[start_idx];
+
+    const int middle_idx = FindNextDistantPoint(route, start_idx);
+    if (middle_idx == -1) return false;
+    const RGGeoPoint_t& point_b = geo_points[middle_idx];
+
+    const int forward_idx = FindNextDistantPoint(route, middle_idx);
+    if (forward_idx == -1) return false;
+    const RGGeoPoint_t& point_c = geo_points[forward_idx];
+
+    // 2) 航向与转角
+    const float heading_ab = RG_GetLineAngleDouble(point_a, point_b);
+    const float heading_bc = RG_GetLineAngleDouble(point_b, point_c);
+    const float turn_deg   = AngleDiffSigned(heading_bc, heading_ab);  // CW+
+
+    // 3) 曲率与强度
+    const double kDegToRad = M_PI / 180.0;
+    const double kMinArcLen = 1e-3;
+
+    const double arc_len = dd_curve::ComputeCurvatureArcLen(point_a, point_b, point_c);
+    const double curvature = (arc_len > kMinArcLen)
+        ? (std::fabs(turn_deg) * kDegToRad / arc_len)
+        : 0.0;
+
+    const double strength = curvature * std::fabs(turn_deg * kDegToRad);
+    const double prev_len = RG_DistanceBetweenPoints(point_a, point_b);
+    const double next_len = RG_DistanceBetweenPoints(point_b, point_c);
+
+    // 4) 构造候选（保持你原始构造参数顺序）
+    out_candidate = CurveBendCandidate(
+        /* route_idx           */ middle_idx,
+        /* prev_arc_len        */ prev_len,
+        /* next_arc_len        */ next_len,
+        /* turn_deg            */ static_cast<double>(turn_deg),
+        /* curvature           */ curvature,
+        /* unit_cross_product  */ dd_curve::Cross2DUnit(point_a, point_b, point_c),
+        /* strength            */ strength,
+        /* in_angle            */ heading_ab,
+        /* out_angle           */ heading_bc,
+        /* reserved            */ 0,
+        /* reserved            */ 0
+    );
+
+    return true;
+}
+
+BendCollectDecision BendCandidateCollector::AssessBendCandidate(const DDRouteData& route,
+                                                               CurveBendCandidate* prev,
+                                                               CurveBendCandidate& curr,
+                                                               double& total_arc_len) {
+    auto& g = curr.geometry_;
+    BendCollectDecision result = BendCollectDecision::Accept; // 默认为接纳
+
+    // 1. 基础弱弯与曲率过滤
+    double ratio = (g.prev_arc_len_ > 1e-6) ? (g.next_arc_len_ / g.prev_arc_len_) : 1e9;
+    double abs_turn = std::fabs(g.turn_deg_);
+
+    if (ratio < 5.0 || abs_turn < 75.0) {
```
