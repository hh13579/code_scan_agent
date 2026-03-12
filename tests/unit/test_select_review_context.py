from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from code_scan_agent.nodes.select_review_context import select_review_context


class SelectReviewContextTest(unittest.TestCase):
    def test_select_review_context_populates_context_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)
            (repo_path / "src").mkdir()
            (repo_path / "tests").mkdir()
            (repo_path / "src" / "order_service.ts").write_text(
                "export interface Order {\n"
                "  id: string;\n"
                "  amount: number;\n"
                "}\n\n"
                "export function settleOrder(order: Order) {\n"
                "  if (order.amount > 0) {\n"
                "    return order.amount;\n"
                "  }\n"
                "  return 0;\n"
                "}\n",
                encoding="utf-8",
            )
            (repo_path / "tests" / "order_service.test.ts").write_text(
                "import { settleOrder } from '../src/order_service';\n"
                "it('settles order', () => {\n"
                "  expect(settleOrder({ id: '1', amount: 1 })).toBe(1);\n"
                "});\n",
                encoding="utf-8",
            )
            state = {
                "request": {
                    "repo_path": str(repo_path),
                    "mode": "diff",
                },
                "repo_profile": {
                    "repo_path": str(repo_path),
                    "languages": ["ts"],
                },
                "diff_files": [
                    {
                        "path": "src/order_service.ts",
                        "language": "ts",
                        "status": "M",
                        "changed_lines": [2, 7],
                        "patch": (
                            "@@ -1,8 +1,10 @@\n"
                            "-export interface Order {\n"
                            "+export interface Order {\n"
                            "+  amount: number;\n"
                            "   id: string;\n"
                            "-export function settleOrder(order: Order) {\n"
                            "+export function settleOrder(order: Order) {\n"
                            "+  if (order.amount > 0) {\n"
                            "     return order.amount;\n"
                            "+  }\n"
                            "   return 0;\n"
                            " }\n"
                        ),
                        "hunks": [],
                    }
                ],
                "triaged_findings": [
                    {"file": "src/order_service.ts", "severity": "high", "message": "demo"},
                ],
                "logs": [],
                "errors": [],
            }

            result = select_review_context(state)  # type: ignore[arg-type]

            blocks = result["review_context_blocks"]
            self.assertTrue(result["review_plans"])
            self.assertTrue(blocks)
            self.assertTrue(any(block.kind == "function_context" for block in blocks))
            self.assertTrue(any(block.kind == "type_definition" for block in blocks))
            self.assertTrue(all(block.bug_class in {"generic_review", "contract_drift", "semantic_misuse"} or block.bug_class for block in blocks))
            self.assertTrue(all(block.evidence_role for block in blocks))
            self.assertTrue(all(block.hop >= 1 for block in blocks))

    def test_select_review_context_expands_resource_lifecycle_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_path = Path(temp_dir)
            (repo_path / "nav_wrapper" / "rg_tools").mkdir(parents=True)
            (repo_path / "src").mkdir()
            (repo_path / "dd_src" / "dd_route_guide" / "dd_data_mgr").mkdir(parents=True)
            (repo_path / "dd_src" / "dd_route_guide").mkdir(parents=True, exist_ok=True)

            (repo_path / "nav_wrapper" / "rg_tools" / "rg_api_tools.cpp").write_text(
                "void AddRouteCodeSection() {\n"
                "  PtrArr<RGEvent_t> events(rg_info.event());\n"
                "  RG_SetCodeSection(handle, routeId, tag, endPoint, events.cnt, events);\n"
                "}\n",
                encoding="utf-8",
            )
            (repo_path / "src" / "navi_guide.cpp").write_text(
                "int RG_SetCodeSection(ng_handle handle, ng_uint64 routeId, const RGRouteTag_t& tag, const RGMapRoutePoint_t& endPoint, int eventsCnt, const RGEvent_t* events)\n"
                "{\n"
                "    return mgr->setCodeSection(routeId, tag, endPoint, eventsCnt, events);\n"
                "}\n\n"
                "int RG_SetMarkers(ng_handle handle, ng_uint64 routeId, int eventCnt, const RGEvent_t* events)\n"
                "{\n"
                "    if (mgr->saveEventsAllocPointerToPool(routeId, eventCnt, events) != NG_RET_OK) {\n"
                "        mgr->releaseEventsAllocPointer(eventCnt, (RGEvent_t*)events);\n"
                "    }\n"
                "    return mgr->setMarkers(routeId, 0, nullptr);\n"
                "}\n",
                encoding="utf-8",
            )
            (repo_path / "nav_wrapper" / "rg_tools" / "pb2c.h").write_text(
                "static void pb2c(RGVISentence_t& dst, const VISentence& src) {\n"
                "    dst.ttsContent = new ng_wchar[8];\n"
                "}\n"
                "static void pb2c(RGBIMission_t &dst, const BIMission &src) {\n"
                "    dst.missionDisplayPb = new ng_char[16];\n"
                "}\n"
                "static void pb2c(RGEvent_t& dst, const Event& src) {\n"
                "    pb2c(dst.biInfo, src.biinfo());\n"
                "}\n"
                "template <typename T> class PtrArr{\n"
                "public:\n"
                "    ~PtrArr(){if(m_p){delete[] m_p;}}\n"
                "    T* m_p;\n"
                "};\n",
                encoding="utf-8",
            )
            (repo_path / "dd_src" / "dd_route_guide" / "dd_ng_route_guide_mgr.cpp").write_text(
                "int DDRouteGuideMgr::setCodeSection(ng_uint64 routeId, const RGRouteTag_t& tag, const RGMapRoutePoint_t& endPoint, int eventsCnt, const RGEvent_t* events)\n"
                "{\n"
                "    return RG->setRouteCodeSection(tag, endPoint, curPoint, eventsCnt, events);\n"
                "}\n\n"
                "int DDRouteGuideMgr::saveEventsAllocPointerToPool(ng_uint64 routeId, int eventCnt, const RGEvent_t* events)\n"
                "{\n"
                "    return m_vectRG[i]->saveEventsAllocPointerToPool(eventCnt, events);\n"
                "}\n\n"
                "void DDRouteGuideMgr::releaseEventsAllocPointer(int eventCnt, RGEvent_t* events)\n"
                "{\n"
                "    SAFE_DELETE_ARRAY(event.viInfo.sentences[j].ttsContent);\n"
                "}\n",
                encoding="utf-8",
            )
            (repo_path / "dd_src" / "dd_route_guide" / "dd_data_mgr" / "dd_rg_data_mgr.cpp").write_text(
                "void DDRGDataMgr::clearEventsAllocPointerPool()\n"
                "{\n"
                "    SAFE_DELETE_ARRAY(pMissionPb);\n"
                "}\n\n"
                "void DDRGDataMgr::saveEventsAllocPointerToPool(int eventCnt,const RGEvent_t* events)\n"
                "{\n"
                "    m_setMissionPBPointerPool.insert(event.biInfo.infoMission.missionDisplayPb);\n"
                "    m_setTTSPointerPool.insert(event.viInfo.sentences[j].ttsContent);\n"
                "}\n",
                encoding="utf-8",
            )

            state = {
                "request": {
                    "repo_path": str(repo_path),
                    "mode": "diff",
                },
                "repo_profile": {
                    "repo_path": str(repo_path),
                    "languages": ["cpp"],
                },
                "diff_files": [
                    {
                        "path": "nav_wrapper/rg_tools/rg_api_tools.cpp",
                        "language": "cpp",
                        "status": "M",
                        "changed_lines": [1, 2, 3],
                        "patch": (
                            "@@ -0,0 +1,4 @@\n"
                            "+void AddRouteCodeSection() {\n"
                            "+  PtrArr<RGEvent_t> events(rg_info.event());\n"
                            "+  pb2c(dst, src);\n"
                            "+  RG_SetCodeSection(handle, routeId, tag, endPoint, events.cnt, events);\n"
                            "+}\n"
                        ),
                        "hunks": [],
                    }
                ],
                "triaged_findings": [],
                "logs": [],
                "errors": [],
            }

            result = select_review_context(state)  # type: ignore[arg-type]

            blocks = result["review_context_blocks"]
            self.assertTrue(result["review_plans"])
            files = {block.file for block in blocks}
            kinds = {block.kind for block in blocks}
            self.assertIn("nav_wrapper/rg_tools/rg_api_tools.cpp", files)
            self.assertIn("src/navi_guide.cpp", files)
            self.assertIn("nav_wrapper/rg_tools/pb2c.h", files)
            self.assertIn("dd_src/dd_route_guide/dd_ng_route_guide_mgr.cpp", files)
            self.assertIn("dd_src/dd_route_guide/dd_data_mgr/dd_rg_data_mgr.cpp", files)
            self.assertIn("sibling_api", kinds)
            self.assertIn("cleanup_path", kinds)
            self.assertIn("helper_definition", kinds)
            self.assertIn("ownership_path", kinds)
            self.assertTrue(any(block.bug_class in {"resource_lifecycle", "ownership_mismatch"} for block in blocks))
            self.assertTrue(any(block.evidence_role == "cleanup_path" for block in blocks))
            self.assertTrue(any(block.evidence_role == "helper_definition" for block in blocks))
            self.assertTrue(any(block.evidence_role == "ownership_transfer_path" for block in blocks))
            self.assertTrue(any(block.evidence_role == "sibling_baseline" for block in blocks))
            self.assertTrue(any(block.why_selected for block in blocks))


if __name__ == "__main__":
    unittest.main()
