import json

import pytest

from src.merchant_os import database
from src.merchant_os.agent_runtime import AgentDefinition
from src.merchant_os.intake import intake_message
from src.merchant_os.professor_os import Mission, ProfessorOS


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "qualification.sqlite"))
    database.ensure_schema()
    return database


def test_customer_multi_turn_messages_preserve_customer_and_open_conversation(isolated_db):
    first = intake_message(
        message_id="wamid.TURN1",
        wa_id="967700000001",
        sender_name="Test Customer",
        message_type="text",
        text="أريد معرفة سعر المنتج",
        raw_payload={"turn": 1},
    )
    second = intake_message(
        message_id="wamid.TURN2",
        wa_id="967700000001",
        sender_name="Test Customer",
        message_type="text",
        text="وإذا طلبته كم يستغرق التوصيل؟",
        raw_payload={"turn": 2},
    )

    assert second["customer"]["id"] == first["customer"]["id"]
    assert second["conversation"]["id"] == first["conversation"]["id"]

    with database.get_connection() as db:
        messages = db.execute(
            """SELECT message_id, customer_id, conversation_id, text
               FROM messages
               WHERE customer_id=?
               ORDER BY received_at ASC, message_id ASC""",
            (first["customer"]["id"],),
        ).fetchall()

    assert [row["message_id"] for row in messages] == ["wamid.TURN1", "wamid.TURN2"]
    assert all(row["conversation_id"] == first["conversation"]["id"] for row in messages)


def test_professor_partial_failure_preserves_completed_prefix_and_audit(monkeypatch, tmp_path):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "failure.sqlite"))
    database.ensure_schema()

    professor = ProfessorOS()

    def broken_data(_input):
        raise RuntimeError("data specialist exploded")

    professor.runtime.register(
        AgentDefinition(
            "data",
            "qualification failure",
            ("professor.data",),
            broken_data,
        )
    )

    mission = Mission(
        goal="qualify partial failure",
        subject={
            "candidates": [{
                "name": "Qualified Merchant",
                "url": "https://example.com/merchant",
                "source_url": "https://example.com/merchant",
                "source_type": "official",
                "city": "Sanaa",
            }],
            "max_enrichment": 0,
        },
    )

    result = professor.run(mission)

    assert result["status"] == "failed"
    assert [item["agent"] for item in result["results"]] == [
        "research", "intelligence", "data"
    ]
    assert result["results"][0]["status"] == "completed"
    assert result["results"][1]["status"] == "completed"
    assert result["results"][2]["status"] == "failed"
    assert result["results"][2]["error"] == "data specialist exploded"

    with database.get_connection() as db:
        rows = db.execute(
            """SELECT task_id, parent_task_id, agent, status, error
               FROM agent_runs
               WHERE task_type='professor.data'
               ORDER BY run_id DESC LIMIT 1"""
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["agent"] == "data"
    assert rows[0]["status"] == "failed"
    assert rows[0]["error"] == "data specialist exploded"
