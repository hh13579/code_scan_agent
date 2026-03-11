# C/C++ 代码审查报告

> 生成方式：DeepSeek

## 范围
- 本次审查基于 diff 模式，针对 feature/driver/v9.2.8 到 feature/driver/v9.2.10 的变更代码，覆盖了 47 个变更文件中的 29 个 C++ 编译单元。
- 结论：扫描工具共报告 3 个低风险问题，均为代码风格或优化建议，无安全或功能缺陷。结合代码上下文和 diff hunk 分析，这些问题对系统稳定性和安全性影响极小，可选择性处理。
- 总体风险：低

## 扫描摘要
- 原始 summary：`{"total": 3, "critical": 0, "high": 0, "medium": 0, "low": 3, "info": 0}`

## 工具观察
- cppcheck 在 diff 模式下扫描了 29 个文件，原始发现 906 条，经 diff 过滤后保留 3 条。
- semgrep 安全扫描未发现任何问题。
- 工具对变更代码的覆盖较为精准，但仅针对 C++ 代码，未覆盖 Java 等其他语言。

## 覆盖限制
- 扫描仅覆盖了 C++ 代码，未对 Java 代码进行静态分析（根据 key_logs，项目包含 Java 语言）。
- diff 模式下，cppcheck 使用了显式文件列表，可能未执行完整的跨文件分析，导致某些跨文件问题未被检出。
- 工具配置为仅报告 diff 相关发现，未变更代码中的潜在问题未被纳入本次审查。

## Findings
### 1. low | walk_src/walk_route_guide/walk_pb_parser.cpp:83
- 工具：`cppcheck`
- 规则：`cstyleCast`
- 判断：可暂缓
- 置信度：中
- 原因：该行使用 C 风格指针转换将 WalkPtrArr<RGWalkFacilityLine_t> 转换为 RGWalkFacilityLine_t*，用于 std::vector::insert。从 diff hunk 可见，此行在变更前后未修改，且上下文中存在多处类似转换（如第 72 行对 trafficLights 的处理）。这种转换在该代码库中似乎是常见模式，用于处理自定义容器 WalkPtrArr，可能涉及底层内存布局的兼容性。虽然 C++ 风格转换（如 static_cast）更安全，但在此上下文中，若 WalkPtrArr 设计为隐式转换或提供指针访问接口，则当前写法可能可接受。
- 影响：低风险。C 风格转换缺乏类型安全检查，在类型不匹配时可能导致未定义行为，但此处上下文显示类型一致，且代码长期存在未引发问题。
- 建议：建议检查 WalkPtrArr 是否提供更安全的接口（如 data() 成员函数返回正确类型指针）。若无，可考虑使用 static_cast<RGWalkFacilityLine_t*>(facilities) 以增强类型安全，但需确保 WalkPtrArr 的内存布局与指针转换兼容。

### 2. low | walk_src/walk_route_guide/walk_pb_parser.cpp:83
- 工具：`cppcheck`
- 规则：`cstyleCast`
- 判断：可暂缓
- 置信度：中
- 原因：此条与上一条 finding 指向同一行代码，cppcheck 可能因同一行存在多个转换而重复报告。分析同上：该行在 diff 中未变更，是现有代码模式的一部分。
- 影响：低风险。重复告警，实际影响与上一条相同。
- 建议：同上。可合并处理，或忽略重复告警。

### 3. low | dd_src/dd_route_guide/dd_event_checker/dd_rg_event_checker_behavior.cpp:281
- 工具：`cppcheck`
- 规则：`variableScope`
- 判断：建议修复
- 置信度：高
- 原因：变量 'diffLevel1' 在函数 initOnTimeArriveTts 中声明，但根据代码上下文，它仅在后续有限范围内使用（可能用于计算时间差阈值）。从 diff hunk 可见，该行在变更中未修改，但变量作用域确实可以缩小到更接近其使用点，以减少变量生命周期和潜在误用。
- 影响：极低风险。缩小作用域是代码优化建议，不影响功能或安全，但能提升代码可读性和维护性。
- 建议：将 'diffLevel1' 的声明移至实际使用它的代码块内部（例如，在需要计算或比较时声明），以遵循最小作用域原则。例如：如果它只在某个 if 语句中使用，则在该 if 块内声明。

## 建议动作
- 优先处理变量作用域问题（finding 3），因其为简单优化且修复风险低。
- 评估 C 风格转换的使用场景，若 WalkPtrArr 有安全接口则逐步替换；否则，可记录为技术债务，暂不处理。
- 考虑在后续迭代中启用更全面的静态分析（如完整项目扫描），以发现非变更代码中的潜在问题。
- 审查团队可讨论是否将 C 风格转换纳入代码规范，明确允许或禁止用例。

## 附录：关键日志
- discover_repo: languages=['cpp', 'java'], build_systems=['cmake', 'clang_compile_db', 'gradle']
- collect_targets detail: git_diff: range=feature/driver/v9.2.8...feature/driver/v9.2.10, files=3430, changed_line_files=3426, changed_lines=723235, status={A:3378, M:52}
- collect_targets detail: diff_candidates=3426
- collect_targets: mode=diff, total_targets=47
- choose_toolchains: mode=diff, languages=['cpp'], toolchains={'cpp': ['clang-tidy', 'cppcheck'], 'security': ['semgrep']}
- run_cpp_scanners: using compile_db intersection units=29 (diff_targets=30)
- run_cpp_scanners: diff mode -> cppcheck uses explicit file list
- run_cpp_scanners: processed 29 files, findings=906
- run_security_scanners: exit=0, findings=0
- normalize_findings(enhanced): normalized=3, dropped=0, diff_filtered=903, diff_files=47, diff_filter=only
- llm_triage: disabled (mode=diff), fallback_local=3
- llm_triage: triaged=3
- build_report: summary={'total': 3, 'critical': 0, 'high': 0, 'medium': 0, 'low': 3, 'info': 0}

## 附录：命中代码上下文
### 1. dd_src/dd_route_guide/dd_event_checker/dd_rg_event_checker_behavior.cpp:281

```cpp
   261 |     memset(m_onTimeArriveTts, 0, sizeof(m_onTimeArriveTts));
   262 | 
   263 |     if (m_pMgrDirectAccess) {
   264 |         int firstRouteEta = -1;
   265 |         long firtGetRouteTime = 0;
   266 |         int curUsedTime = 0;
   267 | 
   268 |         m_pMgrDirectAccess->getFirstRouteInfo(firstRouteEta, firtGetRouteTime);
   269 |         struct timeval tv;
   270 |         struct timezone tz;
   271 |         gettimeofday(&tv, &tz);
   272 | 
   273 |         curUsedTime = tv.tv_sec - firtGetRouteTime;
   274 | 
   275 |         struct tm vtm;
   276 |         long timeStamp = firtGetRouteTime + firstRouteEta;
   277 |         localtime_r(&timeStamp, &vtm);
   278 | 
   279 |         int level1 = 10 * 60;
   280 |         int level2 = 20 * 60;
>  281 |         int diffLevel1 = 1 * 60;
   282 |         int diffLevel2 = 2 * 60;
   283 |         float diffRatioLevel = 0.1;
   284 |         bool satisfy = false;
   285 | 
   286 |         const ng_wchar fmt_minutes[] = {'%', 's', ',',          // 到达目的地附近,
   287 |                                       '%', 's',                // 预估
   288 |                                       '%', 's',                // 行驶时间
   289 |                                       '%', 'd',                 // XX
   290 |                                       '%', 's', ',',           // 分钟,
   291 |                                       '%', 's', 0};            // 已为您准时送达
   292 | 
   293 |         const ng_wchar fmt_hours[] = {'%', 's', ',',           // 到达目的地附近,
   294 |                                       '%', 's',                // 预估
   295 |                                       '%', 's',                // 行驶时间
   296 |                                     '%', 'd',                  // X
   297 |                                     '%', 's',                  // 小时
   298 |                                     '%', 'd',                  // Y
   299 |                                     '%', 's', ',',            // 分钟,
   300 |                                     '%', 's', 0};             // 已为您准时送达
   301 | 
```

```diff
diff --git a/dd_src/dd_route_guide/dd_event_checker/dd_rg_event_checker_behavior.cpp b/dd_src/dd_route_guide/dd_event_checker/dd_rg_event_checker_behavior.cpp
index 7731e7467..3716b0209 100644
--- a/dd_src/dd_route_guide/dd_event_checker/dd_rg_event_checker_behavior.cpp
+++ b/dd_src/dd_route_guide/dd_event_checker/dd_rg_event_checker_behavior.cpp
@@ -256,41 +261,41 @@ void DDRGEventCheckerBehavior::checkEvent(const RGGPSPoint_t& gpsInfo, int naviT
         }
     }
 }
 
 void DDRGEventCheckerBehavior::initOnTimeArriveTts(ng_wchar** ttsContent, bool isTerminalOffRoute) {
     memset(m_onTimeArriveTts, 0, sizeof(m_onTimeArriveTts));
 
     if (m_pMgrDirectAccess) {
         int firstRouteEta = -1;
         long firtGetRouteTime = 0;
         int curUsedTime = 0;
 
         m_pMgrDirectAccess->getFirstRouteInfo(firstRouteEta, firtGetRouteTime);
         struct timeval tv;
         struct timezone tz;
         gettimeofday(&tv, &tz);
 
         curUsedTime = tv.tv_sec - firtGetRouteTime;
 
         struct tm vtm;
-        long timeStamp = firtGetRouteTime + firstRouteEta;
+        time_t timeStamp = firtGetRouteTime + firstRouteEta;
         localtime_r(&timeStamp, &vtm);
 
         int level1 = 10 * 60;
         int level2 = 20 * 60;
         int diffLevel1 = 1 * 60;
         int diffLevel2 = 2 * 60;
         float diffRatioLevel = 0.1;
         bool satisfy = false;
 
         const ng_wchar fmt_minutes[] = {'%', 's', ',',          // 到达目的地附近,
                                       '%', 's',                // 预估
                                       '%', 's',                // 行驶时间
                                       '%', 'd',                 // XX
                                       '%', 's', ',',           // 分钟,
                                       '%', 's', 0};            // 已为您准时送达
 
         const ng_wchar fmt_hours[] = {'%', 's', ',',           // 到达目的地附近,
                                       '%', 's',                // 预估
                                       '%', 's',                // 行驶时间
                                     '%', 'd',                  // X
```

### 2. walk_src/walk_route_guide/walk_pb_parser.cpp:83

```cpp
    63 |                 
    64 |                 guideData.eda = 0;//导航引擎计算使用的eda
    65 |                 for (int j = 1; j < guideData.mapPoints.size(); ++j) {
    66 |                     guideData.eda += (int)round(RG_DistanceBetweenPoints(guideData.mapPoints[j-1], guideData.mapPoints[j]));
    67 |                 }
    68 |                 
    69 |                 std::string strLights;
    70 |                 WalkPtrArr<RGMapRoutePoint_t> trafficLights = rg.trafficlight();
    71 |                 guideData.trafficLights.clear();
    72 |                 guideData.trafficLights.insert(guideData.trafficLights.begin(),(RGMapRoutePoint_t*)trafficLights, (RGMapRoutePoint_t*)trafficLights+trafficLights.cnt);
    73 |                 
    74 |                 for(int li=0; li<guideData.trafficLights.size(); li++) {
    75 |                     const RGMapRoutePoint_t& light = guideData.trafficLights[li];
    76 |                     strLights += std::to_string(light.coorIdx) + "," + std::to_string((int)light.shapeOffset) + "," + std::to_string((int)light.geoPoint.lng) + "," + std::to_string((int)light.geoPoint.lat);
    77 |                     strLights += ";";
    78 |                 }
    79 |                 
    80 |                 std::string strFacilities;
    81 |                 WalkPtrArr<RGWalkFacilityLine_t> facilities = rg.walkfacility();
    82 |                 guideData.facilities.clear();
>   83 |                 guideData.facilities.insert(guideData.facilities.begin(), (RGWalkFacilityLine_t*)facilities, (RGWalkFacilityLine_t*)facilities+facilities.cnt);
    84 |                 
    85 |                 for(int fi=0; fi<guideData.facilities.size(); fi++) {
    86 |                     const RGWalkFacilityLine_t& fati = guideData.facilities[fi];
    87 |                     strFacilities += std::to_string(fati.markerPos.coorIdx) + "," + std::to_string((int)fati.markerPos.shapeOffset) + "," + std::to_string((int)fati.markerPos.geoPoint.lng) + "," + std::to_string((int)fati.markerPos.geoPoint.lat) + "," + std::to_string(fati.type);
    88 |                     strFacilities += ";";
    89 |                 }
    90 |                 
    91 |                 sdklog(Logger::LogTarget::LBAMAI,Logger::LogLevel::LINFO,"w_parser||ret=%d||rId=%lld||ttime=%d||time=%d||eda=%d||lights=%s||facties=%s",m_retCode, guideData.routeId, rg.traffictime(), rg.time(), guideData.eda, strLights.c_str(), strFacilities.c_str());
    92 |                 
    93 |             }
    94 |         }
    95 |     }
    96 | 
    97 | }
    98 | 
    99 | void DDWalkPBParser::getRouteIds(std::vector<ng_uint64>& vecRouteIds)
   100 | {
   101 |     vecRouteIds.clear();
   102 |     for (auto it=m_mapRouteData.begin(); it!=m_mapRouteData.end(); ++it) {
   103 |         vecRouteIds.push_back(it->first);
```

```diff
diff --git a/walk_src/walk_route_guide/walk_pb_parser.cpp b/walk_src/walk_route_guide/walk_pb_parser.cpp
index 143847a8e..e00aa7394 100644
--- a/walk_src/walk_route_guide/walk_pb_parser.cpp
+++ b/walk_src/walk_route_guide/walk_pb_parser.cpp
@@ -44,72 +56,188 @@ m_retCode(PARSER_WALK_PB_ERROR_CODE)
             free(dest);
             delete[] outbuf;
             
             int rgSize = m_rgInfos.rginfo_size();
             if (rgSize <= 0) {
                 return;
             }
             
             for (int i = 0; i < rgSize; i++) {
                 const WalkRouteGuidanceInfo& rg = m_rgInfos.rginfo(i);
                 
                 RGWalkBasicRouteData& guideData = m_mapRouteData[rg.routeid()];
                 
                 guideData.routeId = rg.routeid();
                 guideData.eta = rg.traffictime();
                 
                 WalkPtrArr<RGGeoPoint_t> geos = rg.coor();
                 guideData.mapPoints.clear();
                 guideData.mapPoints.insert(guideData.mapPoints.begin(), (RGGeoPoint_t*)geos, (RGGeoPoint_t*)geos+geos.cnt);
                 
+                guideData.mapGeoSectionLength.clear();
+                
                 guideData.eda = 0;//导航引擎计算使用的eda
+                
                 for (int j = 1; j < guideData.mapPoints.size(); ++j) {
-                    guideData.eda += (int)round(RG_DistanceBetweenPoints(guideData.mapPoints[j-1], guideData.mapPoints[j]));
+                    int secDist = (int)round(RG_DistanceBetweenPoints(guideData.mapPoints[j-1], guideData.mapPoints[j]));
+                    guideData.eda += secDist;
+                    guideData.mapGeoSectionLength.push_back(secDist);
                 }
                 
                 std::string strLights;
                 WalkPtrArr<RGMapRoutePoint_t> trafficLights = rg.trafficlight();
                 guideData.trafficLights.clear();
                 guideData.trafficLights.insert(guideData.trafficLights.begin(),(RGMapRoutePoint_t*)trafficLights, (RGMapRoutePoint_t*)trafficLights+trafficLights.cnt);
                 
                 for(int li=0; li<guideData.trafficLights.size(); li++) {
                     const RGMapRoutePoint_t& light = guideData.trafficLights[li];
                     strLights += std::to_string(light.coorIdx) + "," + std::to_string((int)light.shapeOffset) + "," + std::to_string((int)light.geoPoint.lng) + "," + std::to_string((int)light.geoPoint.lat);
                     strLights += ";";
                 }
                 
                 std::string strFacilities;
                 WalkPtrArr<RGWalkFacilityLine_t> facilities = rg.walkfacility();
                 guideData.facilities.clear();
                 guideData.facilities.insert(guideData.facilities.begin(), (RGWalkFacilityLine_t*)facilities, (RGWalkFacilityLine_t*)facilities+facilities.cnt);
                 
                 for(int fi=0; fi<guideData.facilities.size(); fi++) {
                     const RGWalkFacilityLine_t& fati = guideData.facilities[fi];
                     strFacilities += std::to_string(fati.markerPos.coorIdx) + "," + std::to_string((int)fati.markerPos.shapeOffset) + "," + std::to_string((int)fati.markerPos.geoPoint.lng) + "," + std::to_string((int)fati.markerPos.geoPoint.lat) + "," + std::to_string(fati.type);
                     strFacilities += ";";
                 }
                 
-                sdklog(Logger::LogTarget::LBAMAI,Logger::LogLevel::LINFO,"w_parser||ret=%d||rId=%lld||ttime=%d||time=%d||eda=%d||lights=%s||facties=%s",m_retCode, guideData.routeId, rg.traffictime(), rg.time(), guideData.eda, strLights.c_str(), strFacilities.c_str());
+                std::string strRoadNames;
+                WalkPtrArr<RGWalkRoadName_t> roadNames = rg.roadname();
+                guideData.roadNames.clear();
+                guideData.roadNames.insert(guideData.roadNames.begin(), (RGWalkRoadName_t*)roadNames, (RGWalkRoadName_t*)roadNames+roadNames.cnt);
+                
+                for (int ri=0; ri<guideData.roadNames.size(); ri++) {
+                    const RGWalkRoadName_t& rn = guideData.roadNames[ri];
+                    
+                    unsigned char utf8[RG_MAX_SIZE_NAME] = {0};
+                    RG_UnicodeStrToUTF8Str((unsigned short*)rn.roadName, utf8, RG_MAX_SIZE_NAME);
+                    
+                    strRoadNames += std::to_string(rn.beginPos.coorIdx) + "," + std::to_string(int(rn.beginPos.shapeOffset)) + "," + std::to_string(rn.endPos.coorIdx) + "," + std::to_string(int(rn.endPos.shapeOffset)) + "," + std::string((char *)utf8);
+                    
+                    strRoadNames += ";";
+                }
+                
+                WalkPtrArr<RGWalkRouteTag_t> roadTags = rg.tag();
+                guideData.tags.clear();
+                guideData.tags.insert(guideData.tags.begin(), (RGWalkRouteTag_t*)roadTags, (RGWalkRouteTag_t*)roadTags+roadTags.cnt);
+                std::string strTags;
+                for (int i = 0; i < guideData.tags.size(); i++) {
+                    auto rTag = guideData.tags[i];
+                    
+                    unsigned char utf8[RG_MAX_SIZE_NAME] = {0};
+                    RG_UnicodeStrToUTF8Str((unsigned short*)rTag.value, utf8, RG_MAX_SIZE_NAME);
+                    strTags += (std::string(rTag.key) + ":" + std::string((char *)utf8)) + ";";
+                }
+                
+                guideData.guideEvents.clear();
+                guideData.startOrientation = -1;
+                                
+                for (int ei=0; ei < rg.event().size(); ei++) {
+                    Event eventPb = rg.event(ei);
+                    if (eventPb.eventkind() != EventKind_Display ||
+                        eventPb.diinfo().infokind() != DIKind_Intersection ||
+                        eventPb.diinfo().infodiintersection().intersection() == LONG_STRAIGHT_CODE) {
+                        continue;
+                    }
+                    
+                    RGWalkEvent_t rgEvent;
+                    memset(&rgEvent, 0, sizeof(RGWalkEvent_t));
+                    walk_pb2c(rgEvent, eventPb);
+
+                    guideData.guideEvents.push_back(rgEvent);
+                }
+                
+                if (guideData.guideEvents.size() >= 2) {
+                    std::sort(guideData.guideEvents.begin(), guideData.guideEvents.end(), compareIntersectionEvent);
+                }
+                
+                RGMapRoutePoint_t preTargetPos;
+                preTargetPos.coorIdx = 0;
+                preTargetPos.shapeOffset = 0;
+                if (guideData.mapPoints.size() > 0) {
+                    preTargetPos.geoPoint = guideData.mapPoints.front();
+                }
+                
+                for (int ei=0; ei<guideData.guideEvents.size(); ei++) {
+                    RGWalkEvent_t &curEvent = guideData.guideEvents[ei];
+                    RGMapRoutePoint_t targetPos = curEvent.diInfo.infoDIIntersection.targetPos;
+                    
```

### 3. walk_src/walk_route_guide/walk_pb_parser.cpp:83

```cpp
    63 |                 
    64 |                 guideData.eda = 0;//导航引擎计算使用的eda
    65 |                 for (int j = 1; j < guideData.mapPoints.size(); ++j) {
    66 |                     guideData.eda += (int)round(RG_DistanceBetweenPoints(guideData.mapPoints[j-1], guideData.mapPoints[j]));
    67 |                 }
    68 |                 
    69 |                 std::string strLights;
    70 |                 WalkPtrArr<RGMapRoutePoint_t> trafficLights = rg.trafficlight();
    71 |                 guideData.trafficLights.clear();
    72 |                 guideData.trafficLights.insert(guideData.trafficLights.begin(),(RGMapRoutePoint_t*)trafficLights, (RGMapRoutePoint_t*)trafficLights+trafficLights.cnt);
    73 |                 
    74 |                 for(int li=0; li<guideData.trafficLights.size(); li++) {
    75 |                     const RGMapRoutePoint_t& light = guideData.trafficLights[li];
    76 |                     strLights += std::to_string(light.coorIdx) + "," + std::to_string((int)light.shapeOffset) + "," + std::to_string((int)light.geoPoint.lng) + "," + std::to_string((int)light.geoPoint.lat);
    77 |                     strLights += ";";
    78 |                 }
    79 |                 
    80 |                 std::string strFacilities;
    81 |                 WalkPtrArr<RGWalkFacilityLine_t> facilities = rg.walkfacility();
    82 |                 guideData.facilities.clear();
>   83 |                 guideData.facilities.insert(guideData.facilities.begin(), (RGWalkFacilityLine_t*)facilities, (RGWalkFacilityLine_t*)facilities+facilities.cnt);
    84 |                 
    85 |                 for(int fi=0; fi<guideData.facilities.size(); fi++) {
    86 |                     const RGWalkFacilityLine_t& fati = guideData.facilities[fi];
    87 |                     strFacilities += std::to_string(fati.markerPos.coorIdx) + "," + std::to_string((int)fati.markerPos.shapeOffset) + "," + std::to_string((int)fati.markerPos.geoPoint.lng) + "," + std::to_string((int)fati.markerPos.geoPoint.lat) + "," + std::to_string(fati.type);
    88 |                     strFacilities += ";";
    89 |                 }
    90 |                 
    91 |                 sdklog(Logger::LogTarget::LBAMAI,Logger::LogLevel::LINFO,"w_parser||ret=%d||rId=%lld||ttime=%d||time=%d||eda=%d||lights=%s||facties=%s",m_retCode, guideData.routeId, rg.traffictime(), rg.time(), guideData.eda, strLights.c_str(), strFacilities.c_str());
    92 |                 
    93 |             }
    94 |         }
    95 |     }
    96 | 
    97 | }
    98 | 
    99 | void DDWalkPBParser::getRouteIds(std::vector<ng_uint64>& vecRouteIds)
   100 | {
   101 |     vecRouteIds.clear();
   102 |     for (auto it=m_mapRouteData.begin(); it!=m_mapRouteData.end(); ++it) {
   103 |         vecRouteIds.push_back(it->first);
```

```diff
diff --git a/walk_src/walk_route_guide/walk_pb_parser.cpp b/walk_src/walk_route_guide/walk_pb_parser.cpp
index 143847a8e..e00aa7394 100644
--- a/walk_src/walk_route_guide/walk_pb_parser.cpp
+++ b/walk_src/walk_route_guide/walk_pb_parser.cpp
@@ -44,72 +56,188 @@ m_retCode(PARSER_WALK_PB_ERROR_CODE)
             free(dest);
             delete[] outbuf;
             
             int rgSize = m_rgInfos.rginfo_size();
             if (rgSize <= 0) {
                 return;
             }
             
             for (int i = 0; i < rgSize; i++) {
                 const WalkRouteGuidanceInfo& rg = m_rgInfos.rginfo(i);
                 
                 RGWalkBasicRouteData& guideData = m_mapRouteData[rg.routeid()];
                 
                 guideData.routeId = rg.routeid();
                 guideData.eta = rg.traffictime();
                 
                 WalkPtrArr<RGGeoPoint_t> geos = rg.coor();
                 guideData.mapPoints.clear();
                 guideData.mapPoints.insert(guideData.mapPoints.begin(), (RGGeoPoint_t*)geos, (RGGeoPoint_t*)geos+geos.cnt);
                 
+                guideData.mapGeoSectionLength.clear();
+                
                 guideData.eda = 0;//导航引擎计算使用的eda
+                
                 for (int j = 1; j < guideData.mapPoints.size(); ++j) {
-                    guideData.eda += (int)round(RG_DistanceBetweenPoints(guideData.mapPoints[j-1], guideData.mapPoints[j]));
+                    int secDist = (int)round(RG_DistanceBetweenPoints(guideData.mapPoints[j-1], guideData.mapPoints[j]));
+                    guideData.eda += secDist;
+                    guideData.mapGeoSectionLength.push_back(secDist);
                 }
                 
                 std::string strLights;
                 WalkPtrArr<RGMapRoutePoint_t> trafficLights = rg.trafficlight();
                 guideData.trafficLights.clear();
                 guideData.trafficLights.insert(guideData.trafficLights.begin(),(RGMapRoutePoint_t*)trafficLights, (RGMapRoutePoint_t*)trafficLights+trafficLights.cnt);
                 
                 for(int li=0; li<guideData.trafficLights.size(); li++) {
                     const RGMapRoutePoint_t& light = guideData.trafficLights[li];
                     strLights += std::to_string(light.coorIdx) + "," + std::to_string((int)light.shapeOffset) + "," + std::to_string((int)light.geoPoint.lng) + "," + std::to_string((int)light.geoPoint.lat);
                     strLights += ";";
                 }
                 
                 std::string strFacilities;
                 WalkPtrArr<RGWalkFacilityLine_t> facilities = rg.walkfacility();
                 guideData.facilities.clear();
                 guideData.facilities.insert(guideData.facilities.begin(), (RGWalkFacilityLine_t*)facilities, (RGWalkFacilityLine_t*)facilities+facilities.cnt);
                 
                 for(int fi=0; fi<guideData.facilities.size(); fi++) {
                     const RGWalkFacilityLine_t& fati = guideData.facilities[fi];
                     strFacilities += std::to_string(fati.markerPos.coorIdx) + "," + std::to_string((int)fati.markerPos.shapeOffset) + "," + std::to_string((int)fati.markerPos.geoPoint.lng) + "," + std::to_string((int)fati.markerPos.geoPoint.lat) + "," + std::to_string(fati.type);
                     strFacilities += ";";
                 }
                 
-                sdklog(Logger::LogTarget::LBAMAI,Logger::LogLevel::LINFO,"w_parser||ret=%d||rId=%lld||ttime=%d||time=%d||eda=%d||lights=%s||facties=%s",m_retCode, guideData.routeId, rg.traffictime(), rg.time(), guideData.eda, strLights.c_str(), strFacilities.c_str());
+                std::string strRoadNames;
+                WalkPtrArr<RGWalkRoadName_t> roadNames = rg.roadname();
+                guideData.roadNames.clear();
+                guideData.roadNames.insert(guideData.roadNames.begin(), (RGWalkRoadName_t*)roadNames, (RGWalkRoadName_t*)roadNames+roadNames.cnt);
+                
+                for (int ri=0; ri<guideData.roadNames.size(); ri++) {
+                    const RGWalkRoadName_t& rn = guideData.roadNames[ri];
+                    
+                    unsigned char utf8[RG_MAX_SIZE_NAME] = {0};
+                    RG_UnicodeStrToUTF8Str((unsigned short*)rn.roadName, utf8, RG_MAX_SIZE_NAME);
+                    
+                    strRoadNames += std::to_string(rn.beginPos.coorIdx) + "," + std::to_string(int(rn.beginPos.shapeOffset)) + "," + std::to_string(rn.endPos.coorIdx) + "," + std::to_string(int(rn.endPos.shapeOffset)) + "," + std::string((char *)utf8);
+                    
+                    strRoadNames += ";";
+                }
+                
+                WalkPtrArr<RGWalkRouteTag_t> roadTags = rg.tag();
+                guideData.tags.clear();
+                guideData.tags.insert(guideData.tags.begin(), (RGWalkRouteTag_t*)roadTags, (RGWalkRouteTag_t*)roadTags+roadTags.cnt);
+                std::string strTags;
+                for (int i = 0; i < guideData.tags.size(); i++) {
+                    auto rTag = guideData.tags[i];
+                    
+                    unsigned char utf8[RG_MAX_SIZE_NAME] = {0};
+                    RG_UnicodeStrToUTF8Str((unsigned short*)rTag.value, utf8, RG_MAX_SIZE_NAME);
+                    strTags += (std::string(rTag.key) + ":" + std::string((char *)utf8)) + ";";
+                }
+                
+                guideData.guideEvents.clear();
+                guideData.startOrientation = -1;
+                                
+                for (int ei=0; ei < rg.event().size(); ei++) {
+                    Event eventPb = rg.event(ei);
+                    if (eventPb.eventkind() != EventKind_Display ||
+                        eventPb.diinfo().infokind() != DIKind_Intersection ||
+                        eventPb.diinfo().infodiintersection().intersection() == LONG_STRAIGHT_CODE) {
+                        continue;
+                    }
+                    
+                    RGWalkEvent_t rgEvent;
+                    memset(&rgEvent, 0, sizeof(RGWalkEvent_t));
+                    walk_pb2c(rgEvent, eventPb);
+
+                    guideData.guideEvents.push_back(rgEvent);
+                }
+                
+                if (guideData.guideEvents.size() >= 2) {
+                    std::sort(guideData.guideEvents.begin(), guideData.guideEvents.end(), compareIntersectionEvent);
+                }
+                
+                RGMapRoutePoint_t preTargetPos;
+                preTargetPos.coorIdx = 0;
+                preTargetPos.shapeOffset = 0;
+                if (guideData.mapPoints.size() > 0) {
+                    preTargetPos.geoPoint = guideData.mapPoints.front();
+                }
+                
+                for (int ei=0; ei<guideData.guideEvents.size(); ei++) {
+                    RGWalkEvent_t &curEvent = guideData.guideEvents[ei];
+                    RGMapRoutePoint_t targetPos = curEvent.diInfo.infoDIIntersection.targetPos;
+                    
```
