import csv
import io

from src.merchant_os.data_intelligence import DataIntelligenceAgent
from src.merchant_os.strategist import StrategicDeveloperAgent
from src.merchant_os.professor_os import Mission, ProfessorOS
from src.merchant_os.research_tools import ResearchResult, StaticResearchProvider


def _read_csv(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_real_mvp_path_csv_to_professor_decision():
    merchants = _read_csv("""name,category,city,source_url
Yemen Fashion,fashion,Sana'a,https://example.com/yemen-fashion
Sana'a Electronics,electronics,Sana'a,https://example.com/electronics
""")
    customers = _read_csv("""name,category,city,purchase_frequency
Customer A,electronics,Sana'a,weekly
Customer B,electronics,Sana'a,monthly
Customer C,electronics,Sana'a,weekly
""")

    merchant_records = [
        {"name": r["name"], "city": r["city"], "source_url": r["source_url"],
         "taxonomy": {"primary_category": r["category"]}}
        for r in merchants
    ]
    customer_records = [
        {"name": r["name"], "city": r["city"],
         "taxonomy": {"purchase_categories": [r["category"]],
                      "purchase_frequency": r["purchase_frequency"]}}
        for r in customers
    ]

    data = DataIntelligenceAgent().analyze(merchant_records, customer_records, [])
    assert data["merchant_metrics"]["count"] == 2
    assert data["customer_metrics"]["count"] == 3
    assert data["market_signals"]["demand_supply_gaps"]

    strategy = StrategicDeveloperAgent().analyze({
        "merchants": merchant_records,
        "customers": customer_records,
        "data_intelligence": data,
    })
    assert strategy["development_queue"]
    assert all(x["validation_required"] for x in strategy["development_queue"])

    provider = StaticResearchProvider([
        ResearchResult("Yemen Fashion", "https://example.com/yemen-fashion", "fashion Sana'a"),
        ResearchResult("Sana'a Electronics", "https://example.com/electronics", "electronics Sana'a"),
    ])
    professor = ProfessorOS(research_provider=provider)
    result = professor.run(Mission(
        goal="rank merchants for electronics demand",
        subject={
            "research_query": "electronics Sana'a",
            "category": "electronics",
            "city": "Sana'a",
            "discovery_enabled": False,
            "customers": customer_records,
            "candidates": [
                {"name": r["name"], "url": r["source_url"], "source_url": r["source_url"],
                 "category": r["category"], "city": r["city"], "snippet": "observed"}
                for r in merchants
            ],
            "business_events": [],
        },
        constraints={"minimum_confidence": 0.0},
    ))
    assert result["status"] in {"ready_for_action", "needs_review"}
    assert len(result["specialists"]) == 10
    assert result["final"]["ranked_merchants"]
    assert result["final"]["jev"]["choice"]
    assert result["final"]["verification"]["verified"] is True


class FailingProvider:
    def search(self, query, limit=10):
        raise TimeoutError("simulated provider timeout")


def test_mvp_external_failure_does_not_crash_core():
    professor = ProfessorOS(research_provider=FailingProvider())
    result = professor.run(Mission(
        goal="safe failure test",
        subject={
            "research_query": "electronics Sana'a",
            "discovery_enabled": False,
            "customers": [],
            "candidates": [],
        },
        constraints={"minimum_confidence": 0.0},
    ))
    research_outputs = [x["output"] for x in result["results"] if x["agent"] == "research"]
    assert research_outputs
    assert research_outputs[0]["research_error"]
    assert result["status"] in {"needs_review", "failed"}
