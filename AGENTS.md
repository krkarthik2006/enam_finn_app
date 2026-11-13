# AGENTS.md — FINN (Financial Investment Agent)

Read this whole file before every task. 
If a task conflicts with this file, stop and say so instead of guessing.
---

## 1. What we are building (one paragraph)

FINN is a **mobile-first** investor copilot with three layers:
- **Push**: tells the investor what changed and why it matters (windowed digest + threshold alerts).
- **Pull**: on-demand research on any NSE ticker, grounded **only** in annual reports and concall transcripts.
- **Network**: the investor's own contacts as an intelligence layer, surfaced *inside* Push and Pull ("who can help me understand this"), and also queryable directly.

Grading criteria: product judgment, creativity, architecture, efficiency. **Not** completeness.
**A demo that doesn't run is the worst outcome.** Thin-but-working beats broad-but-broken.

The full phase plan is in `PLAN.md`. The decision and course-correction history is in `BUILD_LOG.md`, which **you maintain** (see §6).

---

## 2. Agent working rules (Karpathy-style discipline)

These four rules exist because coding agents tend to fail in the same ways: silent assumptions, bloated code, edits beyond scope, and claiming things are done without checking.

### 2.1 Think before coding
- State your assumptions before you write code. If the task is ambiguous, list the possible interpretations and ask. Don't pick one silently.
- If a simpler approach exists than the one requested, say so before you start.
- If you're confused, stop and name what's unclear. Never paper over confusion with plausible-looking code.

### 2.2 Simplicity first
- Write the minimum code that solves the task. No speculative features, no "while I'm here" extras.
- No abstraction for single-use code. No config options nobody asked for. No frameworks we haven't already chosen.
- If you wrote 200 lines and 50 would do, rewrite it before you report.
- Self-check: *Would a senior engineer call this overcomplicated?* If yes, simplify.

### 2.3 Surgical changes
- Touch only the files and lines the task requires. Don't reformat, rename or "improve" adjacent code.
- Match the existing style even if you'd do it differently.
- Clean up only what your own change orphaned (unused imports or functions *you* made dead). Mention any other dead code you notice; don't delete it.
- Every changed line must trace back to the task.

### 2.4 Goal-driven execution
- Turn every task into checkable success criteria, usually a test. "Add X" means writing a test that proves X, then making it pass.
- For multi-step tasks, write a short plan first, with each step paired with how it will be verified.
- Loop until the checks actually pass. **Never report "done" without running the tests and pasting the result.**
- If you can't verify something (no network, missing key), say so explicitly. Don't claim it works.

---

## 3. Project rules (non-negotiable)

### 3.1 Grounding: the Pull side
- Pull outputs (research briefs) may use **only** retrieved chunks from annual reports and concall transcripts, plus structured financial tables from screener.in.
- **Never** use the model's outside knowledge of the company. No news, no broker notes.
- Every claim in a brief carries a citation: `{doc_id, doc_type, period, page}`.
- If the sources don't support a section, the section says "Not found in primary sources." It must never be filled with guesses.
- System prompts for Pull must restate this rule.

### 3.2 Push-side enrichment
- Professional background of people (bio, past employers, education) and network insights are allowed on the Push side.
- Profiles are **synthetic** (`/data/mock/`). Never scrape LinkedIn. Mark synthetic data as such in the UI's About page and in the writeup.

### 3.3 Generalisation
- Nothing may be hard-wired to the demo tickers. Every engine function takes a ticker and works on any NSE symbol where data exists.
- The demo set only decides what is **pre-cached**.

### 3.4 Model routing and cost
FINN is not subject to the separate Hyde assessment's GLM-only restriction. The current
Hyde GLM configuration is a working baseline, not a final model choice. The user will decide
which providers/models handle each task, including smaller models for efficiency, after
workflow validation. The tiers below are provisional; do not switch providers autonomously.

| Step | Model tier | Why |
|---|---|---|
| Filing classification (rule miss only) | cheap (Gemini Flash-Lite / Flash) | bulk, low reasoning |
| One-line filing summaries | cheap | bulk |
| Results number extraction from PDF | cheap, JSON mode | structured extraction; cross-checked in code |
| Guidance extraction per transcript | cheap, JSON mode | structured extraction |
| Promised-vs-delivered narrative, bull/bear | strong (Claude / GPT) | real reasoning, low volume |
| Network graph, overlaps, scoring, thresholds | **no LLM** | deterministic code |

- **Rules first, LLM second.** If a regex or category map can decide, don't call a model.
- **Cache every LLM call** in the `llm_cache` table, keyed by `sha256(model + prompt_version + input)`. Never call twice for the same input.
- Every LLM call goes through `engine/llm.py` (a single wrapper that handles routing, caching, retries and token logging). No direct SDK calls anywhere else.
- Prompts live in `engine/prompts/*.md` with a version string. Change the version when you change a prompt.

### 3.5 Privacy (also a graded writeup topic)
- The network belongs to one investor. Every network table has an `owner_id`, and every query filters by it.
- Store professional facts only (roles, employers, tenure, education, relationship metadata). No personal contact details beyond a name in the mock data.
- Never send network data to an LLM unless the step requires it, and send the minimum fields.
- Never log personal data at INFO level.

### 3.6 Demo safety
- Every external fetch has a timeout, a retry, and a **fallback to the cached snapshot** in `/data/cache/`.
- The frontend must render the demo companies with the backend offline (seeded JSON fallback).
- Loading states are required for any live fetch over 1s.

---

## 4. Stack and layout

- **Backend:** Python 3.11, FastAPI, SQLite in dev (`data/finn.db`), Postgres (Supabase) in prod via SQLAlchemy. `uv` or `pip` + `requirements.txt`.
- **Frontend:** Next.js (App Router) + TypeScript + Tailwind, mobile-first, installable PWA.
- **Scheduled ingestion:** GitHub Actions cron calls the `ingest/` scripts.
- **Deploy:** web on Vercel; API on Render or Railway.

```
/ingest        # fetchers: prices.py, announcements.py, fundamentals.py, documents.py
/engine        # pure logic: classify.py, score.py, alerts.py, enrich/, network.py, research/, llm.py, prompts/
/api           # FastAPI routes only; thin, no business logic
/web           # Next.js app
/data/mock     # synthetic network + investor profile (committed)
/data/cache    # cached raw fetches + demo snapshots (committed for demo tickers)
/tests         # pytest; fixtures in /tests/fixtures (offline)
```

Rules:
- `engine/` never does network I/O directly. It receives data from `ingest/` or the DB, which keeps it testable offline.
- `api/` routes call engine functions and return Pydantic models. Keep the API contract in `api/schemas.py` in sync with `web/lib/types.ts`.

---

## 5. Data sources (plumbing; keep it boring)

| Source | Use | Notes |
|---|---|---|
| yfinance (`TICKER.NS`) | EOD price/volume | 1y history; compute 20d avg volume |
| BSE announcements API | filings | Map NSE symbol → BSE scrip code; NSE API as fallback (needs cookies, often blocked from cloud IPs) |
| screener.in company page | quarterly/annual tables, links to concalls + annual reports | Polite: cache HTML, ≤1 req/sec, set a UA |
| Company PDFs | transcripts, annual reports, results filings | Store PDF + extracted text per page |
| `/data/mock/network.json` | synthetic people, orgs, edges | Investor-owned |

Matching people across sources (entity resolution) goes in `engine/network.py::resolve_person`. It normalises the name (strips honorifics like Mr/Dr/Shri, uses initials), matches on name + org + time window, and returns a confidence score in [0,1]. Below 0.7, the UI says "possible match".

---

## 6. How to do a task

1. Read `AGENTS.md`, the relevant `PLAN.md` phase, and the last 3 entries in `BUILD_LOG.md`.
2. Reply with: your assumptions, your plan (steps + how each step is verified), and the files you'll touch.
3. Write or extend tests and fixtures first (offline).
4. Implement the minimum.
5. Run `pytest -q` (and `npm run build` / `npm run lint` for web). Paste the results.
6. **Append your entry to `BUILD_LOG.md`** using its format: what changed, routes considered (chosen vs rejected, with why), key decisions, any human corrections, verification result, open items. Be honest; log failed first attempts.
7. Summarise to the human in chat: what changed, what's not verified, and any follow-ups.
8. One task = one commit (code + BUILD_LOG entry together), with message format `phaseN: <what>`.

When the human corrects you mid-task ("no, do X instead"), remember it, because it goes in the `Corrected:` line of that task's log entry.

## 7. Never
- Never add a dependency without stating why in your reply.
- Never commit API keys. Keys go in `.env` (git-ignored); `.env.example` lists the variable names.
- Never delete or rewrite `/data/mock` or `/data/cache` unless the task says to.
- Never mark something done that you didn't run.
