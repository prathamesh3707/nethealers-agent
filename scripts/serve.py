"""Start the game backend on http://localhost:8010 (API docs at /docs).

    uv run python scripts/serve.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    uvicorn.run("nethealers.api.app:app", host="127.0.0.1", port=port, app_dir=str(ROOT / "src"))
