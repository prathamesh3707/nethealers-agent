## 3D game (Step 4), agent fixes found by playing it, and an LLM provider

### Summary
- **The game (`web/`)**: a 3D Station Road in the browser (Vite + React + TypeScript + React Three Fiber). Place problems by clicking the street, move buses and trucks with ◀◀ ◀ ▶ ▶▶ or the arrow keys, approve or reject the agent's larger changes, and watch every step of the agent live.
  - **Simple / Expert views.** Simple uses plain language and focuses on the main problem; Expert shows every step, timing, probability and log line.
  - **UI tour** (22 steps): spotlights and explains every part of the screen.
  - **Incident demo**: one bus incident told step by step with the real numbers of that run (users hit, signal in dB, detection time, diagnosis, every fix the twin tried, predicted vs measured, with vs without the agent, summary).
  - **Digital twin card**: every fix tried, with its rank, the order it was tried and safety-checked, its score, the twin's prediction, and the safety result; round tabs.
  - **With vs without the agent**: a hidden copy of the street gets the same problems but no agent, so the bottom bar compares them live.
- **Game backend**: crash-safe tick loop, non-blocking WebSocket, parked or driven vehicles, move/leave endpoints, per-step timings, an incident timeline endpoint, a decision log in Postgres, immediate frames while paused, and the built game served by the API.
- **Agent fixes**, all found by playing the game or by testing every problem type end to end:
  - Undo subtracts the change instead of restoring old values, so overlapping fixes survive.
  - Operator-approved fixes are re-checked by the rule-checker before they are applied.
  - Phones that join a blockage incident after a fix (the bus still arriving) are not blamed on the fix.
  - Protected-zone relief is judged against the twin's own "do nothing" load; moves onto the zone's tower keep the strict check.
  - When the AI planner hands over after a fix was kept, that fix is still watched (withdrawn or undone), not abandoned.
  - Handed-over problems are retried with a fresh diagnosis, then closed; stale approval requests are withdrawn.
  - Fixing a misconfigured tower restores its original settings; the agent notices outside setting changes.
  - Tidy-up removes changes the twin predicts are no longer needed; withdrawn fixes are marked inactive.
  - Users plainly worse than their normal are not dismissed as "normal variation".
  - A phone's "normal" rises slowly, so a temporary improvement can't create a false problem later.
- **LLM**: OpenAI added as a provider (default `gpt-4.1-mini`); planner and safety-adviser prompts tuned (`gpt-4o-mini` was far too cautious); providers that fail are rested for 60 s.

### Results
Evaluation report regenerated (`docs/evaluation_report.md`), full agent, degraded user-seconds during + after the problem:

| Scenario | Network alone | Rule fixer | Full agent |
|---|---|---|---|
| Moving bus | 221 + 19 | 76 + 91 | 106 + 19 |
| Wrong beam | 418 | 131 | 30 |
| Twin mismatch | 326 | 121 + 78 | 112 + 11 |
| Hospital-zone conflict | 326 | 82 + 87, 24 breaches | 221 + 0, **0 breaches** |
| Faulty and stale data | 754 | 734 | 559 |

Zero safety breaks for the agent in every scenario.

### Known limits
- The agent cannot fully repair a badly misconfigured tower on its own (3 dB step limit by policy), so it asks the operator.
- After a misconfiguration at Tower A is removed, a few users can stay stranded (3 vs 7 without the agent), because of how the simulated network blocks some handovers.
- The evaluation measures plain-rules mode only; LLM mode was tuned on four scenarios.
- The layout needs a full-size browser window.
- Unused Vite starter files are still tracked (`web/src/assets/`, `web/src/App.css`); `web/public/icons.svg` is untracked. They can be deleted.

### Test plan
- [x] `uv run pytest`: 69 passed, 1 skipped (needs Postgres)
- [x] `uv run python scripts/run_scenarios.py`: report regenerated, no safety breaks
- [x] Every problem type placed, then removed: nothing left open, agent never worse than without it
- [x] UI tour (22 steps) and incident demo run end to end in the browser
- [ ] With `.env` (`LLM_PROVIDERS=openai`, `OPENAI_API_KEY`): start "Agent with language model" and run the quick scenarios
- [ ] `cd web && npm install && npm run build`, then `uv run python scripts/serve.py` and open http://localhost:8010

🤖 Generated with [Claude Code](https://claude.com/claude-code)
