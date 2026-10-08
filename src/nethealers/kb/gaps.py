"""Policy, strategy and standards gap analysis over the knowledge base.

For each question in config/gap_topics.yaml, the analyst retrieves:
  - what the host country's documents say (national),
  - what the operator policy and the ITU-T standards say,
  - how each global example and each neighbouring country handles it (best passages per document),
then a language model names the gaps, using only those passages and citing them by number. Citations to
passages it was not given are dropped, and which country an example comes from is taken from the document
records, never from the model, so every example in the output can be checked against its source.

Without a language model, the analysis falls back to retrieval only: it reports how closely the national
documents address each question and lists the closest passages from elsewhere, for a person to judge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..llm import LLM, LLMUnavailable
from .library import Hit, Library, source_meta

ROOT = Path(__file__).resolve().parents[3]
TOPICS = ROOT / "config" / "gap_topics.yaml"
OUT_JSON = ROOT / "docs" / "gap_analysis.json"
OUT_MD = ROOT / "docs" / "gap_analysis.md"

# Ten kinds of gap, each with what it means; the model must pick from these.
GAP_KINDS = {
    "responsibility": "it is unclear who is accountable or who must act",
    "legal coverage": "the law does not address the question",
    "standards": "no technical standard covers it, or standards conflict",
    "implementation": "principles exist, but no mechanism puts them into practice",
    "coordination": "several bodies are involved with no way set out to coordinate them",
    "conflicting objectives": "two goals pull against each other with no rule for choosing",
    "data": "rules for the data the AI needs are unclear",
    "evaluation": "no way is set out to test or certify the AI before or after deployment",
    "auditability": "no requirement to log or explain automated decisions",
    "cross-border": "rules differ across borders or between neighbouring networks",
}
GAP_TYPES = list(GAP_KINDS)
_OLD_LABELS = {"unclear responsibility": "responsibility", "legislative gap": "legal coverage",
               "standards gap": "standards", "technology gap": "implementation", "coordination problem": "coordination"}
NATIONAL_COVERED = 0.55  # similarity above which a national passage plausibly addresses the question

SYSTEM = f"""You are a telecom policy analyst preparing a gap analysis for the ITU AI for Good Build-a-thon.
The domain is an autonomous AI agent that troubleshoots and optimises a live 5G network (self-healing).
The host country is India. You are given one question and numbered passages [P1], [P2], ... from:
host-country documents (NATIONAL), the operator's own policy (OPERATOR), ITU-T standards (STANDARD),
other jurisdictions (GLOBAL) and neighbouring countries (REGIONAL).

Rules:
- Use only the passages. Every statement of what a document says must cite passage numbers like [P3].
- Read the national passages carefully: a provision may answer the question in different words (for example
  "routed on priority during public emergency" answers a question about emergency priority). Credit it.
- Call something a "legal coverage" gap only if the national passages are on the topic and still leave the
  question unanswered. If the passages are simply off-topic, write "not found in the retrieved passages",
  use confidence "low", and do not claim the law is silent.
- Do not invent laws, articles or countries. If no global or regional passage is relevant, return an empty list.
- Gap types must be from this list (type: meaning):
{chr(10).join(f"  {k}: {v}" for k, v in GAP_KINDS.items())}
- Focus on the domain (AI operating telecom networks), not on general recommendations to one country.

Reply with JSON only:
{{"national_position": "<2-3 sentences with citations>",
  "gaps": [{{"type": "<gap type>", "summary": "<1-2 sentences with citations>"}}],
  "conflicts": "<objectives that pull against each other, with citations, or empty>",
  "severity": "high|medium|low",
  "global_examples": [{{"passage": "P<n>", "what_it_does": "<1 sentence>"}}],
  "regional": [{{"passage": "P<n>", "what_it_does": "<1 sentence>"}}],
  "recommendation": "<2 sentences: what a rule or standard should clarify for AI-operated networks>",
  "confidence": "high|medium|low"}}"""


@dataclass
class Evidence:
    national: list[Hit]
    operator: list[Hit]
    standard: list[Hit]
    global_: list[Hit]
    regional: list[Hit]

    def numbered(self) -> list[tuple[str, str, Hit]]:
        out = []
        for group, hits in (("NATIONAL", self.national), ("OPERATOR", self.operator), ("STANDARD", self.standard),
                            ("GLOBAL", self.global_), ("REGIONAL", self.regional)):
            for h in hits:
                out.append((f"P{len(out) + 1}", group, h))
        return out


def load_topics() -> list[dict]:
    return yaml.safe_load(TOPICS.read_text())


def _merge(results: list[list[Hit]], k: int) -> list[Hit]:
    """Best `k` distinct passages across several searches (each passage scored by its best match)."""
    best: dict[str, Hit] = {}
    for hits in results:
        for h in hits:
            if h.id not in best or h.score > best[h.id].score:
                best[h.id] = h
    return sorted(best.values(), key=lambda h: -h.score)[:k]


def gather(lib: Library, question: str, queries: list[str] | None = None) -> Evidence:
    """Search with the question and with extra phrasings in the documents' own language, then merge."""
    meta = source_meta()
    qs = [question, *(queries or [])]

    def search(k: int, **kw) -> list[Hit]:
        return _merge([lib.search(q, k=k, **kw) for q in qs], k)

    def per_doc(scope: str, k: int, floor: float) -> list[Hit]:
        hits = []
        for d, m in meta.items():
            if m.get("scope") == scope:
                hits += [h for h in search(k, docs=[d]) if h.score >= floor]
        return sorted(hits, key=lambda h: -h.score)

    return Evidence(
        national=search(6, scopes=["national"]),
        operator=search(1, scopes=["operator"]),
        standard=[h for h in search(3, scopes=["standard"]) if h.score >= 0.3],
        global_=per_doc("global", 2, 0.35)[:5],
        regional=per_doc("regional", 1, 0.35)[:3],
    )


def _cite(h: Hit, meta: dict) -> dict:
    m = meta.get(h.doc_id, {})
    return {"passage_id": h.id, "doc_id": h.doc_id, "title": h.title, "page": h.page, "score": round(h.score, 3),
            "scope": m.get("scope", ""), "country": m.get("country", ""), "url": m.get("url", ""),
            "excerpt": " ".join(h.text.split())[:420]}


def analyse(topic: dict, lib: Library, llm: LLM | None) -> dict:
    meta = source_meta()
    ev = gather(lib, topic["question"], topic.get("queries"))
    numbered = ev.numbered()
    by_num = {n: (g, h) for n, g, h in numbered}
    best_national = max((h.score for h in ev.national), default=0.0)
    base = {
        "id": topic["id"], "title": topic["title"], "question": topic["question"], "seen_in": topic.get("seen_in", ""),
        "national_coverage": round(best_national, 3),
        "passages": {n: {"group": g, **_cite(h, meta)} for n, g, h in numbered},
    }
    if llm is not None:
        user = json.dumps({"question": topic["question"],
                           "where_our_agent_meets_it": topic.get("seen_in", ""),
                           "passages": [{"n": n, "group": g, "source": h.cite(), "text": h.text[:900]}
                                        for n, g, h in numbered]}, indent=1)
        try:
            ans = llm.chat_json(SYSTEM, user)
            return {**base, **_validated(ans.data, by_num, meta), "method": f"language model ({ans.source})"}
        except (LLMUnavailable, ValueError) as e:
            base["note"] = f"language model unavailable ({str(e)[:80]}); retrieval only"
    return {**base, **_retrieval_only(ev, best_national, by_num, meta), "method": "retrieval only"}


def split_groups(text: str) -> str:
    """"[P2, P3]" or "(P2, P3)" -> "[P2] [P3]", so every citation is checked on its own."""
    import re

    return re.sub(r"[\[(]\s*(P\d+(?:\s*[,;]\s*P\d+)+)\s*[\])]",
                  lambda m: " ".join(f"[{x}]" for x in re.findall(r"P\d+", m.group(1))), str(text or ""))


def _valid_refs(text: str, by_num: dict) -> str:
    """Remove citations to passages the model was not given."""
    import re

    text = re.sub(r"\[(P\d+)\]", lambda m: m.group(0) if m.group(1) in by_num else "", split_groups(text))
    return re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s{2,}", " ", text)).strip()


def _validated(data: dict, by_num: dict, meta: dict) -> dict:
    def examples(items, want: str) -> list[dict]:
        out = []
        for it in items or []:
            n = str(it.get("passage", "")).strip("[] ")
            if n not in by_num or by_num[n][0] != want:
                continue  # not a passage we gave it, or from the wrong group: drop it
            h = by_num[n][1]
            out.append({"passage": n, "jurisdiction": meta.get(h.doc_id, {}).get("country", ""), "title": h.title,
                        "page": h.page, "what_it_does": _valid_refs(str(it.get("what_it_does", "")), by_num)})
        return out

    def kind(t) -> str:
        t = str(t or "").strip().lower()
        t = _OLD_LABELS.get(t, t)
        return t if t in GAP_TYPES else "responsibility"

    gaps = [{"type": kind(g.get("type")),
             "summary": _valid_refs(str(g.get("summary", "")), by_num)} for g in data.get("gaps", []) if g.get("summary")]
    sev = str(data.get("severity", "medium")).lower()
    conf = str(data.get("confidence", "medium")).lower()
    return {
        "national_position": _valid_refs(str(data.get("national_position", "")), by_num),
        "gaps": gaps,
        "conflicts": _valid_refs(str(data.get("conflicts", "")), by_num),
        "severity": sev if sev in ("high", "medium", "low") else "medium",
        "global_examples": examples(data.get("global_examples"), "GLOBAL"),
        "regional": examples(data.get("regional"), "REGIONAL"),
        "recommendation": _valid_refs(str(data.get("recommendation", "")), by_num),
        "confidence": conf if conf in ("high", "medium", "low") else "medium",
    }


def _retrieval_only(ev: Evidence, best_national: float, by_num: dict, meta: dict) -> dict:
    num_of = {h.id: n for n, (_, h) in by_num.items()}
    covered = best_national >= NATIONAL_COVERED
    return {
        "national_position": ("The closest national passages may address this; a person should confirm. "
                              if covered else "No national passage closely addresses this question. ")
                             + " ".join(f"[{num_of[h.id]}]" for h in ev.national[:3]),
        "gaps": [] if covered else [{"type": "legal coverage",
                                     "summary": "The host-country documents in the knowledge base do not clearly cover "
                                                "this question (best match "
                                                f"{best_national:.2f})."}],
        "conflicts": "",
        "severity": "medium" if not covered else "low",
        "global_examples": [{"passage": num_of[h.id], "jurisdiction": meta.get(h.doc_id, {}).get("country", ""),
                             "title": h.title, "page": h.page, "what_it_does": " ".join(h.text.split())[:200] + "…"}
                            for h in ev.global_[:3]],
        "regional": [{"passage": num_of[h.id], "jurisdiction": meta.get(h.doc_id, {}).get("country", ""),
                      "title": h.title, "page": h.page, "what_it_does": " ".join(h.text.split())[:200] + "…"}
                     for h in ev.regional[:2]],
        "recommendation": "",
        "confidence": "low",
    }


def run(llm: LLM | None = None, log=print) -> dict:
    lib = Library.open()
    if lib.store.count() == 0:
        raise RuntimeError("The knowledge base is empty: run scripts/build_library.py first.")
    if llm is not None:
        llm.max_tokens, llm.timeout_s = 1500, 90.0
    results = []
    for t in load_topics():
        log(f"  {t['id']}...")
        results.append(analyse(t, lib, llm))
    docs = lib.documents()
    report = {"topics": results, "documents": docs,
              "gap_types": GAP_TYPES, "method": results[0]["method"] if results else ""}
    OUT_JSON.write_text(json.dumps(report, indent=1, ensure_ascii=False))
    OUT_MD.write_text(to_markdown(report))
    return report


def to_markdown(report: dict) -> str:
    sev_rank = {"high": 0, "medium": 1, "low": 2}
    topics = sorted(report["topics"], key=lambda t: sev_rank.get(t["severity"], 3))
    lines = [
        "# Policy, strategy and standards gap analysis",
        "",
        "Domain: an autonomous AI agent that troubleshoots and optimises a live 5G network. Host country: India; "
        "neighbouring countries: Sri Lanka, Bangladesh, Nepal; global examples: EU, United States, Singapore; "
        "standards: ITU-T Y.3172, Y.3181, Y.3090.",
        "",
        f"Generated by `scripts/gap_analysis.py` ({report['method']}). Every statement cites a numbered passage from "
        "the knowledge base; the passages are listed under each topic with their source, page and link. Citations "
        "the language model invented were removed automatically, and the country of each example comes from the "
        "document records. The knowledge base is limited to the documents listed at the end: a gap here means "
        "*not covered by these documents*, which a lawyer should confirm before it is relied on.",
        "",
        "## Summary",
        "",
        "| Topic | Severity | Gap types | National coverage | Global examples | Regional |",
        "|---|---|---|---|---|---|",
    ]
    for t in topics:
        types = ", ".join(sorted({g["type"] for g in t["gaps"]})) or "none found"
        lines.append(f"| [{t['title']}](#{t['id']}) | {t['severity']} | {types} | {t['national_coverage']:.2f} | "
                     f"{', '.join(sorted({e['jurisdiction'] for e in t['global_examples']})) or '-'} | "
                     f"{', '.join(sorted({e['jurisdiction'] for e in t['regional']})) or '-'} |")
    for t in topics:
        lines += ["", f"## {t['title']}", f'<a id="{t["id"]}"></a>', "",
                  f"**Question.** {t['question']}", "",
                  f"**Where our agent meets it.** {t['seen_in']}", "",
                  f"**What the host country's documents say.** {t['national_position']}", ""]
        if t["gaps"]:
            lines.append("**Gaps.**")
            lines += [f"- *{g['type']}*: {g['summary']}" for g in t["gaps"]]
            lines.append("")
        if t.get("conflicts"):
            lines += [f"**Conflicting objectives.** {t['conflicts']}", ""]
        if t["global_examples"]:
            lines.append("**Global examples.**")
            lines += [f"- {e['jurisdiction']} ({e['title']}, p. {e['page']}) [{e['passage']}]: {e['what_it_does']}"
                      for e in t["global_examples"]]
            lines.append("")
        if t["regional"]:
            lines.append("**Neighbouring countries.**")
            lines += [f"- {e['jurisdiction']} ({e['title']}, p. {e['page']}) [{e['passage']}]: {e['what_it_does']}"
                      for e in t["regional"]]
            lines.append("")
        if t.get("recommendation"):
            lines += [f"**Recommendation.** {t['recommendation']}", ""]
        lines += [f"Severity: {t['severity']} · confidence: {t['confidence']} · method: {t['method']}", "",
                  "<details><summary>Passages</summary>", ""]
        for n, p in t["passages"].items():
            lines.append(f"- **[{n}]** {p['group'].lower()} · {p['title']}, p. {p['page']} (similarity {p['score']:.2f}): "
                         f"“{p['excerpt']}”")
        lines += ["", "</details>"]
    lines += ["", "## Documents in the knowledge base", "", "| Document | Scope | Country | Passages |",
              "|---|---|---|---|"]
    lines += [f"| [{d['title']}]({d.get('url', '')}) | {d.get('scope', '')} | {d.get('country', '')} | "
              f"{d['passages']} |" for d in report["documents"]]
    return "\n".join(lines) + "\n"
