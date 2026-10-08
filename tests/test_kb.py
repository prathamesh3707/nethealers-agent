from pathlib import Path

import pytest

from nethealers.kb import AGENT_SCOPES, Library, source_meta
from nethealers.kb.gaps import GAP_TYPES, _merge, _validated, gather, load_topics
from nethealers.kb.library import Hit

BUILT = (Path(__file__).resolve().parents[1] / "data" / "kb" / "index" / "vectors.npy").exists()
needs_kb = pytest.mark.skipif(not BUILT, reason="build the knowledge base first: scripts/build_library.py")


def hit(pid, doc, score=0.5, page=1):
    return Hit(pid, doc, doc.upper(), "law", page, "text", score)


def test_every_source_has_a_scope_and_the_agent_only_cites_host_country_standards_and_operator():
    meta = source_meta()
    assert {m["scope"] for m in meta.values()} == {"national", "operator", "standard", "global", "regional"}
    assert set(AGENT_SCOPES) == {"national", "operator", "standard"}
    assert all(m.get("country") for m in meta.values())


def test_gap_answers_keep_only_real_citations_and_take_the_country_from_the_records():
    by_num = {"P1": ("NATIONAL", hit("a:1:0", "telecom-act-2023")),
              "P2": ("GLOBAL", hit("b:1:0", "eu-ai-act")),
              "P3": ("REGIONAL", hit("c:1:0", "lk-pdpa-2022"))}
    data = {
        "national_position": "The Act covers this [P1] and also [P9].",
        "gaps": [{"type": "made-up type", "summary": "Unclear [P1] [P7]"}],
        "severity": "extreme",
        "global_examples": [{"passage": "P2", "what_it_does": "x"}, {"passage": "P8", "what_it_does": "invented"},
                            {"passage": "P1", "what_it_does": "national passage passed off as global"}],
        "regional": [{"passage": "P3", "what_it_does": "y"}],
        "recommendation": "Do it [P2].",
    }
    out = _validated(data, by_num, source_meta())
    assert "[P9]" not in out["national_position"] and "[P1]" in out["national_position"]
    assert out["gaps"][0]["type"] in GAP_TYPES and "[P7]" not in out["gaps"][0]["summary"]
    assert out["severity"] == "medium"
    assert [e["passage"] for e in out["global_examples"]] == ["P2"]  # invented and wrong-group examples dropped
    assert out["global_examples"][0]["jurisdiction"] == "European Union"  # from the records, not the model
    assert out["regional"][0]["jurisdiction"] == "Sri Lanka"


def test_merging_searches_keeps_each_passage_once_with_its_best_score():
    merged = _merge([[hit("x", "d", 0.4), hit("y", "d", 0.6)], [hit("x", "d", 0.7)]], k=5)
    assert [(h.id, h.score) for h in merged] == [("x", 0.7), ("y", 0.6)]


@needs_kb
def test_evidence_is_grouped_by_scope_and_finds_the_emergency_priority_provision():
    lib = Library.open(prefer_postgres=False)
    meta = source_meta()
    topic = next(t for t in load_topics() if t["id"] == "emergency-priority")
    ev = gather(lib, topic["question"], topic["queries"])
    assert ev.national and all(meta[h.doc_id]["scope"] == "national" for h in ev.national)
    assert all(meta[h.doc_id]["scope"] == "global" for h in ev.global_)
    assert all(meta[h.doc_id]["scope"] == "regional" for h in ev.regional)
    # Telecommunications Act 2023, section 20: priority routing for responders during a public emergency
    assert any(h.doc_id == "telecom-act-2023" and "priority" in h.text for h in ev.national)


@needs_kb
def test_the_agent_search_never_returns_foreign_documents():
    lib = Library.open(prefer_postgres=False)
    meta = source_meta()
    hits = lib.search("human oversight of AI systems that control critical infrastructure", k=8, scopes=AGENT_SCOPES)
    assert hits and all(meta[h.doc_id]["scope"] in AGENT_SCOPES for h in hits)


def test_passages_pinned_in_the_itu_alignment_exist():
    import yaml

    lib = Library.open()
    if lib.store.count() == 0:
        pytest.skip("build the knowledge base first: scripts/build_library.py")
    rows = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "itu_alignment.yaml").read_text())
    ids = {pid for r in rows["policy_to_control"] for pid in r["passages"]}
    assert ids <= set(lib.get(sorted(ids)))  # ids change if the documents are re-split: re-pin them


def test_remote_knowledge_base_reads_both_reply_shapes_and_falls_back_when_down(monkeypatch):
    from nethealers.kb.library import RemoteStore

    class Local:
        def search(self, vec, k, kinds, docs):
            return [hit("local:1:0", "telecom-act-2023")]

    rs = RemoteStore("http://sandbox.invalid/search", Local())
    nested = {"results": [{"id": "x:3:0", "text": "t", "score": 0.9,
                           "metadata": {"doc_id": "x", "title": "X", "kind": "law", "page": 3}}]}
    monkeypatch.setattr(rs, "_post", lambda body: nested)
    h = rs.search_text("q", lambda q: None, 3, None, None)[0]
    assert (h.id, h.doc_id, h.title, h.page, h.score) == ("x:3:0", "x", "X", 3, 0.9)
    monkeypatch.setattr(rs, "_post", lambda body: [{"id": "y:1:0", "text": "t", "doc_id": "y"}])
    assert rs.search_text("q", lambda q: None, 3, None, None)[0].id == "y:1:0"

    def down(body):
        raise OSError("unreachable")

    monkeypatch.setattr(rs, "_post", down)
    assert rs.search_text("q", lambda q: None, 3, None, None)[0].id == "local:1:0"
    assert rs.last_error == "unreachable"


def test_grouped_gap_citations_are_checked_one_by_one():
    by_num = {"P1": ("NATIONAL", hit("a:1:0", "telecom-act-2023")), "P3": ("NATIONAL", hit("b:1:0", "dpdp-act-2023"))}
    out = _validated({"national_position": "Covered in part [P1, P3, P9].", "gaps": []}, by_num, {})
    assert out["national_position"] == "Covered in part [P1] [P3]."
