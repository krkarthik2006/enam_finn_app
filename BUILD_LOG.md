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

### [P5] Real-model acceptance tests and deferred model routing — 2026-11-13 22:31
Changed: AGENTS.md/PLAN.md model policy and checklist, live acceptance/oracle tests, strict research JSON Schema contract (cache prompt version 3), README and pytest marker.
Routes: real-provider acceptance tests with known synthetic ground truth plus offline backend/oracle tests (chosen); mocked success alone or an uncalibrated LLM judge (rejected: cannot establish real integration or numeric correctness).
Decisions: provider/model selection per task remains for the user, including smaller models for efficiency; keep working Hyde configuration meanwhile; live tests save fixture/request/response artifacts, without credentials.
Corrected: user clarified GLM-only rule belongs to another project. First live run: 6 failed/1 passed, exposing extra quiz fields; prompt-only fix still failed 4 cases. Strict JSON Schema fixed output shape. Fixed overly strict test assumptions about historical numbers and guidance restated in Q2; oracle tests now reject wrong facts, units, direction and citations.
Verified: pytest -q: 31 passed/7 live cases skipped by default; explicit real-provider suite: 7 passed (24.20s); ruff and git diff --check passed. Reviewed saved findings for two misses, one beat, missing forecasts, source replacement and ignored document injection.
Open: real-company/long-corpus evaluation and broader semantic review remain pending; numerical acceptance checks do not prove every free-text sentence true. Model allocation and efficiency benchmarks remain unchecked in PLAN.md.

### [P0] GitHub Actions test automation — 2026-11-13 22:35
Changed: .github/workflows/tests.yml, README.md and PLAN.md.
Routes: backend lint/tests on push and PR plus explicit manual live tests (chosen) vs paid model calls on every change (rejected: unnecessary usage and nondeterminism).
Decisions: Python 3.11/3.12 matrix, locked dependencies, SHA-pinned actions, read-only workflow token, model key confined to the live step; upload XML and fictional observations on failures, exclude databases/env files.
Corrected: automatic approval review rejected exporting the existing key to a repository secret without explicit credential-transfer approval; requested approval separately and continued unaffected CI work.
Verified: local pytest -m "not live": 31 passed/7 deselected; ruff passed; actionlint v1.7.12 passed; remote execution to be inspected after this commit is pushed.
Open: hosted live execution requires the repository Actions secret FINN_GLM_API_KEY; upload pending explicit user approval (or user can add it directly).

### [P0] Hosted CI execution result — 2026-11-13 22:36
Changed: PLAN.md follow-up for GitHub account lock.
Routes: inspected job/check annotations after jobs failed before startup; no code/test workaround can resolve an account billing lock.
Decisions: retain the locally validated workflow; do not change account billing or transfer the key without explicit approval.
Corrected: hosted run could not start despite valid workflow syntax; GitHub annotation: "The job was not started because your account is locked due to a billing issue."
Verified: pushed commit 1b8ca6b; https://github.com/krkarthik2006/enam_finn_app/actions/runs/43469299535 failed at runner startup on both Python versions, with no test steps executed; live job skipped as designed for push.
Open: user must resolve the GitHub account lock, then rerun; FINN_GLM_API_KEY repository secret awaits explicit transfer approval or user setup.
