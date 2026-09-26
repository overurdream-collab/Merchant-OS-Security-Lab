from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List
from .data_intelligence import DataIntelligenceAgent
from .strategist import StrategicDeveloperAgent
from .knowledge_learning import KnowledgeSourceRegistry


@dataclass(frozen=True)
class EvaluationCase:
    name: str
    input: Dict[str, Any]
    expected_codes: tuple[str, ...] = ()
    expected_metrics: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvaluationResult:
    agent: str
    passed: bool
    score: float
    checks: List[Dict[str, Any]]


class AgentCompetencySuite:
    """Deterministic promotion gate for the two critical agents."""

    def __init__(self):
        self.data_agent = DataIntelligenceAgent()
        self.strategy_agent = StrategicDeveloperAgent()

    def cases(self) -> List[EvaluationCase]:
        return [
            EvaluationCase("market_gap", {
                "merchants": [{"taxonomy": {"primary_category": "fashion"}}],
                "customers": [{"taxonomy": {"purchase_categories": ["electronics"]}}] * 4,
            }, expected_metrics=("market_signals", "hypotheses", "data_sufficiency")),
            EvaluationCase("no_fake_finance", {
                "merchants": [], "customers": [], "events": [],
            }, expected_metrics=("outcome_metrics", "financial_safety")),
            EvaluationCase("delivery_leakage", {
                "merchants": [{"name": "A"}], "customers": [],
                "data_intelligence": {
                    "data_gaps": {}, "market_signals": {"demand_supply_gaps": []},
                    "outcome_metrics": {"orders": {"created": 10, "delivered": 2}},
                },
            }, expected_codes=("fulfillment_visibility",)),
            EvaluationCase("missing_lifecycle", {
                "merchants": [{"name": "A"}], "customers": [{"name": "B"}],
                "data_intelligence": {
                    "data_gaps": {"merchant_missing_city": 0, "customer_missing_city": 0, "customer_missing_age": 0},
                    "market_signals": {"demand_supply_gaps": []}, "outcome_metrics": {},
                },
            }, expected_codes=("merchant_performance", "customer_lifecycle")),
            EvaluationCase("blind_spot", {
                "merchants": [{"name": "A"}], "customers": [{"name": "B"}],
                "data_intelligence": {
                    "blind_spots": [{"code": "commission_visibility"}],
                    "data_gaps": {}, "market_signals": {"demand_supply_gaps": []},
                    "outcome_metrics": {},
                },
            }, expected_codes=("blind_spot:commission_visibility",)),
        ]

    def evaluate_data_intelligence(self) -> EvaluationResult:
        checks = []
        for case in self.cases():
            if case.name in {"delivery_leakage", "missing_lifecycle", "blind_spot"}:
                continue
            out = self.data_agent.analyze(
                case.input.get("merchants", []), case.input.get("customers", []), case.input.get("events")
            )
            ok = all(key in out for key in case.expected_metrics)
            if case.name == "no_fake_finance":
                ok = ok and out["outcome_metrics"]["financial"]["commission_observed"] == 0
            checks.append({"case": case.name, "passed": ok})
        return self._result("data_intelligence", checks)

    def evaluate_strategist(self) -> EvaluationResult:
        checks = []
        for case in self.cases():
            if not case.expected_codes:
                continue
            out = self.strategy_agent.analyze(case.input)
            codes = {x["code"] for x in out.get("suggestions", [])}
            ok = all(code in codes for code in case.expected_codes)
            checks.append({"case": case.name, "passed": ok})
        return self._result("strategic_developer", checks)

    @staticmethod
    def _result(agent: str, checks: List[Dict[str, Any]]) -> EvaluationResult:
        score = sum(c["passed"] for c in checks) / len(checks) if checks else 0.0
        return EvaluationResult(agent, score >= 0.9, round(score, 4), checks)
