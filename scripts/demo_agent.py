"""Watch the agent handle the Station Road bus, step by step, in plain language.

    uv run python scripts/demo_agent.py                 # the hospital-zone conflict
    uv run python scripts/demo_agent.py --scenario 3_wrong_beam
    uv run python scripts/demo_agent.py --offline       # skip the language model even if a key is set

Uses the language-model roles when a key is in .env, otherwise plain rules.
Logs every step to Postgres when the database is running (docker compose up -d).
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")
load_dotenv(ROOT / ".env.example")

from nethealers.agent import Agent, EventLog, PgDecisionLog, Policy, Roles, SimulatedOperator  # noqa: E402
from nethealers.diagnosis import Diagnoser  # noqa: E402
from nethealers.eval.scenarios import LENGTH, SCENARIOS  # noqa: E402

ICONS = {"detect": "!", "diagnose": "?", "rehearse": "~", "check": "#", "plan": ">", "review": "=",
         "act": "*", "verify": "+", "undo": "-", "escalate": "^", "approve": "v", "withdraw": "<",
         "resolve": ".", "note": " "}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="5_conflict", choices=[s.key for s in SCENARIOS])
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    sc = next(s for s in SCENARIOS if s.key == args.scenario)
    script = sc.build(args.seed)
    w = script.world
    roles = Roles(llm=None, library=Roles.default().library) if args.offline else Roles.default()
    sinks = []
    run_id = f"demo-{args.scenario}-{int(time.time())}"
    try:
        sinks.append(PgDecisionLog(os.environ["DATABASE_URL"], run_id, sc.title))
    except Exception:
        pass
    agent = Agent(w, diagnoser=Diagnoser.load(), policy=Policy.load(), roles=roles,
                  operator=SimulatedOperator(delay=5), log=EventLog(sinks=sinks))
    print(f"{sc.title} on {w.name}. Language model: "
          f"{', '.join(roles.llm.ready) if roles.live else 'off (plain rules)'}. "
          f"Library: {'on' if roles.library else 'off'}. Decision log: {'Postgres ' + run_id if sinks else 'memory'}.\n")
    for _ in range(LENGTH):
        for fn in script.events.get(w.tick + 1, []):
            fn(w)
        w.step()
        for e in agent.on_tick():
            print(f"{e.tick:3d}s {ICONS.get(e.stage, ' ')} {e.agent:9s} {e.text}")
    if roles.live:
        llm = roles.llm
        print(f"\nLanguage model: {llm.calls} calls, {llm.tokens_in} tokens in, {llm.tokens_out} out.")


if __name__ == "__main__":
    main()
