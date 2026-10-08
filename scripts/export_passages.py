"""Export the knowledge base as plain files, ready to ingest elsewhere (e.g. the ITU AI for Good Sandbox).

    uv run python scripts/export_passages.py              # data/kb/export/passages.jsonl + manifest.json
    uv run python scripts/export_passages.py --vectors    # also each passage's 384-number embedding

One JSON line per passage with a stable id (doc:page:chunk), so citations made here still resolve after
re-ingestion. The manifest lists every document with its source link, kind, scope, country and SHA-256.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from nethealers.kb import Library, source_meta  # noqa: E402
from nethealers.kb.library import EMBED_MODEL, MemoryStore  # noqa: E402

OUT = ROOT / "data" / "kb" / "export"


def all_passages(lib: Library) -> list[dict]:
    store = lib.local
    if isinstance(store, MemoryStore):
        return [dict(m, embedding=store.vecs[i].tolist()) for i, m in enumerate(store.meta)]
    rows = store.conn.execute("SELECT id, doc_id, title, kind, page, text, embedding FROM kb_passages "
                              "ORDER BY doc_id, page, id").fetchall()
    return [{"id": r[0], "doc_id": r[1], "title": r[2], "kind": r[3], "page": r[4], "text": r[5],
             "embedding": r[6].to_list()} for r in rows]


def main():
    vectors = "--vectors" in sys.argv
    lib = Library.open()
    if lib.local.count() == 0:
        sys.exit("The library is empty: run scripts/build_library.py first.")
    meta = source_meta()
    OUT.mkdir(parents=True, exist_ok=True)
    passages = all_passages(lib)
    with (OUT / "passages.jsonl").open("w") as f:
        for p in passages:
            m = meta.get(p["doc_id"], {})
            rec = {"id": p["id"], "doc_id": p["doc_id"], "title": p["title"], "kind": p["kind"],
                   "scope": m.get("scope", ""), "country": m.get("country", ""), "publisher": m.get("publisher", ""),
                   "url": m.get("url", ""), "page": p["page"], "text": p["text"]}
            if vectors:
                rec["embedding"] = p["embedding"]
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    docs = lib.documents()
    manifest = {"exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "passages": len(passages), "documents": docs, "chunking": "about 900 characters, 150 overlap, "
                "split on sentence and paragraph boundaries, page numbers kept",
                "embedding_model": EMBED_MODEL if vectors else None}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False))
    print(f"{len(passages)} passages from {sum(1 for d in docs if d['passages'])} documents -> {OUT}")


if __name__ == "__main__":
    main()
