# Sandbox day: moving the knowledge base to the ITU AI for Good Sandbox

The knowledge base runs locally today (PostgreSQL with pgvector, or a local file). On the day we get Sandbox
access, we move it there with ITU's reference code, without touching the agent. The safety rules never move:
they stay in `config/policy.yaml` and plain code, whatever happens to the knowledge base.

## Before the day

```bash
uv run python scripts/build_library.py        # 14 documents, 2,960 passages
uv run python scripts/eval_library.py         # baseline retrieval scores: docs/kb_report.md
uv run python scripts/export_passages.py      # data/kb/export/passages.jsonl + manifest.json
```

`passages.jsonl` has one passage per line with a stable id (`doc:page:chunk`), its document, kind (law,
recommendation, guidance, standard, operator), scope (national, operator, standard, global, regional),
country, source link and page. `manifest.json` lists each document with its SHA-256. Add `--vectors` to include
our embeddings if the Sandbox wants them; otherwise it embeds the text itself.

## On the day

1. Ingest one document (the Telecommunications Act) with ITU's reference code. Check that a search returns its
   passages with the same ids and page numbers.
2. Ingest the rest from `passages.jsonl`, keeping the ids and the metadata fields above.
3. Point NetHealers at it, in `.env`:

   ```
   KB_BACKEND=remote
   KB_REMOTE_URL=<the Sandbox search endpoint>
   ```

   The request is a JSON POST `{"query", "k", "doc_ids", "kinds"}`. If the reference code expects something
   else, change `RemoteStore._post` and `RemoteStore._hit` in `src/nethealers/kb/library.py` (about 15 lines).
4. Run `scripts/eval_library.py` again and compare with the local baseline.
5. Keep the Sandbox only if retrieval is at least as good and fast enough for the game. If the Sandbox is
   unreachable at any point, searches fall back to the local index automatically, so the demo keeps working.
