# BUILD_LOG.md — FINN build history

Index into the AI build sessions. **Codex writes this file**; the human only adds `HUMAN:` lines.
Purpose: let a reader see the decisions, the routes taken and rejected, and the course corrections without reading every session.

## Rules for the agent
- Append **one entry per task**, at the end of the task, in the same commit as the code.
- Keep it short: one entry ≈ 5–8 lines. No progress narration, no restating the diff line by line.
- Log the **routes**: what you considered, what you picked, and why. Honest failures are as valuable as successes.
- If the human corrected you during the task, log it under `Corrected:` in plain words. Don't soften it.
- Never edit or delete past entries. Fixes to a past entry go in a new entry.
- If nothing notable happened (a pure mechanical task), write a single line: `- [Pn] <task> — routine, no decisions. (<commit>)`

## Entry format
```
### [Pn] <task title> — <YYYY-MM-DD HH:MM>
Changed: <files/modules, 1 line>
Routes: <option A (chosen) vs option B (rejected) — why>
Decisions: <non-obvious choices: thresholds, schemas, model tier, fallbacks>
Corrected: <where the human redirected me or where my first attempt failed, and the fix> | none
Verified: <command + result, e.g. `pytest -q` 14 passed> | NOT verified: <why>
Open: <follow-ups / known gaps> | none
```

---

## Log

### [P0] Initial architecture — 2026-11-13 22:00
Changed: AGENTS.md, PLAN.md, BUILD_LOG.md
Routes: Next.js PWA + FastAPI (chosen) vs single Streamlit app (rejected: not mobile-first, weak product feel); deterministic network graph (chosen) vs LLM graph reasoning (rejected: cost, untestable); no agent framework (chosen) vs LangChain (rejected: unnecessary weight for this pipeline).
Decisions: cheap model for bulk extraction, strong model only for promised-vs-delivered and bull/bear; all LLM calls cached by input hash; choose the portfolio after scanning for real filing events.
Corrected: none
Verified: n/a (docs only)
Open: fill in the planted network stories after Phase 1.
### [P3/P5] Mock workflow and Hyde GLM validation — 2026-11-13 22:24
Changed: fictional Push/Pull/network scenario, request trace, workflow checker/tests, Hyde configuration defaults and README.
Routes: existing OpenAI-compatible HTTP adapter with Hyde endpoint (chosen) vs provider SDK or alternate models (rejected: unnecessary and assessment permits only provided GLM).
Decisions: use https://inference.hyde.tech/v1 with hyde/glm-5.3-flash; contacts selected deterministically; trace exposes excerpts/request without keys or contact profiles; validation uses temporary DB.
Corrected: initial calls wrongly sent the Hyde-issued key to Z.ai and returned 401; the user supplied Hyde invitation instructions, establishing the correct gateway and model alias.
Verified: pytest -q: 21 passed; ruff: passed; live check_workflow.py --live-model: all 5 checks passed; reviewed all four findings against Q1/Q2 excerpts (22% guidance, 20% actual, 2pp shortfall, stated causes/missing Q3 guidance); 1,140 tokens.
Open: live verification covers one synthetic scenario; broader real-document evaluation and planned engine/llm.py/tenant-isolation architecture remain future work. Invitation/key excluded from committed files.
