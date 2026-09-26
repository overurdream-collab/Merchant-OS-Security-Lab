from src.merchant_os.data_intelligence import DataIntelligenceAgent
from src.merchant_os.strategist import StrategicDeveloperAgent
from src.merchant_os.agent_training import AgentCompetencySuite
from src.merchant_os.knowledge_learning import KnowledgeSourceRegistry, KnowledgeLearningLoop


def test_data_agent_discovers_gap_and_hypothesis():
    out = DataIntelligenceAgent().analyze(
        [{"taxonomy": {"primary_category": "fashion"}}],
        [{"taxonomy": {"purchase_categories": ["electronics"]}}] * 4,
        [],
    )
    assert out["market_signals"]["demand_supply_gaps"]
    assert out["hypotheses"]
    assert out["data_sufficiency"]["overall"] >= 0


def test_data_agent_never_invents_financials():
    out = DataIntelligenceAgent().analyze([], [], [])
    assert out["outcome_metrics"]["financial"]["commission_observed"] == 0
    assert out["outcome_metrics"]["financial"]["order_value_observed"] == 0


def test_strategist_finds_blind_spot_and_requires_validation():
    out = StrategicDeveloperAgent().analyze({
        "merchants": [{"name": "A"}],
        "customers": [{"name": "B"}],
        "data_intelligence": {
            "blind_spots": [{"code": "commission_visibility"}],
            "data_gaps": {},
            "market_signals": {"demand_supply_gaps": []},
            "outcome_metrics": {},
        },
    })
    proposal = next(x for x in out["suggestions"] if x["code"] == "blind_spot:commission_visibility")
    assert proposal["requires_validation"] is True
    assert proposal["execution"] == "blocked_until_validated_and_approved"


def test_competency_suite_passes():
    suite = AgentCompetencySuite()
    assert suite.evaluate_data_intelligence().passed
    assert suite.evaluate_strategist().passed


def test_knowledge_sources_are_extensible_and_deduplicated():
    registry = KnowledgeSourceRegistry()
    registry.register("source_a", lambda q: [{"title": "A", "content": "same", "url": "https://a"}], reliability=0.9)
    registry.register("source_b", lambda q: [{"title": "B", "content": "same", "url": "https://a"}, {"title": "C", "content": "new"}], reliability=0.8)
    loop = KnowledgeLearningLoop(registry)
    snap = loop.refresh("merchant market")
    assert len(snap.items) == 2
    assert registry.list_sources() == ["source_a", "source_b"]


def test_data_agent_uses_observed_events_for_real_operational_signals():
    events = [
        {"event_type": "merchant_contacted", "subject_id": "m1", "occurred_at": "2026-01-01T10:00:00+00:00", "source": "test"},
        {"event_type": "merchant_response", "subject_id": "m1", "occurred_at": "2026-01-01T10:02:00+00:00", "source": "test"},
        {"event_type": "order_created", "subject_id": "o1", "occurred_at": "2026-01-01T11:00:00+00:00", "value": 1000, "source": "test"},
        {"event_type": "order_delivered", "subject_id": "o1", "occurred_at": "2026-01-02T11:00:00+00:00", "source": "test"},
        {"event_type": "commission_earned", "subject_id": "o1", "occurred_at": "2026-01-02T11:01:00+00:00", "value": 100, "source": "test"},
    ]
    out = DataIntelligenceAgent().analyze(
        [{"taxonomy": {"primary_category": "fashion"}}],
        [{"taxonomy": {"purchase_categories": ["fashion"]}}],
        events,
    )
    assert out["outcome_metrics"]["financial"]["commission_observed"] == 100
    assert out["outcome_metrics"]["orders"]["delivered"] == 1
    assert out["performance_signals"]


def test_strategist_detects_merchant_performance_capability_gap():
    out = StrategicDeveloperAgent().analyze({
        "merchants": [{"name": "A"}],
        "customers": [{"name": "B"}],
        "data_intelligence": {
            "data_gaps": {},
            "market_signals": {"demand_supply_gaps": []},
            "outcome_metrics": {"conversion": {"merchant_response_to_conversion": None}},
        },
    })
    codes = {x["code"] for x in out["suggestions"]}
    assert "merchant_performance" in codes
