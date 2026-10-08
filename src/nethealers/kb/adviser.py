"""The policy and legal adviser: answers a person's question from the knowledge base, with exact citations.

Anyone in the game can ask it something ("Can the agent move users onto the hospital tower?"), optionally about
the incident on screen. It searches the host country's documents, the operator policy, the ITU-T standards and
the global and regional examples, then a language model answers using only those passages. Every passage is
labelled with how much weight it carries (binding Indian law, a regulator's recommendation, guidance, a technical
standard, the operator's own policy, or a foreign example that does not apply in India).

Guard rails, all in plain code:
  - citations to passages the model was not given are removed;
  - an answer that cites nothing from India, the operator policy or a standard becomes "not established";
  - a foreign example can illustrate, but can never establish what is allowed in India;
  - the adviser only advises. It has no way to change the network.

Without a language model it returns the closest passages for a person to read, and says it cannot conclude.
"""

from __future__ import annotations

import json
import re

from ..llm import LLM, LLMUnavailable
from .gaps import gather, split_groups
from .library import Hit, Library, source_meta

VERDICTS = ("allowed", "conditional", "not allowed", "not established")

AUTHORITY = {
    ("national", "law"): "Indian law (binding)",
    ("national", "recommendation"): "Indian regulator's recommendation (not binding)",
    ("national", "guidance"): "Indian policy guidance (not binding)",
    ("operator", "operator"): "Operator policy (enforced by the rule-checker)",
    ("standard", "standard"): "Technical standard",
}
DECISIVE_SCOPES = ("national", "operator", "standard")  # passages that can support a verdict for India


def authority(scope: str, kind: str) -> str:
    if scope in ("global", "regional"):
        return "Foreign example (does not apply in India)"
    return AUTHORITY.get((scope, kind), f"{scope} {kind}")


SYSTEM = """You are the policy and legal adviser to the operations team of an Indian 5G operator. An autonomous
AI agent troubleshoots and optimises the network (moves phones between towers, changes beams, power and tilt),
and people ask you questions about what it may do. You advise; you never change the network yourself.

You get a question, sometimes the incident the team is looking at, and numbered passages [P1], [P2], ... Each
passage has a group (NATIONAL = Indian documents, OPERATOR = this operator's policy, STANDARD = ITU-T standards,
GLOBAL / REGIONAL = other countries) and an authority label.

Rules:
- Use only the passages. Cite every claim with passage numbers, one per bracket: [P2] or [P2][P5].
- Binding Indian law outranks recommendations and guidance. Say which kind of source you rely on.
- GLOBAL and REGIONAL passages never establish what is allowed in India. Use them only as "elsewhere, ..."
  examples, clearly marked as such.
- If the Indian, operator and standard passages do not answer the question, the verdict is "not established".
  Do not guess and do not fill gaps from general knowledge. Saying "not established" is a good answer.
- Name a responsible body (for example the Department of Telecommunications, TRAI, the Data Protection Board,
  the operator) only if a passage names it; otherwise write "not stated in the passages".
- You may use the incident's numbers, but refer to them in words ("the incident shows ..."), not in brackets.
- Keep it short and plain: the reader is an engineer, not a lawyer.

Reply with JSON only:
{"verdict": "allowed|conditional|not allowed|not established",
 "answer": "<2-4 plain sentences with citations>",
 "conditions": ["<condition with citation>", ...],
 "responsible": "<who is responsible, with citation, or 'not stated in the passages'>",
 "recommended_action": "<1 sentence: what the operations team should do now>",
 "elsewhere": "<1 sentence on a global or regional example with citation, or empty>",
 "confidence": "high|medium|low"}"""


def _clean(text: str, valid: set[str]) -> str:
    """Drop citations to passages the model was not given, and tidy what is left."""
    text = re.sub(r"\[incident[^\]]*\]", "(the incident on screen)", split_groups(text), flags=re.I)
    text = re.sub(r"\[(P\d+)\]", lambda m: m.group(0) if m.group(1) in valid else "", text)
    return re.sub(r"\s+([.,;:])", r"\1", re.sub(r"\s{2,}", " ", text)).strip()


def _cited(text: str) -> set[str]:
    return set(re.findall(r"\[(P\d+)\]", text or ""))


def ask(question: str, lib: Library, llm: LLM | None, incident: dict | None = None) -> dict:
    """Answer `question` from the knowledge base. `incident` is a short summary of the incident on screen."""
    question = question.strip()
    if not question:
        raise ValueError("empty question")
    meta = source_meta()
    queries = [f"{question} {incident.get('cause', '')} automated network change".strip()] if incident else []
    ev = gather(lib, question, queries)
    numbered = ev.numbered()
    passages = {}
    for n, group, h in numbered:
        m = meta.get(h.doc_id, {})
        passages[n] = {"group": group, "passage_id": h.id, "doc_id": h.doc_id, "title": h.title, "page": h.page,
                       "scope": m.get("scope", ""), "country": m.get("country", ""), "url": m.get("url", ""),
                       "authority": authority(m.get("scope", ""), h.kind), "score": round(h.score, 3),
                       "excerpt": " ".join(h.text.split())[:600]}
    base = {"question": question, "incident": incident, "passages": passages}
    if llm is None:
        return {**base, **_retrieval_only(numbered), "method": "retrieval only (no language model)"}
    user = json.dumps({"question": question, "incident_on_screen": incident,
                       "passages": [{"n": n, "group": g, "authority": passages[n]["authority"], "source": h.cite(),
                                     "text": h.text[:900]} for n, g, h in numbered]}, indent=1)
    try:
        ans = llm.chat_json(SYSTEM, user)
    except (LLMUnavailable, ValueError) as e:
        out = _retrieval_only(numbered)
        out["note"] = f"language model unavailable ({str(e)[:80]})"
        return {**base, **out, "method": "retrieval only"}
    return {**base, **validate(ans.data, passages), "method": f"language model ({ans.source})"}


def validate(data: dict, passages: dict) -> dict:
    """Keep only what the passages support. Pure function, so it is easy to test."""
    valid = set(passages)
    answer = _clean(data.get("answer", ""), valid)
    conditions = [c for c in (_clean(x, valid) for x in data.get("conditions") or []) if c]
    responsible = _clean(data.get("responsible", ""), valid) or "not stated in the passages"
    action = _clean(data.get("recommended_action", ""), valid)
    elsewhere = _clean(data.get("elsewhere", ""), valid)
    verdict = str(data.get("verdict", "")).strip().lower()
    verdict = verdict if verdict in VERDICTS else "not established"
    conf = str(data.get("confidence", "")).strip().lower()
    conf = conf if conf in ("high", "medium", "low") else "medium"

    # The verdict must rest on Indian, operator or standard passages, never on a foreign example alone.
    decisive = {n for n in _cited(" ".join([answer, *conditions, responsible])) if passages[n]["scope"] in DECISIVE_SCOPES}
    note = ""
    if verdict != "not established" and not decisive:
        verdict, conf = "not established", "low"
        note = "No Indian, operator or standard passage supports a conclusion, so the adviser does not conclude."
    used = sorted(_cited(" ".join([answer, *conditions, responsible, action, elsewhere])), key=lambda n: int(n[1:]))
    return {"verdict": verdict, "answer": answer, "conditions": conditions, "responsible": responsible,
            "recommended_action": action, "elsewhere": elsewhere, "confidence": conf, "cited": used,
            "note": note}


def _retrieval_only(numbered: list[tuple[str, str, Hit]]) -> dict:
    national = [n for n, g, _ in numbered if g in ("NATIONAL", "OPERATOR", "STANDARD")][:3]
    return {"verdict": "not established",
            "answer": "The language model is off, so the adviser cannot draw a conclusion. The closest passages are "
                      + " ".join(f"[{n}]" for n in national) + "; a person should read them.",
            "conditions": [], "responsible": "not stated in the passages", "recommended_action": "",
            "elsewhere": "", "confidence": "low", "cited": national, "note": ""}
