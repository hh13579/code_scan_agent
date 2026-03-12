from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from code_scan_agent.nodes.review_diff_with_llm import _select_diff_blocks, review_diff_with_llm
from code_scan_agent.retrieval.specs import RetrievalHints, RetrievalPlan, RetrievalPlanItem


def _base_state(repo_path: Path) -> dict[str, object]:
    return {
        "request": {
            "repo_path": str(repo_path),
            "mode": "diff",
        },
        "repo_profile": {
            "repo_path": str(repo_path),
            "languages": ["cpp", "ts"],
        },
        "diff_files": [
            {
                "path": "src/demo.cpp",
                "language": "cpp",
                "status": "M",
                "changed_lines": [2, 3],
                "patch": "diff --git a/src/demo.cpp b/src/demo.cpp\n@@ -2 +2,2 @@\n-return a + b;\n+const int sum = a + b;\n+return sum;\n",
                "hunks": ["@@ -2 +2,2 @@\n-return a + b;\n+const int sum = a + b;\n+return sum;\n"],
            }
        ],
        "triaged_findings": [],
        "errors": [],
        "logs": [],
    }


class ReviewDiffWithLlmTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        repo_path = Path(self.temp_dir.name)
        (repo_path / "src").mkdir()
        (repo_path / "src" / "demo.cpp").write_text("int add(int a, int b) {\n    return a + b;\n}\n", encoding="utf-8")
        self.repo_path = repo_path

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_no_llm_skips_review(self) -> None:
        state = _base_state(self.repo_path)
        state["request"]["enable_llm_triage"] = False

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        self.assertEqual(result["llm_review_findings"], [])
        self.assertIn("review_diff_with_llm: skipped (--no-llm)", result["logs"])

    @patch("code_scan_agent.nodes.review_diff_with_llm._call_llm_diff_review")
    def test_mock_llm_response_produces_structured_findings(self, mock_call) -> None:
        mock_call.return_value = json.dumps(
            {
                "summary": {"overall_risk": "medium", "notes": ["check pointer lifetime"]},
                "findings": [
                    {
                        "file": "src/demo.cpp",
                        "line": 2,
                        "bug_class": "resource_lifecycle",
                        "severity": "high",
                        "review_action": "block",
                        "category": "memory",
                        "title": "Potential lifetime issue",
                        "message": "Returned reference may outlive local storage.",
                        "impact": "The caller may observe undefined behavior if it uses invalid storage.",
                        "confidence": "high",
                        "key_evidence_roles": ["changed_entrypoint", "cleanup_path"],
                        "evidence_completeness": "strong",
                        "evidence": ["New code introduces a local temporary."],
                        "suggested_action": "Return by value or store data in owned storage.",
                    }
                ],
            },
            ensure_ascii=False,
        )
        state = _base_state(self.repo_path)

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        findings = result["llm_review_findings"]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["tool"], "llm_diff_review")
        self.assertEqual(findings[0]["severity"], "high")
        self.assertEqual(findings[0]["file"], "src/demo.cpp")
        self.assertEqual(findings[0]["rule_id"], "semantic-review")
        self.assertEqual(findings[0]["language"], "cpp")
        self.assertEqual(findings[0]["category"], "resource_lifecycle")
        self.assertEqual(findings[0]["bug_class"], "resource_lifecycle")
        self.assertEqual(findings[0]["review_action"], "block")
        self.assertEqual(findings[0]["impact"], "The caller may observe undefined behavior if it uses invalid storage.")
        self.assertEqual(findings[0]["evidence"], ["New code introduces a local temporary."])
        self.assertEqual(findings[0]["key_evidence_roles"], ["changed_entrypoint", "cleanup_path"])
        self.assertEqual(findings[0]["evidence_completeness"], "strong")

    @patch("code_scan_agent.nodes.review_diff_with_llm._call_llm_diff_review")
    def test_dirty_json_falls_back_to_empty_findings(self, mock_call) -> None:
        mock_call.return_value = "not-json-response"
        state = _base_state(self.repo_path)

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        self.assertEqual(result["llm_review_findings"], [])
        self.assertTrue(any("parse failed" in item.lower() for item in result["errors"]))

    @patch("code_scan_agent.nodes.review_diff_with_llm._call_llm_diff_review")
    def test_resource_categories_are_preserved(self, mock_call) -> None:
        mock_call.return_value = json.dumps(
            {
                "summary": {"overall_risk": "medium"},
                "findings": [
                    {
                        "file": "src/demo.cpp",
                        "line": 2,
                        "severity": "medium",
                        "review_action": "should_fix",
                        "category": "ownership_mismatch",
                        "title": "Ownership chain is broken",
                        "message": "The new bridge does not preserve the cleanup path.",
                        "impact": "Deep fields may leak on every request.",
                        "confidence": "high",
                        "evidence": [
                            "Allocation enters the new wrapper path.",
                            "The cleanup chain is not visible in the new API.",
                        ],
                        "suggested_action": "Route the new path through the existing pool/release mechanism.",
                    }
                ],
            },
            ensure_ascii=False,
        )
        state = _base_state(self.repo_path)

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        self.assertEqual(result["llm_review_findings"][0]["category"], "ownership_mismatch")
        self.assertEqual(result["llm_review_findings"][0]["bug_class"], "ownership_mismatch")

    @patch("code_scan_agent.nodes.review_diff_with_llm._call_llm_diff_review")
    def test_finding_without_evidence_or_impact_is_degraded(self, mock_call) -> None:
        mock_call.return_value = json.dumps(
            {
                "summary": {"overall_risk": "low"},
                "findings": [
                    {
                        "file": "src/demo.cpp",
                        "line": 2,
                        "severity": "medium",
                        "review_action": "follow_up",
                        "category": "logic_regression",
                        "title": "Suspicious change",
                        "message": "This may be risky.",
                        "confidence": "high",
                        "evidence": [],
                        "suggested_action": "Inspect the call sites.",
                    }
                ],
            },
            ensure_ascii=False,
        )
        state = _base_state(self.repo_path)

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        self.assertEqual(len(result["llm_review_findings"]), 1)
        finding = result["llm_review_findings"][0]
        self.assertEqual(finding["confidence"], "medium")
        self.assertEqual(finding["impact"], "该改动可能影响局部行为正确性，建议在相关路径上补充验证。")
        self.assertEqual(finding["evidence"], [])
        self.assertTrue(any("dropped=0" in item for item in result["logs"]))
        self.assertEqual(finding["evidence_completeness"], "partial")

    @patch("code_scan_agent.nodes.review_diff_with_llm._call_llm_diff_review")
    def test_route_code_section_leak_is_synthesized_from_context_chain(self, mock_call) -> None:
        mock_call.return_value = json.dumps({"summary": {"overall_risk": "low"}, "findings": []}, ensure_ascii=False)

        repo_path = self.repo_path
        (repo_path / "nav_wrapper" / "rg_tools").mkdir(parents=True)
        (repo_path / "nav_wrapper" / "rg_tools" / "rg_api_tools.cpp").write_text(
            "void AddRouteCodeSection() {\n"
            "    PtrArr<RGEvent_t> events(rg_info.event());\n"
            "    RG_SetCodeSection(handle, routeId, tag, endPoint, events.cnt, events);\n"
            "}\n",
            encoding="utf-8",
        )
        state = {
            "request": {"repo_path": str(repo_path), "mode": "diff"},
            "repo_profile": {"repo_path": str(repo_path), "languages": ["cpp"]},
            "diff_files": [
                {
                    "path": "nav_wrapper/rg_tools/rg_api_tools.cpp",
                    "language": "cpp",
                    "status": "M",
                    "changed_lines": [1, 2, 3],
                    "patch": (
                        "diff --git a/nav_wrapper/rg_tools/rg_api_tools.cpp b/nav_wrapper/rg_tools/rg_api_tools.cpp\n"
                        "@@ -0,0 +1,4 @@\n"
                        "+void AddRouteCodeSection() {\n"
                        "+    PtrArr<RGEvent_t> events(rg_info.event());\n"
                        "+    RG_SetCodeSection(handle, routeId, tag, endPoint, events.cnt, events);\n"
                        "+}\n"
                    ),
                    "hunks": [
                        "@@ -0,0 +1,4 @@\n"
                        "+void AddRouteCodeSection() {\n"
                        "+    PtrArr<RGEvent_t> events(rg_info.event());\n"
                        "+    RG_SetCodeSection(handle, routeId, tag, endPoint, events.cnt, events);\n"
                        "+}\n"
                    ],
                }
            ],
            "review_context_blocks": [
                {
                    "file": "src/navi_guide.cpp",
                    "subject_file": "nav_wrapper/rg_tools/rg_api_tools.cpp",
                    "kind": "ownership_path",
                    "evidence_role": "ownership_transfer_path",
                    "symbol": "RG_SetCodeSection",
                    "content": "int RG_SetCodeSection(...) {\n    return mgr->setCodeSection(routeId, tag, endPoint, eventsCnt, events);\n}\n",
                },
                {
                    "file": "src/navi_guide.cpp",
                    "subject_file": "nav_wrapper/rg_tools/rg_api_tools.cpp",
                    "kind": "sibling_api",
                    "evidence_role": "sibling_baseline",
                    "symbol": "RG_SetMarkers",
                    "content": "int RG_SetMarkers(...) {\n    if (mgr->saveEventsAllocPointerToPool(routeId, eventCnt, events) != NG_RET_OK) {\n        mgr->releaseEventsAllocPointer(eventCnt, (RGEvent_t*)events);\n    }\n}\n",
                },
                {
                    "file": "nav_wrapper/rg_tools/pb2c.h",
                    "subject_file": "nav_wrapper/rg_tools/rg_api_tools.cpp",
                    "kind": "helper_definition",
                    "evidence_role": "helper_definition",
                    "symbol": "pb2c",
                    "content": "static void pb2c(RGVISentence_t& dst, const VISentence& src) {\n    dst.ttsContent = new ng_wchar[ttsLen+1];\n}\n\nstatic void pb2c(RGBIMission_t &dst, const BIMission &src) {\n    dst.missionDisplayPb = new ng_char[dst.missionDisplayPbSize];\n}\n\ntemplate <typename T> class PtrArr{\npublic:\n    ~PtrArr(){if(m_p){delete[] m_p;}}\n};\n",
                },
                {
                    "file": "dd_src/dd_route_guide/dd_ng_route_guide_mgr.cpp",
                    "subject_file": "nav_wrapper/rg_tools/rg_api_tools.cpp",
                    "kind": "cleanup_path",
                    "evidence_role": "cleanup_path",
                    "content": "int DDRouteGuideMgr::saveEventsAllocPointerToPool(...) {\n    return m_vectRG[i]->saveEventsAllocPointerToPool(eventCnt, events);\n}\n\nvoid DDRouteGuideMgr::releaseEventsAllocPointer(...) {\n    SAFE_DELETE_ARRAY(event.viInfo.sentences[j].ttsContent);\n}\n",
                },
                {
                    "file": "dd_src/dd_route_guide/dd_data_mgr/dd_rg_data_mgr.cpp",
                    "subject_file": "nav_wrapper/rg_tools/rg_api_tools.cpp",
                    "kind": "cleanup_path",
                    "evidence_role": "cleanup_path",
                    "content": "void DDRGDataMgr::clearEventsAllocPointerPool() {\n    SAFE_DELETE_ARRAY(pMissionPb);\n}\n\nvoid DDRGDataMgr::saveEventsAllocPointerToPool(...) {\n    m_setMissionPBPointerPool.insert(event.biInfo.infoMission.missionDisplayPb);\n    m_setTTSPointerPool.insert(event.viInfo.sentences[j].ttsContent);\n}\n",
                },
            ],
            "review_plans": [
                RetrievalPlan(
                    file="nav_wrapper/rg_tools/rg_api_tools.cpp",
                    language="cpp",
                    suspected_bug_classes=("resource_lifecycle", "ownership_mismatch"),
                    class_reasons={
                        "resource_lifecycle": ("signal:helper_alloc_like", "signal:cleanup_terms"),
                        "ownership_mismatch": ("signal:wrapper_or_bridge",),
                    },
                    retrieval_hints={
                        "resource_lifecycle": RetrievalHints(
                            symbol_candidates=("AddRouteCodeSection", "RG_SetCodeSection", "PtrArr", "pb2c"),
                            cleanup_terms=("save", "release", "pool", "clear"),
                        ),
                        "ownership_mismatch": RetrievalHints(
                            symbol_candidates=("AddRouteCodeSection", "RG_SetCodeSection"),
                            api_families=("RG_Set",),
                        ),
                    },
                    items=(
                        RetrievalPlanItem(
                            bug_class="resource_lifecycle",
                            evidence_role="changed_entrypoint",
                            hop=1,
                            why_selected="changed bridge path",
                            hints=RetrievalHints(symbol_candidates=("AddRouteCodeSection",)),
                        ),
                        RetrievalPlanItem(
                            bug_class="resource_lifecycle",
                            evidence_role="helper_definition",
                            hop=2,
                            why_selected="helper may allocate deep fields",
                            hints=RetrievalHints(symbol_candidates=("pb2c",), cleanup_terms=("save", "release")),
                        ),
                        RetrievalPlanItem(
                            bug_class="ownership_mismatch",
                            evidence_role="ownership_transfer_path",
                            hop=3,
                            why_selected="need ownership handoff path",
                            hints=RetrievalHints(symbol_candidates=("RG_SetCodeSection",), cleanup_terms=("save", "release", "pool", "clear")),
                        ),
                        RetrievalPlanItem(
                            bug_class="ownership_mismatch",
                            evidence_role="cleanup_path",
                            hop=3,
                            why_selected="need cleanup path",
                            hints=RetrievalHints(symbol_candidates=("saveEventsAllocPointerToPool",), cleanup_terms=("save", "release", "pool", "clear")),
                        ),
                        RetrievalPlanItem(
                            bug_class="ownership_mismatch",
                            evidence_role="sibling_baseline",
                            hop=3,
                            why_selected="need sibling baseline",
                            hints=RetrievalHints(symbol_candidates=("RG_SetMarkers",), api_families=("RG_Set",)),
                        ),
                    ),
                    hop_strategy=("hop1", "hop2", "hop3"),
                    why_selected=("resource lifecycle suspected", "ownership mismatch suspected"),
                )
            ],
            "triaged_findings": [],
            "logs": [],
            "errors": [],
        }

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        findings = result["llm_review_findings"]
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["category"], "ownership_mismatch")
        self.assertEqual(finding["severity"], "medium")
        self.assertEqual(finding["review_action"], "should_fix")
        joined = "\n".join(finding["evidence"])
        self.assertIn("AddRouteCodeSection", joined)
        self.assertIn("RG_SetMarkers", joined)
        self.assertIn("saveEventsAllocPointerToPool", joined)
        self.assertIn("missionDisplayPb", joined)
        self.assertIn("ttsContent", joined)

    @patch("code_scan_agent.nodes.review_diff_with_llm._call_llm_diff_review")
    def test_move_like_diff_with_guarded_call_is_downgraded(self, mock_call) -> None:
        mock_call.return_value = json.dumps(
            {
                "summary": {"overall_risk": "medium"},
                "findings": [
                    {
                        "file": "src/demo.cpp",
                        "line": 2,
                        "severity": "medium",
                        "review_action": "should_fix",
                        "category": "exception_handling",
                        "title": "移除空检查可能导致段错误",
                        "message": "在 BuildOutput 中移除了空检查，直接访问 front()。",
                        "impact": "空容器会崩溃。",
                        "confidence": "high",
                        "evidence": ["diff 显示删除了 if (!items.empty()) 检查。"],
                        "suggested_action": "恢复检查。",
                    }
                ],
            },
            ensure_ascii=False,
        )
        state = _base_state(self.repo_path)
        state["diff_files"][0]["status"] = "R"
        state["diff_files"][0]["old_path"] = "src/old_demo.cpp"
        state["review_context_blocks"] = [
            {
                "file": "src/demo.cpp",
                "subject_file": "src/demo.cpp",
                "kind": "call_site",
                "content": "if (items.empty()) {\n    return;\n}\nBuildOutput(items);\n",
            }
        ]

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        finding = result["llm_review_findings"][0]
        self.assertEqual(finding["severity"], "low")
        self.assertEqual(finding["review_action"], "follow_up")
        self.assertIn("调用方上下文", finding["message"])

    @patch("code_scan_agent.nodes.review_diff_with_llm._call_llm_diff_review")
    def test_move_like_diff_with_relocation_signal_is_downgraded(self, mock_call) -> None:
        mock_call.return_value = json.dumps(
            {
                "summary": {"overall_risk": "medium"},
                "findings": [
                    {
                        "file": "src/demo.cpp",
                        "line": 20,
                        "severity": "medium",
                        "review_action": "should_fix",
                        "category": "logic_regression",
                        "title": "移除 HelperAlpha 可能改变行为",
                        "message": "删除了 HelperAlpha 和 HelperBeta，可能改变原有处理逻辑。",
                        "impact": "行为可能变化。",
                        "confidence": "medium",
                        "evidence": ["Diff Block 1 显示删除了 HelperAlpha 调用点，且调用点被移除。"],
                        "suggested_action": "确认逻辑是否迁移。",
                    }
                ],
            },
            ensure_ascii=False,
        )
        state = _base_state(self.repo_path)
        state["diff_files"][0]["status"] = "R"
        state["diff_files"][0]["old_path"] = "src/old_demo.cpp"
        state["diff_files"].append(
            {
                "path": "src/migrated.cpp",
                "language": "cpp",
                "status": "M",
                "changed_lines": [3],
                "patch": "diff --git a/src/migrated.cpp b/src/migrated.cpp\n@@ -1 +1 @@\n+HelperBeta();\n",
                "hunks": ["@@ -1 +1 @@\n+HelperBeta();\n"],
            }
        )

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        finding = result["llm_review_findings"][0]
        self.assertEqual(finding["severity"], "low")
        self.assertEqual(finding["review_action"], "follow_up")
        self.assertIn("重构迁移", finding["message"])

    @patch("code_scan_agent.nodes.review_diff_with_llm._call_llm_diff_review")
    def test_speculative_callsite_gap_is_downgraded(self, mock_call) -> None:
        mock_call.return_value = json.dumps(
            {
                "summary": {"overall_risk": "medium"},
                "findings": [
                    {
                        "file": "src/demo.cpp",
                        "line": 2,
                        "severity": "medium",
                        "review_action": "should_fix",
                        "category": "contract_mismatch",
                        "title": "新增参数未在调用处提供默认值",
                        "message": "函数签名改动后，其他调用点可能未同步。",
                        "impact": "遗漏的调用点可能出错。",
                        "confidence": "medium",
                        "evidence": ["diff 显示函数新增了一个参数。"],
                        "suggested_action": "检查所有调用点。",
                    }
                ],
            },
            ensure_ascii=False,
        )
        state = _base_state(self.repo_path)
        state["review_context_blocks"] = [
            {
                "file": "src/demo.cpp",
                "subject_file": "src/demo.cpp",
                "kind": "call_site",
                "content": "call_demo(ready, value);\n",
            }
        ]

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        finding = result["llm_review_findings"][0]
        self.assertEqual(finding["severity"], "low")
        self.assertEqual(finding["review_action"], "follow_up")
        self.assertIn("未同步调用方", finding["message"])

    @patch("code_scan_agent.nodes.review_diff_with_llm._call_llm_diff_review")
    def test_diff_only_speculative_finding_is_downgraded(self, mock_call) -> None:
        mock_call.return_value = json.dumps(
            {
                "summary": {"overall_risk": "medium"},
                "findings": [
                    {
                        "file": "src/demo.cpp",
                        "line": 2,
                        "severity": "high",
                        "review_action": "block",
                        "category": "boundary_condition",
                        "title": "循环条件可能越界",
                        "message": "如果输入很小，这里可能出现越界。",
                        "impact": "可能导致崩溃。",
                        "confidence": "high",
                        "evidence": ["Diff Block 1 显示循环条件使用 <=。"],
                        "suggested_action": "检查边界。",
                    }
                ],
            },
            ensure_ascii=False,
        )
        state = _base_state(self.repo_path)

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        finding = result["llm_review_findings"][0]
        self.assertEqual(finding["severity"], "low")
        self.assertEqual(finding["review_action"], "follow_up")
        self.assertIn("主要来自 diff 片段推断", finding["message"])

    @patch("code_scan_agent.nodes.review_diff_with_llm._repo_contains_identifier")
    @patch("code_scan_agent.nodes.review_diff_with_llm._call_llm_diff_review")
    def test_helper_semantic_gap_is_downgraded_when_repo_has_definition(self, mock_call, mock_repo_contains) -> None:
        mock_call.return_value = json.dumps(
            {
                "summary": {"overall_risk": "medium"},
                "findings": [
                    {
                        "file": "src/demo.cpp",
                        "line": 20,
                        "severity": "medium",
                        "review_action": "should_fix",
                        "category": "contract_mismatch",
                        "title": "ComputeThing 参数可能未适配",
                        "message": "HelperThing(value) 可能不匹配预期类型或语义。",
                        "impact": "如果 helper 语义不对，可能导致计算错误。",
                        "confidence": "medium",
                        "evidence": ["Diff Block 1 显示调用方传递了 HelperThing(value)，但未提供 HelperThing 的实现或语义。"],
                        "suggested_action": "验证 HelperThing 的语义。",
                    }
                ],
            },
            ensure_ascii=False,
        )
        mock_repo_contains.return_value = True
        state = _base_state(self.repo_path)

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        finding = result["llm_review_findings"][0]
        self.assertEqual(finding["severity"], "low")
        self.assertEqual(finding["review_action"], "follow_up")
        self.assertIn("helper/工具函数的语义推断", finding["message"])

    def test_missing_diff_files_skips_review(self) -> None:
        state = _base_state(self.repo_path)
        state["diff_files"] = []

        result = review_diff_with_llm(state)  # type: ignore[arg-type]

        self.assertEqual(result["llm_review_findings"], [])
        self.assertIn("review_diff_with_llm: skipped (no diff_files)", result["logs"])

    def test_select_diff_blocks_keeps_rename_metadata_and_patch_header(self) -> None:
        changed_files, diff_blocks = _select_diff_blocks(
            [
                {
                    "path": "src/new_demo.cpp",
                    "old_path": "src/old_demo.cpp",
                    "language": "cpp",
                    "status": "R",
                    "changed_lines": [20],
                    "patch": (
                        "diff --git a/src/old_demo.cpp b/src/new_demo.cpp\n"
                        "similarity index 90%\n"
                        "rename from src/old_demo.cpp\n"
                        "rename to src/new_demo.cpp\n"
                        "@@ -20 +20 @@\n"
                        "-old_value\n"
                        "+new_value\n"
                        "@@ -40 +40 @@\n"
                        "-old_other\n"
                        "+new_other\n"
                    ),
                    "hunks": [
                        "@@ -20 +20 @@\n-old_value\n+new_value\n",
                        "@@ -40 +40 @@\n-old_other\n+new_other\n",
                    ],
                }
            ],
            max_files=4,
            max_hunks=4,
            max_patch_chars=2000,
        )

        self.assertEqual(changed_files, ["R src/old_demo.cpp -> src/new_demo.cpp"])
        self.assertEqual(len(diff_blocks), 1)
        self.assertEqual(diff_blocks[0]["old_path"], "src/old_demo.cpp")
        self.assertEqual(diff_blocks[0]["status"], "R")
        self.assertIn("rename from src/old_demo.cpp", diff_blocks[0]["patch"])
        self.assertIn("rename to src/new_demo.cpp", diff_blocks[0]["patch"])
        self.assertEqual(diff_blocks[0]["block_id"], "src/new_demo.cpp#patch")
        self.assertIn("@@ -40 +40 @@", diff_blocks[0]["patch"])


if __name__ == "__main__":
    unittest.main()
