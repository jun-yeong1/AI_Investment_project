"""실제 웹·RAG 서비스 없이 조사 노드의 계약과 협업을 검증한다."""

import unittest

from langgraph.graph import END, START, StateGraph

from agents.common import FetchedPage, PageAnalysis, ResearchTools
from agents.company import company_node
from agents.market import market_node
from agents.regulation import regulation_node
from agents.select_candidate import select_candidate
from agents.tech_pipeline import tech_pipeline_node
from config import CANDIDATES
from state import State


def fake_tools(url: str, text: str, analysis: dict, *, rag_results: bool = True):
    calls = {"queries": [], "rag": [], "fetched": []}

    def web_search(query):
        calls["queries"].append(query)
        return [{"url": url, "snippet": "검색 요약은 근거로 쓰지 않는다"}]

    def fetch_page(requested_url):
        calls["fetched"].append(requested_url)
        return FetchedPage(requested_url, text, "2026-09-01", "2026-09-30")

    def rag_search(query, doc_type, pipeline=None):
        calls["rag"].append((query, doc_type, pipeline))
        return [{"chunk_id": "criteria-1", "doc": "판단 기준", "page": 3, "text": "기업별 사실이 아닌 판단 기준"}] if rag_results else []

    def extract(area, company_name, allowed_items, page, rag_context):
        return PageAnalysis.model_validate(analysis)

    return ResearchTools(web_search, fetch_page, extract, rag_search), calls


def merge(state, update):
    """테스트에서 State의 evidence 리듀서 동작을 흉내 낸다."""
    for key, value in update.items():
        if key == "evidence":
            state.setdefault(key, []).extend(value)
        else:
            state[key] = value


class AgentContractTests(unittest.TestCase):
    def test_candidate_order_and_reset(self):
        state = {"candidates": CANDIDATES, "current_idx": -1, "evidence": []}
        selected = []
        for candidate in CANDIDATES:
            merge(state, select_candidate(state))
            selected.append(state["company"]["company_id"])
            state["pipeline"] = [{"substance": "OLD", "indication": "OLD", "stage": "OLD"}]
            state["scores"] = {"old": 2}
        self.assertEqual(selected, [candidate["company_id"] for candidate in CANDIDATES])
        with self.assertRaises(IndexError):
            select_candidate(state)
        self.assertEqual(state["company"]["company_id"], "drnoah")

    def test_four_nodes_pass_pipeline_and_judge_gets_only_current_evidence(self):
        state = {"candidates": CANDIDATES, "current_idx": -1, "evidence": []}
        merge(state, select_candidate(state))

        company_tools, company_calls = fake_tools(
            "https://example.org/company",
            "창업자는 제약사에서 신약 개발을 했다.",
            {"findings": [{"item": "management", "fact": "창업 전 제약사 경력", "quote": "제약사에서 신약 개발을 했다", "status": "확인됨"}]},
        )
        tech_tools, tech_calls = fake_tools(
            "https://example.org/tech",
            "스탠다임 후보물질 ST-01은 폐암 적응증에서 전임상 단계다.",
            {
                "findings": [{"item": "stage", "fact": "전임상 단계", "quote": "폐암 적응증에서 전임상 단계", "status": "기업 주장만"}],
                "pipeline": [{"substance": "ST-01", "indication": "폐암", "stage": "전임상", "quote": "스탠다임 후보물질 ST-01은 폐암 적응증에서 전임상 단계"}],
            },
        )
        regulation_tools, regulation_calls = fake_tools(
            "https://example.org/regulation",
            "ST-01 폐암 임상시험계획이 승인되었다.",
            {"findings": [{"item": "regulation", "fact": "임상시험계획 승인", "quote": "임상시험계획이 승인되었다", "status": "확인됨"}]},
        )
        market_tools, market_calls = fake_tools(
            "https://example.org/market",
            "ST-01 폐암 치료제 공동연구 계약을 맺었다.",
            {"findings": [{"item": "sales", "fact": "공동연구 계약", "quote": "공동연구 계약을 맺었다", "status": "기업 주장만"}]},
        )

        merge(state, company_node(state, tools=company_tools))
        merge(state, tech_pipeline_node(state, tools=tech_tools))
        merge(state, regulation_node(state, tools=regulation_tools))
        merge(state, market_node(state, tools=market_tools))

        self.assertEqual(state["pipeline"], [{"substance": "ST-01", "indication": "폐암", "stage": "전임상"}])
        self.assertTrue(any("ST-01 폐암" in query for query in regulation_calls["queries"]))
        self.assertTrue(any("ST-01 폐암" in query for query in market_calls["queries"]))
        self.assertEqual([item["item"] for item in state["evidence"]], ["management", "stage", "regulation", "sales"])
        self.assertEqual({item["company_id"] for item in state["evidence"]}, {"standigm"})
        self.assertEqual(len({item["id"] for item in state["evidence"]}), 4)
        self.assertEqual(len(company_calls["fetched"]), 1)
        self.assertEqual(tech_calls["rag"][0][1], "tech")
        self.assertEqual(len(tech_calls["rag"]), 1)  # 국문·영문 검색은 RAG 내부에서 수행
        self.assertEqual(regulation_calls["rag"][0][1], "regulation")
        self.assertEqual(market_calls["rag"][0][1], "market")
        self.assertEqual(regulation_calls["rag"][0][2], state["pipeline"])
        self.assertEqual(market_calls["rag"][0][2], state["pipeline"])
        self.assertEqual(
            [item for item in state["evidence"] if item["company_id"] == state["company"]["company_id"]],
            state["evidence"],
        )

        merge(state, select_candidate(state))
        self.assertEqual(state["pipeline"], [])
        self.assertEqual(state["scores"], {})
        self.assertEqual(
            [item for item in state["evidence"] if item["company_id"] == state["company"]["company_id"]],
            [],
        )
        self.assertEqual(len(state["evidence"]), 4)  # 누적 기록은 보존

    def test_unverifiable_quote_is_not_evidence_and_pipeline_is_empty(self):
        state = {"company": CANDIDATES[0]}
        tools, _ = fake_tools(
            "https://example.org/article",
            "원문에는 이 내용이 없다.",
            {
                "findings": [{"item": "technology", "fact": "검증 완료", "quote": "임상 검증을 마쳤다", "status": "확인됨"}],
                "pipeline": [{"substance": "ST-01", "indication": "폐암", "stage": "임상", "quote": "임상 검증을 마쳤다"}],
            },
        )
        result = tech_pipeline_node(state, tools=tools)
        self.assertEqual(result, {"evidence": [], "pipeline": []})

    def test_other_company_pipeline_is_not_passed_to_regulation(self):
        state = {"company": CANDIDATES[0]}
        tools, _ = fake_tools(
            "https://example.org/trials",
            "스탠다임은 신약을 개발한다. 다른 회사의 BAL0891은 고형암 임상 단계다.",
            {"pipeline": [{"substance": "BAL0891", "indication": "고형암", "stage": "임상",
                           "quote": "다른 회사의 BAL0891은 고형암 임상 단계다"}]},
        )
        self.assertEqual(tech_pipeline_node(state, tools=tools)["pipeline"], [])

    def test_rag_miss_uses_web_after_rag_retry(self):
        state = {"company": CANDIDATES[0]}
        tools, calls = fake_tools(
            "https://example.org/tech",
            "스탠다임 후보물질 ST-01은 전임상 단계다.",
            {"findings": [{"item": "stage", "fact": "전임상 단계", "quote": "ST-01은 전임상 단계다", "status": "기업 주장만"}]},
            rag_results=False,
        )
        result = tech_pipeline_node(state, tools=tools)
        self.assertEqual(len(calls["rag"]), 1)  # RAG 내부에서 국문·영문 검색과 재작성
        self.assertTrue(any("스탠다임" in query and "AI 신약 발굴" in query for query in calls["queries"]))
        self.assertEqual(result["evidence"][0]["source"], "https://example.org/tech")

    def test_langgraph_waits_for_all_research_before_judge(self):
        company_tools, _ = fake_tools(
            "https://example.org/company", "창업자는 제약사 경력이 있다.",
            {"findings": [{"item": "management", "fact": "제약사 경력", "quote": "제약사 경력이 있다", "status": "확인됨"}]},
        )
        tech_tools, _ = fake_tools(
            "https://example.org/tech", "스탠다임 ST-01은 폐암 치료용 전임상 물질이다.",
            {"findings": [{"item": "stage", "fact": "전임상", "quote": "폐암 치료용 전임상 물질", "status": "기업 주장만"}],
             "pipeline": [{"substance": "ST-01", "indication": "폐암", "stage": "전임상", "quote": "스탠다임 ST-01은 폐암 치료용 전임상 물질"}]},
        )
        regulation_tools, regulation_calls = fake_tools(
            "https://example.org/regulation", "ST-01의 IND 효력이 발생했다.",
            {"findings": [{"item": "regulation", "fact": "IND 효력", "quote": "IND 효력이 발생했다", "status": "확인됨"}]},
        )
        market_tools, market_calls = fake_tools(
            "https://example.org/market", "ST-01의 폐암 공동연구가 진행 중이다.",
            {"findings": [{"item": "sales", "fact": "공동연구", "quote": "폐암 공동연구가 진행 중", "status": "기업 주장만"}]},
        )
        judged = []

        def judge(state):
            handoff = {
                "company": state["company"],
                "pipeline": state["pipeline"],
                "evidence": [
                    item for item in state["evidence"]
                    if item["company_id"] == state["company"]["company_id"]
                ],
            }
            judged.append(handoff)
            return {"scores": {"received": len(handoff["evidence"])}}

        graph = StateGraph(State)
        graph.add_node("select", select_candidate)
        graph.add_node("company", lambda state: company_node(state, tools=company_tools))
        graph.add_node("tech", lambda state: tech_pipeline_node(state, tools=tech_tools))
        graph.add_node("regulation", lambda state: regulation_node(state, tools=regulation_tools))
        graph.add_node("market", lambda state: market_node(state, tools=market_tools))
        graph.add_node("judge", judge)
        graph.add_edge(START, "select")
        graph.add_edge("select", "company")
        graph.add_edge("select", "tech")
        graph.add_edge("tech", "regulation")
        graph.add_edge("tech", "market")
        graph.add_edge(["company", "regulation", "market"], "judge")
        graph.add_edge("judge", END)

        result = graph.compile().invoke({"candidates": CANDIDATES, "current_idx": -1, "evidence": []})
        self.assertEqual(len(judged), 1)
        self.assertEqual(result["scores"], {"received": 4})
        self.assertEqual({item["item"] for item in judged[0]["evidence"]}, {"management", "stage", "regulation", "sales"})
        self.assertTrue(any("ST-01 폐암" in query for query in regulation_calls["queries"]))
        self.assertTrue(any("ST-01 폐암" in query for query in market_calls["queries"]))


if __name__ == "__main__":
    unittest.main()
