# PLAN.md — FINN build plan

**Deadline:** Sun 15 Nov 2026. **Start:** Fri 13 Nov, 22:00.
**Principle:** protect a working demo first, polish second. Finish, test and commit each phase before starting the next.
**Hero workflows (never cut):** (1) management-change card with a network path, (2) results card QoQ/YoY, (3) promised-vs-delivered research, each with the Network on top.

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done · `[-]` cut

---

## Product point of view

One ranked attention surface, not a dashboard. Three tabs:
- **Today (Push):** a digest of cards sorted by attention score; the window picker defaults to 24h; routine filings collapse into a single "N routine filings" row.
- **Ask (Pull):** command bar → research brief with citations on every claim.
- **People (Network):** paths, expertise search, reconnect nudges.

The Network is **woven in**: every Push card and Pull brief can show a **"Who to call"** chip, and the feed shows **"Reason to reconnect"** nudges.

---

## Phase 0 — Setup (Fri night, ~1h)
- [ ] Decide providers/models per task with the user after workflow validation: benchmark smaller models for classification/extraction/summary and stronger models for reasoning; compare accuracy, latency and token cost. Current Hyde GLM is a baseline, not a project restriction.
- [ ] Create the repo layout from AGENTS.md §4, plus `.env.example`, `requirements.txt`, Next.js app, pytest config
- [ ] `engine/llm.py`: routing wrapper + SQLite `llm_cache` + token/cost log
- [x] CI workflow: lint and backend tests on push/PR for Python 3.11/3.12; manual real-model acceptance with repository secret and saved diagnostics.
- **Done when:** `pytest -q` passes (empty) and `npm run build` succeeds.

## Phase 1 — Check the data sources, then choose the portfolio (Fri night/Sat early, ~2–3h) ★ most important
- [ ] Spike scripts confirm each source responds: yfinance `.NS`, BSE announcements, screener page + doc links
- [ ] Scan the last 60–90 days of filings across ~100 liquid NSE names for: CFO/CEO/MD changes, results, M&A, large capex, litigation
- [ ] Choose **15–20 portfolio stocks** around real events (mixed sectors and sizes) + **3–5 research tickers**
- [ ] Record the picks and the reason for each in `data/mock/portfolio.json`
- **Done when:** at least one real management change, ≥5 results filings and ≥1 material event are in the portfolio window.

## Phase 2 — Data layer + ingestion (Sat morning, ~3h)
- [ ] Schema: `companies, prices, announcements, documents, doc_pages, financials_quarterly, financials_annual, llm_cache`
- [ ] Ingest jobs are safe to re-run (re-runs don't duplicate): prices, announcements, screener tables, document downloads + per-page text
- [ ] NSE→BSE scrip code map
- [ ] Every fetcher saves its raw response to `/data/cache` and can fall back to it
- [ ] Offline fixtures for 2 companies
- **Done when:** `python -m ingest.all --tickers <portfolio>` fills the DB and the tests pass offline.

## Phase 3 — Mock network + graph engine (Sat morning, ~3h, no LLM)
- [ ] `data/mock/investor.json`: the investor's alma maters, past employers, sectors
- [ ] `data/mock/network.json`: ~40 synthetic people with employers (dates), education (years), expertise tags, relationship strength 1–5, last_contacted, and known-to-know edges
- [ ] **Planted stories** (fill in after Phase 1):
  - [ ] the incoming CFO at `<CO>` worked at `<ORG>` alongside the investor's ex-colleague `<X>` (overlap of 2+ years)
  - [ ] contact `<Y>` works at a competitor or supplier of `<CO2>` (which had a material event)
  - [ ] the investor's classmate `<Z>` studied with `<PROMOTER>`
  - [ ] contact `<W>` not spoken to for 9 months; their former employer just reported results → reconnect nudge
- [ ] `engine/network.py`: `resolve_person`, `work_overlap`, `study_overlap`, `paths_to(max_hops=2)` with strength score + explanation, `best_contact_for(company|sector)`, `expertise_map(theme)`, `reconnect_nudges(events)`
- **Done when:** a test exists for each planted story and passes.

## Phase 4 — Push engine (Sat afternoon, ~4–5h)
- [ ] `classify.py`: BSE category + keyword rules → our categories; the cheap LLM only handles what the rules can't decide
- [ ] `score.py`: attention score = filing type weight × materiality × the investor's preferences + network-link boost
- [ ] `alerts.py`: the investor sets thresholds: volume > k× 20d average, |price move| > X%, and which filing types to watch
- [ ] Enrichers:
  - [ ] **Management change:** extract the incoming person → synthetic bio → network overlaps + paths
  - [ ] **Results:** extract Revenue/EBITDA/PBT/PAT from the filing PDF (cheap model, JSON) → QoQ and YoY → **cross-check with screener**, flag mismatches over 2%
  - [ ] **Material event** (M&A/capex/litigation): best contact + "why"
  - [ ] **Other:** one-line summary (cheap model) or the bare filing, by priority
- [ ] API: `GET /digest?from&to`, `GET /alerts`, `PUT /settings/alerts`
- [ ] Pre-compute enrichments at ingest time, not when the investor views them
- **Done when:** the digest for the demo window returns ranked cards with all 3 hero enrichments.

## Phase 5 — Pull engine (Sat evening/night, ~5–6h)
- [x] Run live-model acceptance tests against known synthetic facts: financial accuracy, missing evidence, source isolation, citations, network selection, cache invalidation and document prompt injection; keep response artifacts for review (7 passed).
- [ ] Extend acceptance coverage to real company documents, longer corpora, multiple periods/units and unsupported prose in findings/gaps; review factual support beyond the bounded numeric checks.
- [ ] Works for **any NSE ticker**: fetch screener tables + last 4 concall transcripts + latest annual report (fetched live, then cached)
- [ ] Split documents into chunks by page; simple retrieval (BM25 or small embeddings)
- [ ] Guidance extractor (cheap model, JSON): `{quarter, metric, guided_value_or_range, quote_page}`
- [ ] Promised-vs-delivered **computed in code** against the actual figures
- [ ] Strong model writes the narrative + bull/bear **using only the cited chunks**
- [ ] Sections (in priority order): Business snapshot → Financial snapshot + trajectory → **Promised vs delivered** → Bull/Bear
- [ ] A "People who'd know" panel from the network engine
- [ ] API: `POST /research/{ticker}` (cached; streams progress)
- **Done when:** briefs for the 3–5 research tickers plus one unseen ticker render with citations.

## Phase 6 — Frontend (Sun morning/afternoon, ~6–8h)
Build in this order:
- [ ] Today feed + card components (results card, management-change card, event card, collapsed routine row)
- [ ] Card detail: bio, overlap timeline, path view (You → A → Target)
- [ ] Ask: command bar → research brief with citation chips (tap → doc + page)
- [ ] People: search by company/theme, expertise map, reconnect nudges
- [ ] Alert settings sheet
- [ ] Design pass: one type scale, one accent colour, dense but calm, readable in 2 seconds
- **Done when:** the whole demo works on a real phone.

## Phase 7 — Deploy + make the demo safe (Sun afternoon, ~3h)
- [ ] Deploy the API (Render/Railway) and the web app (Vercel)
- [ ] Seed snapshots for all demo tickers; the frontend falls back to them if the API is cold
- [ ] Keep-warm ping; loading states for live research
- [ ] Run the demo end to end twice on mobile data

## Phase 8 — Writeup + submission (Sun evening, ~2–3h)
- [ ] Architecture diagram (pipelines, DB, LLM routing, cloud)
- [ ] Sections: what I built · key decisions/tradeoffs · data pipelines · security & privacy · LLMs/agents · cloud · what I left out · what's next
- [ ] State clearly that the network profiles are synthetic, and how real profiles would be handled (consent, official APIs, the contact sharing their own profile)
- [ ] Cost table from the `llm.py` token log
- [ ] Export the Codex/Claude sessions → links
- [ ] Email assessment@enam.com, subject: **"IIT Delhi – Founding AI Engineer - 2027"**

---

## Cut list (cut in this order if behind)
1. Annual-report parsing (keep transcripts)
2. Bull/Bear
3. Expertise map
4. People-tab visual polish
5. Alert settings UI (hard-code sensible defaults)

**Never cut:** the hero workflows, deploy, writeup.
