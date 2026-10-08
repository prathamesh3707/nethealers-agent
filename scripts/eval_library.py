"""How well does the knowledge base find the right document? Writes docs/kb_report.md.

    uv run python scripts/eval_library.py

For each question in config/kb_eval.yaml: is a passage from an expected document among the top k
results (recall@k), and how high is the first one (mean reciprocal rank)?
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from nethealers.kb import Library, source_meta  # noqa: E402

KS = (1, 3, 5)


def main():
    lib = Library.open()
    if lib.store.count() == 0:
        sys.exit("The library is empty: run scripts/build_library.py first.")
    cases = yaml.safe_load((ROOT / "config" / "kb_eval.yaml").read_text())
    meta = source_meta()
    rows, hits_at, rr, scoped_at3 = [], {k: 0 for k in KS}, 0.0, 0
    for c in cases:
        # how the agents search: within the scope of the expected document (e.g. host-country law only)
        scope = meta[c["docs"][0]].get("scope", "national")
        scoped = lib.search(c["q"], k=3, scopes=[scope])
        scoped_at3 += any(h.doc_id in c["docs"] for h in scoped)
        res = lib.search(c["q"], k=max(KS))
        ranks = [i + 1 for i, h in enumerate(res) if h.doc_id in c["docs"]]
        first = ranks[0] if ranks else None
        for k in KS:
            hits_at[k] += bool(first and first <= k)
        rr += 1 / first if first else 0.0
        top = res[0] if res else None
        rows.append((c["q"], ", ".join(c["docs"]), first, f"{top.doc_id} p.{top.page}" if top else "-"))
    n = len(cases)
    docs = lib.documents()
    lines = [
        "# Knowledge base report",
        "",
        f"Store: {lib.store.name}. {sum(d['passages'] for d in docs)} passages from "
        f"{sum(1 for d in docs if d['passages'])} of {len(docs)} documents.",
        "",
        "## Documents",
        "",
        "| Document | Scope | Country | Kind | Passages | SHA-256 of the downloaded file |",
        "|---|---|---|---|---|---|",
        *[f"| [{d['title']}]({d.get('url', '')}) | {d.get('scope', '')} | {d.get('country', '')} | {d['kind']} | "
          f"{d['passages']} | `{d['sha256'][:16]}…` |" for d in docs],
        "",
        "Files are downloaded once from the links above into data/kb/raw/. The Gazette of India serves an incomplete "
        "certificate chain, so the Telecommunications Act was fetched without certificate verification; its checksum "
        "is recorded here so the copy can be compared with the official one.",
        "",
        "## Retrieval test",
        "",
        f"{n} hand-written questions (config/kb_eval.yaml), each with the document that should answer it, searched "
        "over the whole knowledge base.",
        "",
        "| Metric | Value |",
        "|---|---|",
        *[f"| Recall@{k} (right document in the top {k}) | {hits_at[k] / n:.0%} ({hits_at[k]}/{n}) |" for k in KS],
        f"| Mean reciprocal rank | {rr / n:.2f} |",
        f"| Recall@3 within the document's scope (how the agents search) | {scoped_at3 / n:.0%} ({scoped_at3}/{n}) |",
        "",
        "| Question | Expected | Rank of first right passage | Top result |",
        "|---|---|---|---|",
        *[f"| {q} | {d} | {r if r else 'not in top 5'} | {t} |" for q, d, r, t in rows],
        "",
    ]
    out = ROOT / "docs" / "kb_report.md"
    out.write_text("\n".join(lines))
    import json

    (ROOT / "docs" / "kb_eval.json").write_text(json.dumps({
        "questions": n, "recall_at": {str(k): hits_at[k] / n for k in KS}, "mrr": rr / n,
        "scoped_recall_at_3": scoped_at3 / n,
        "rows": [{"q": q, "expected": d, "rank": r, "top": t} for q, d, r, t in rows]}, indent=1))
    print("\n".join(lines[-(n + 9):]))
    print(f"\nreport: {out}")


if __name__ == "__main__":
    main()
