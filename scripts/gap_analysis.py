"""Run the policy, strategy and standards gap analysis. Writes docs/gap_analysis.md and docs/gap_analysis.json.

    uv run python scripts/build_library.py     # once: the knowledge base
    uv run python scripts/gap_analysis.py      # uses the language model in .env if there is one
    uv run python scripts/gap_analysis.py --offline
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nethealers.kb.gaps import OUT_MD, run  # noqa: E402
from nethealers.llm import LLM  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="retrieval only, no language model")
    args = ap.parse_args()
    llm = None if args.offline else LLM()
    if llm is not None and not llm.ready:
        print("No language model configured (.env): running retrieval only.")
        llm = None
    report = run(llm)
    for t in report["topics"]:
        types = ", ".join(sorted({g["type"] for g in t["gaps"]})) or "none"
        print(f"{t['severity']:6s} {t['title']}: {types} (national coverage {t['national_coverage']:.2f}, "
              f"{len(t['global_examples'])} global, {len(t['regional'])} regional)")
    print(f"\nreport: {OUT_MD}")


if __name__ == "__main__":
    main()
