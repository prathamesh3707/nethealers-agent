"""Download the rule documents and build the searchable library.

    docker compose up -d                       # optional: store it in Postgres
    uv run python scripts/build_library.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")  # the database address, if .env doesn't have one

from nethealers.kb import Library  # noqa: E402


def main():
    lib = Library.open()
    print(f"Building the library in {lib.store.name}...")
    counts = lib.build()
    print(f"{sum(counts.values())} passages from {len(counts)} documents.")
    for q in ["Can network changes be made automatically without a person?",
              "rules for processing location data of people",
              "protect the hospital zone"]:
        print(f"\nQ: {q}")
        for h in lib.search(q, k=2):
            print(f"  [{h.score:.2f}] {h.cite()}: {h.text[:160]}...")


if __name__ == "__main__":
    main()
