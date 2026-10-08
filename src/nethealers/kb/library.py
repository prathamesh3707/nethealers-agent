"""The searchable document library: rules, recommendations and the operator's own policy.

Documents are downloaded once, split into passages of about 900 characters
(keeping their page numbers), turned into 384-number vectors by a small
local embedding model (all-MiniLM-L6-v2, runs on the laptop's processor),
and stored in Postgres with pgvector. Without Postgres, the same index is
kept in a local file instead.

Passages are evidence for the agents to quote. Nothing in a document can
change what the agent is allowed to do: only config/policy.yaml does that,
and only a person edits it.

This stands in for the ITU AI for Good Sandbox knowledge base until access
is granted; the chunk records (source, page, stable id) are kept simple so
they can be re-ingested there with ITU's reference code.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[3]
RAW = ROOT / "data" / "kb" / "raw"
LOCAL_INDEX = ROOT / "data" / "kb" / "index"
SOURCES = ROOT / "config" / "kb_sources.yaml"
EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 384
CHUNK_CHARS = 900
OVERLAP = 150
BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 Safari/605.1.15",
                   "Accept": "application/pdf,*/*"}


@dataclass
class Passage:
    id: str
    doc_id: str
    title: str
    kind: str
    page: int
    text: str


@dataclass
class Hit(Passage):
    score: float = 0.0

    def cite(self) -> str:
        return f"{self.title}, p. {self.page}" if self.page else self.title


# ---------------------------------------------------------------------- building

def load_sources() -> list[dict]:
    return yaml.safe_load(SOURCES.read_text())


def source_meta() -> dict[str, dict]:
    """doc id -> its entry in config/kb_sources.yaml (title, publisher, kind, scope, country, url)."""
    return {s["id"]: s for s in load_sources()}


AGENT_SCOPES = ["national", "operator", "standard"]  # what the network agent may cite


def fetch(src: dict) -> Path | None:
    """Download a source PDF once (into data/kb/raw). Returns the local path."""
    if "url" not in src:
        return None
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / f"{src['id']}.pdf"
    if not path.exists():
        try:
            req = urllib.request.Request(src["url"], headers=BROWSER_HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
        except Exception:
            # Some government sites send an incomplete certificate chain that Python rejects but the
            # system's own trust store (used by curl) accepts.
            import subprocess

            data = subprocess.run(["curl", "-sL", "--max-time", "60", "-A", BROWSER_HEADERS["User-Agent"],
                                   "-H", "Accept: application/pdf,*/*", src["url"]],
                                  capture_output=True, check=True).stdout
        if not data.startswith(b"%PDF"):
            raise RuntimeError(f"{src['id']}: the server didn't return a PDF")
        path.write_bytes(data)
    return path


def pages_of(src: dict) -> list[tuple[int, str, str]]:
    """(page number, text, key) for a source: PDF pages, or whole local files (page 0, keyed by file name)."""
    if "files" in src:
        return [(0, (ROOT / f).read_text(), Path(f).stem) for f in src["files"]]
    from pypdf import PdfReader

    reader = PdfReader(str(fetch(src)))
    out = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{2,}", "\n\n", text).strip()
        if len(text) > 40:
            out.append((i, text, str(i)))
    return out


def split(text: str, size: int = CHUNK_CHARS, overlap: int = OVERLAP) -> list[str]:
    """Split on paragraph and sentence boundaries into pieces of about `size` characters."""
    parts = re.split(r"(?<=[.;:])\s+|\n\n", text)
    chunks, cur = [], ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(cur) + len(p) + 1 > size and cur:
            chunks.append(cur)
            cur = cur[-overlap:] + " " + p
        else:
            cur = (cur + " " + p).strip()
    if cur:
        chunks.append(cur)
    return chunks


def passages_of(src: dict) -> list[Passage]:
    out = []
    for page, text, key in pages_of(src):
        for n, chunk in enumerate(split(text)):
            out.append(Passage(f"{src['id']}:{key}:{n}", src["id"], src["title"], src["kind"], page, chunk))
    return out


_EMBEDDER = None


def embed(texts: list[str]) -> np.ndarray:
    global _EMBEDDER
    if _EMBEDDER is None:
        from sentence_transformers import SentenceTransformer

        _EMBEDDER = SentenceTransformer(EMBED_MODEL, device="cpu")
    return np.asarray(_EMBEDDER.encode(texts, batch_size=32, normalize_embeddings=True, show_progress_bar=False),
                      dtype=np.float32)


# ---------------------------------------------------------------------- storage

class MemoryStore:
    """The index in a local file: used when Postgres isn't running."""

    def __init__(self, path: Path = LOCAL_INDEX):
        self.path = path
        self.meta: list[dict] = []
        self.vecs = np.zeros((0, DIM), dtype=np.float32)
        if (path / "vectors.npy").exists():
            self.vecs = np.load(path / "vectors.npy")
            self.meta = json.loads((path / "passages.json").read_text())

    name = "local file"

    def replace_doc(self, doc_id: str, passages: list[Passage], vecs: np.ndarray) -> None:
        keep = [i for i, m in enumerate(self.meta) if m["doc_id"] != doc_id]
        self.meta = [self.meta[i] for i in keep] + [p.__dict__ for p in passages]
        self.vecs = np.vstack([self.vecs[keep], vecs]) if len(keep) else vecs
        self.path.mkdir(parents=True, exist_ok=True)
        np.save(self.path / "vectors.npy", self.vecs)
        (self.path / "passages.json").write_text(json.dumps(self.meta))

    def search(self, vec: np.ndarray, k: int, kinds: list[str] | None, docs: list[str] | None = None) -> list[Hit]:
        if not len(self.meta):
            return []
        scores = self.vecs @ vec
        order = np.argsort(-scores)
        out = []
        for i in order:
            m = self.meta[i]
            if kinds and m["kind"] not in kinds:
                continue
            if docs is not None and m["doc_id"] not in docs:
                continue
            out.append(Hit(**m, score=float(scores[i])))
            if len(out) == k:
                break
        return out

    def count(self) -> int:
        return len(self.meta)

    def get(self, ids: list[str]) -> list[Passage]:
        want = set(ids)
        return [Passage(**m) for m in self.meta if m["id"] in want]


class PgStore:
    """The index in Postgres with pgvector."""

    name = "Postgres"

    def __init__(self, url: str):
        import psycopg
        from pgvector.psycopg import register_vector

        self.conn = psycopg.connect(url, autocommit=True, connect_timeout=3)
        self.conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        register_vector(self.conn)
        self.conn.execute(f"""
            CREATE TABLE IF NOT EXISTS kb_passages (
                id text PRIMARY KEY, doc_id text NOT NULL, title text NOT NULL, kind text NOT NULL,
                page int NOT NULL, text text NOT NULL, embedding vector({DIM}) NOT NULL)""")

    def replace_doc(self, doc_id: str, passages: list[Passage], vecs: np.ndarray) -> None:
        with self.conn.transaction():
            self.conn.execute("DELETE FROM kb_passages WHERE doc_id = %s", (doc_id,))
            with self.conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO kb_passages (id, doc_id, title, kind, page, text, embedding) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    [(p.id, p.doc_id, p.title, p.kind, p.page, p.text, v) for p, v in zip(passages, vecs)])

    def search(self, vec: np.ndarray, k: int, kinds: list[str] | None, docs: list[str] | None = None) -> list[Hit]:
        sql = "SELECT id, doc_id, title, kind, page, text, 1 - (embedding <=> %s) FROM kb_passages"
        args: list = [vec]
        where = []
        if kinds:
            where.append("kind = ANY(%s)")
            args.append(kinds)
        if docs is not None:
            where.append("doc_id = ANY(%s)")
            args.append(list(docs))
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY embedding <=> %s LIMIT %s"
        args += [vec, k]
        rows = self.conn.execute(sql, args).fetchall()
        return [Hit(*r[:6], score=float(r[6])) for r in rows]

    def count(self) -> int:
        return self.conn.execute("SELECT count(*) FROM kb_passages").fetchone()[0]

    def get(self, ids: list[str]) -> list[Passage]:
        rows = self.conn.execute("SELECT id, doc_id, title, kind, page, text FROM kb_passages WHERE id = ANY(%s)",
                                 (list(ids),)).fetchall()
        return [Passage(*r) for r in rows]


class RemoteStore:
    """Search through a remote knowledge base (e.g. the ITU AI for Good Sandbox), keeping the local index as a
    fallback. Switch on with KB_BACKEND=remote and KB_REMOTE_URL=...; anything that fails falls back to local.

    The request is a JSON POST {"query", "k", "doc_ids", "kinds"}; the reply may be a list or {"results": [...]},
    each item with "id", "text", "score" and the passage fields (doc_id, title, kind, page) either at the top level
    or under "metadata". Adapt `_post` and `_hit` on the day if the Sandbox's reference code differs.
    """

    name = "remote knowledge base"
    wants_text = True

    def __init__(self, url: str, fallback, timeout: float = 15.0):
        self.url, self.fallback, self.timeout = url, fallback, timeout
        self.last_error: str | None = None

    def _post(self, body: dict):
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read())

    @staticmethod
    def _hit(item: dict) -> Hit:
        m = {**item.get("metadata", {}), **{k: v for k, v in item.items() if k != "metadata"}}
        return Hit(str(m["id"]), str(m.get("doc_id", "")), str(m.get("title", m.get("doc_id", ""))),
                   str(m.get("kind", "")), int(m.get("page", 0) or 0), str(m["text"]), float(m.get("score", 0.0)))

    def search_text(self, query: str, vec_of, k: int, kinds, docs) -> list[Hit]:
        try:
            out = self._post({"query": query, "k": k, "doc_ids": docs, "kinds": kinds})
            items = out.get("results", []) if isinstance(out, dict) else out
            self.last_error = None
            return [self._hit(i) for i in items][:k]
        except Exception as e:  # unreachable, or a reply we can't read: keep working on the local index
            self.last_error = str(e)[:200]
            return self.fallback.search(vec_of(query), k, kinds, docs)

    def count(self) -> int:
        return self.fallback.count()

    def get(self, ids: list[str]) -> list[Passage]:
        return self.fallback.get(ids)


class Library:
    """Search the documents: `Library.open().search("can the agent change tower power on its own?")`."""

    def __init__(self, store):
        self.store = store

    @classmethod
    def open(cls, prefer_postgres: bool = True) -> "Library":
        url = os.environ.get("DATABASE_URL")
        local = None
        if prefer_postgres and url:
            try:
                local = PgStore(url)
            except Exception:
                pass
        local = local or MemoryStore()
        remote = os.environ.get("KB_REMOTE_URL")
        if os.environ.get("KB_BACKEND", "local") == "remote" and remote:
            return cls(RemoteStore(remote, local))
        return cls(local)

    @property
    def local(self):
        """The index on this machine (the remote store's fallback, when a remote one is in use)."""
        return getattr(self.store, "fallback", self.store)

    def build(self, sources: list[dict] | None = None, log=print) -> dict:
        counts = {}
        for src in sources or load_sources():
            try:
                passages = passages_of(src)
            except Exception as e:
                log(f"  skipped {src['id']}: {e}")
                continue
            vecs = embed([p.text for p in passages])
            self.local.replace_doc(src["id"], passages, vecs)
            counts[src["id"]] = len(passages)
            log(f"  {src['id']}: {len(passages)} passages")
        return counts

    def search(self, query: str, k: int = 4, kinds: list[str] | None = None, scopes: list[str] | None = None,
               docs: list[str] | None = None) -> list[Hit]:
        """Best-matching passages. `scopes` (national, operator, standard, global, regional) and `docs` narrow it."""
        if self.store.count() == 0:
            return []
        if scopes is not None:
            in_scope = [d for d, m in source_meta().items() if m.get("scope", "national") in scopes]
            docs = in_scope if docs is None else [d for d in docs if d in in_scope]
        if getattr(self.store, "wants_text", False):
            return self.store.search_text(query, lambda q: embed([q])[0], k, kinds, docs)
        return self.store.search(embed([query])[0], k, kinds, docs)

    def get(self, ids: list[str]) -> dict[str, Passage]:
        """Passages by their stable id (doc:page:chunk), for citations pinned in config files."""
        return {p.id: p for p in self.store.get(ids)}

    def documents(self) -> list[dict]:
        """Each source with how many passages of it are in the index."""
        counts: dict[str, int] = {}
        if isinstance(self.local, MemoryStore):
            for m in self.local.meta:
                counts[m["doc_id"]] = counts.get(m["doc_id"], 0) + 1
        else:
            for doc_id, n in self.local.conn.execute("SELECT doc_id, count(*) FROM kb_passages GROUP BY doc_id"):
                counts[doc_id] = n
        import hashlib

        def sha(d: str) -> str:
            f = RAW / f"{d}.pdf"
            return hashlib.sha256(f.read_bytes()).hexdigest() if f.exists() else ""

        return [{**{k: v for k, v in m.items() if k != "files"}, "passages": counts.get(d, 0), "sha256": sha(d)}
                for d, m in source_meta().items()]
