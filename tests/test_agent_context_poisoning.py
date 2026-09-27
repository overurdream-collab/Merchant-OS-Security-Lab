from src.merchant_os import database
from src.merchant_os.agent_runtime import AgentDefinition
from src.merchant_os.professor_os import Mission, ProfessorOS


def test_professor_specialist_can_replace_prior_evidence_with_untrusted_output(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "context.sqlite"))
    database.ensure_schema()

    professor = ProfessorOS()

    def replacement(_input):
        return {
            "evidence": [{
                "source": "synthetic-source",
                "data": {"claim": "synthetic"},
            }],
            "merchant_scores": [],
        }

    professor.runtime.register(
        AgentDefinition(
            "intelligence",
            "qualification context replacement",
            ("professor.intelligence",),
            replacement,
        )
    )

    mission = Mission(
        goal="context replacement qualification",
        subject={
            "candidates": [{
                "name": "Legitimate Merchant",
                "url": "https://example.com/merchant",
                "source_url": "https://example.com/merchant",
                "source_type": "official",
            }],
            "max_enrichment": 0,
        },
    )

    result = professor.run(mission)

    assert result["status"] == "ready_for_action"
    assert result["final"]["evidence"][0]["source"] == "https://example.com/merchant"
    assert result["final"]["evidence"][1]["source"] == "synthetic-source"
