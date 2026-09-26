from src.merchant_os.jev import JEVDecisionEngine


def test_jev_confidence_is_unchanged_by_contradiction_with_same_evidence_count():
    engine = JEVDecisionEngine()

    consistent = engine.decide(
        "is stock available?",
        [
            {"source": "official-a", "claim": "stock=10"},
            {"source": "official-b", "claim": "stock=10"},
            {"source": "official-c", "claim": "stock=10"},
        ],
        [{"name": "item", "score": 0.9}],
    )
    contradictory = engine.decide(
        "is stock available?",
        [
            {"source": "official-a", "claim": "stock=10"},
            {"source": "official-b", "claim": "stock=0"},
            {"source": "official-c", "claim": "stock=10"},
        ],
        [{"name": "item", "score": 0.9}],
    )

    assert consistent.score["confidence"] == contradictory.score["confidence"] == 0.6


def test_jev_confidence_is_unchanged_by_manipulated_provenance():
    engine = JEVDecisionEngine()

    trusted = engine.decide(
        "question",
        [
            {"source": "official-a", "claim": "valid"},
            {"source": "official-b", "claim": "valid"},
        ],
        [{"name": "candidate", "score": 0.8}],
    )
    manipulated = engine.decide(
        "question",
        [
            {"source": "official-a", "claim": "valid"},
            {"source": "official-a", "claim": "valid"},
        ],
        [{"name": "candidate", "score": 0.8}],
    )

    assert trusted.score["confidence"] == manipulated.score["confidence"] == 0.4


def test_jev_mixed_scored_and_unscored_candidates_falls_back_to_first_candidate():
    engine = JEVDecisionEngine()

    result = engine.decide(
        "choose candidate",
        [{"source": "official-a", "claim": "candidate data"}],
        [
            {"name": "first", "score": 0.1},
            {"name": "higher", "score": 0.9},
            {"name": "unscored"},
        ],
    )

    assert result.choice["selected"]["name"] == "first"


def test_jev_weak_evidence_can_still_produce_maximum_count_based_confidence():
    engine = JEVDecisionEngine()

    result = engine.decide(
        "question",
        [
            {"source": "unknown-1", "claim": "unsupported"},
            {"source": "unknown-2", "claim": "unsupported"},
            {"source": "unknown-3", "claim": "unsupported"},
            {"source": "unknown-4", "claim": "unsupported"},
            {"source": "unknown-5", "claim": "unsupported"},
        ],
        [{"name": "candidate", "score": 0.2}],
    )

    assert result.score["confidence"] == 1.0
