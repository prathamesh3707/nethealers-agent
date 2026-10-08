from nethealers.kb.adviser import authority, validate

PASSAGES = {
    "P1": {"scope": "national"},
    "P2": {"scope": "global"},
    "P3": {"scope": "operator"},
    "P4": {"scope": "regional"},
}


def test_invented_citations_are_removed():
    out = validate({"verdict": "conditional", "answer": "Allowed with limits [P1] [P9].",
                    "conditions": ["Keep spare capacity [P3, P7]."]}, PASSAGES)
    assert "[P9]" not in out["answer"] and "[P7]" not in out["conditions"][0]
    assert out["cited"] == ["P1", "P3"]


def test_a_foreign_example_alone_cannot_settle_what_is_allowed_in_india():
    out = validate({"verdict": "allowed", "answer": "The EU allows it [P2], so does Sri Lanka [P4]."}, PASSAGES)
    assert out["verdict"] == "not established" and out["confidence"] == "low"


def test_an_indian_passage_can_support_a_verdict():
    out = validate({"verdict": "not allowed", "answer": "The Act forbids it (P1, P2)."}, PASSAGES)
    assert out["verdict"] == "not allowed"


def test_unclear_answers_default_to_not_established():
    out = validate({"verdict": "probably", "answer": "Hard to say."}, PASSAGES)
    assert out["verdict"] == "not established"
    assert out["responsible"] == "not stated in the passages"


def test_authority_labels():
    assert authority("national", "law") == "Indian law (binding)"
    assert "not binding" in authority("national", "recommendation")
    assert authority("global", "law").startswith("Foreign example")
