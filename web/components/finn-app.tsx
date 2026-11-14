"use client";

import {useEffect, useMemo, useRef, useState} from "react";
import {Activity, ArrowDownRight, ArrowRight, ArrowUpRight, BookOpen, Check, ChevronDown, ChevronRight, CircleHelp, Clock3, ExternalLink, FileText, Filter, GitBranch, Layers3, LoaderCircle, MessageSquare, Network, RefreshCw, Search, Settings2, ShieldCheck, Sparkles, Users, WifiOff, X} from "lucide-react";
import Link from "next/link";
import {api, research} from "@/lib/api";
import type {Brief, Citation, Company, Digest, FeedItem, Financial, Mode, Path, Person, Settings, Snapshot} from "@/lib/types";

const DEFAULT_QUESTION = "Explain the business, financial trajectory, management guidance delivery, positives and risks.";
const number = (value: number | null | undefined, digits = 0) => value == null ? "—" : value.toLocaleString("en-IN", {maximumFractionDigits: digits});
const clean = (value: string) => value.replace(/\s*\(fictional\)/gi, "").replace(/^SYNTHETIC(?: REVIEW)?[: ]*/i, "");
const label = (value: string) => value.replaceAll("_", " ");
const personName = (p: Person) => clean(p.name);
const initials = (name: string) => clean(name).split(" ").slice(0, 2).map(p => p[0]).join("");
const dateText = (date?: string | null) => date ? new Date(date).toLocaleDateString("en-IN", {day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata"}) : "Publication date unavailable";
type Tab = "today" | "ask" | "people";
type Detail = {kind: "event"; item: FeedItem} | {kind: "person"; person: Person} | {kind: "source"; source: Citation} | {kind: "settings"} | {kind: "about"};

function Dialog({title, onClose, children, wide = false}: {title: string; onClose: () => void; children: React.ReactNode; wide?: boolean}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {ref.current?.showModal();}, []);
  return <dialog ref={ref} className={`dialog ${wide ? "wide" : ""}`} onCancel={onClose} onClick={event => {if (event.target === event.currentTarget) onClose();}}>
    <div className="dialog-head"><h2>{title}</h2><button className="icon-button" aria-label="Close dialog" onClick={onClose}><X size={20}/></button></div>
    <div className="dialog-body">{children}</div>
  </dialog>;
}

function Avatar({person, small = false}: {person: {name: string}; small?: boolean}) {
  return <span className={`avatar ${small ? "small" : ""}`} aria-hidden="true">{initials(person.name)}</span>;
}

function FinancialTable({records}: {records: Financial[]}) {
  const rows = records.filter(r => r.frequency === "quarterly" && r.basis === "consolidated").slice(0, 5);
  const display = rows.length ? rows : records.slice(0, 5);
  return <div className="table-scroll"><table className="financial-table"><caption>Financial observations · INR {display[0]?.unit || "crore"} · {display[0]?.basis || "basis unavailable"}</caption><thead><tr><th>Period ended</th><th>Revenue</th><th>EBITDA</th><th>PBT</th><th>PAT</th></tr></thead><tbody>{display.map((r, i) => <tr key={`${r.period_end}-${r.source_type}-${i}`}><th>{dateText(r.period_end)}</th>{["revenue", "ebitda", "pbt", "pat"].map(metric => <td key={metric}>{number(r.metrics[metric], 1)}</td>)}</tr>)}</tbody></table></div>;
}

function GuidanceChart({brief}: {brief: Brief}) {
  const rows = brief.guidance.filter(r => r.metric === "ebitda_margin" && r.actual != null).slice(-4);
  if (!rows.length) return <p className="empty-note">Comparable numerical guidance and delivered outcomes weren’t found in the available sources.</p>;
  const values = rows.flatMap(r => [r.guided_low, r.guided_high, r.actual as number]);
  const low = Math.min(...values) - 1, high = Math.max(...values) + 1;
  const x = (i: number) => rows.length === 1 ? 280 : 55 + i * 450 / (rows.length - 1);
  const y = (value: number) => 170 - (value - low) * 125 / (high - low);
  return <div className="guidance-chart"><div className="chart-legend"><span><i className="dot dashed"/>Guided</span><span><i className="dot"/>Delivered</span><span className="muted">EBITDA margin</span></div>
    <svg viewBox="0 0 560 220" role="img" aria-label="Guided versus delivered EBITDA margin by quarter">
      {[low, (low + high) / 2, high].map(v => <g key={v}><line x1="44" x2="520" y1={y(v)} y2={y(v)} stroke="#e7ebe5"/><text x="5" y={y(v) + 4} fill="#869087" fontSize="11">{number(v, 1)}%</text></g>)}
      <polyline points={rows.map((r, i) => `${x(i)},${y(r.guided_low)}`).join(" ")} fill="none" stroke="#9ba99f" strokeWidth="2" strokeDasharray="5 5"/>
      <polyline points={rows.map((r, i) => `${x(i)},${y(r.actual as number)}`).join(" ")} fill="none" stroke="#2e6a50" strokeWidth="3"/>
      {rows.map((r, i) => <g key={r.period}><circle cx={x(i)} cy={y(r.actual as number)} r="5" fill="#2e6a50" stroke="white" strokeWidth="2"/><text x={x(i)} y={y(r.actual as number) + 23} textAnchor="middle" fontSize="12" fill="#234735">{r.actual}%</text><text x={x(i)} y="210" textAnchor="middle" fill="#6c776e" fontSize="11">{r.period}</text></g>)}
    </svg></div>;
}

export default function FinnApp() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [workspace, setWorkspace] = useState<Snapshot | null>(null);
  const [tab, setTab] = useState<Tab>("today");
  const [mode, setMode] = useState<Mode>("demo");
  const [connected, setConnected] = useState(false);
  const [windowDays, setWindowDays] = useState(1);
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [ticker, setTicker] = useState("MOCKIT");
  const [question, setQuestion] = useState("");
  const [brief, setBrief] = useState<Brief | null>(null);
  const [progress, setProgress] = useState("");
  const [asking, setAsking] = useState(false);
  const [peopleQuery, setPeopleQuery] = useState("");
  const [showRoutine, setShowRoutine] = useState(false);
  const [path, setPath] = useState<Path[]>([]);
  const requestRef = useRef<AbortController | null>(null);

  async function loadBackend(nextMode: Mode, days: number, saved: Snapshot) {
    setLoading(true);
    try {
      const since = new Date(Date.now() - days * 86400000).toISOString();
      const [portfolio, digest, contacts, investor, settings, nudges] = await Promise.all([
        api<{companies: Company[]}>("portfolio"), api<Digest>(`digest?mode=${nextMode}&since=${since}&include_routine=true`),
        api<{contacts: Person[]}>("network"), api<Person>("network/investor"), api<Settings>("alerts/settings"),
        api<{nudges: Snapshot["nudges"]}>(`network/reconnect?mode=${nextMode}`)
      ]);
      setWorkspace({...saved, portfolio: portfolio.companies, digest, contacts: contacts.contacts, investor, settings, nudges: nudges.nudges});
      setConnected(true);
    } catch {
      setConnected(false);
      setWorkspace(nextMode === "demo" ? saved : {...saved, digest: {...saved.digest, mode: "live", items: [], routine: [], routine_count: 0}});
      if (nextMode === "live") setNotice("Connect the backend to view real data. The demo is still available.");
    } finally { setLoading(false); }
  }

  useEffect(() => {
    let mounted = true;
    fetch("/demo.json").then(r => {if (!r.ok) throw new Error("Demo snapshot is missing"); return r.json();}).then((saved: Snapshot) => {
      if (!mounted) return;
      try {const local = localStorage.getItem("finn-demo-alerts"); if (local) saved.settings = JSON.parse(local);} catch {}
      setSnapshot(saved); setWorkspace(saved); setBrief(saved.briefs[saved.scenario.workflow.ticker]); setTicker(saved.scenario.workflow.ticker);
      void loadBackend("demo", 1, saved);
    }).catch(() => setNotice("The demo could not load. Please reload after starting the review app."));
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    return () => {mounted = false; requestRef.current?.abort();};
  }, []);

  useEffect(() => {if (notice) {const timer = setTimeout(() => setNotice(""), 6500); return () => clearTimeout(timer);}}, [notice]);

  const people = useMemo(() => workspace?.contacts || [], [workspace]);
  const filteredPeople = useMemo(() => people.filter(p => [p.name, ...p.expertise, ...p.roles.flatMap(r => [r.company, r.title, r.ticker || ""]), ...(p.related_companies || []).map(r => r.ticker)].join(" ").toLowerCase().includes(peopleQuery.toLowerCase())), [people, peopleQuery]);

  async function ask(symbol = ticker, prompt = question) {
    requestRef.current?.abort();
    const control = new AbortController(); requestRef.current = control;
    const normalized = symbol.trim().toUpperCase();
    setTicker(normalized); setTab("ask"); setAsking(true); setProgress("Looking through primary sources"); setBrief(null);
    if (!connected) {
      const saved = mode === "demo" ? snapshot?.briefs[normalized] : null;
      if (saved) {setBrief(saved); setNotice("Showing the saved overview, rather than a new answer to your question; the backend is offline.");}
      else setNotice("This company needs the connected backend to gather sources. Try a saved demo company.");
      setAsking(false); return;
    }
    try {setBrief(await research(normalized, {question: prompt.trim() || DEFAULT_QUESTION, mode, prepare_sources: true}, setProgress, control.signal));}
    catch (error) {if (!control.signal.aborted) setNotice(error instanceof Error ? error.message : "Research could not be completed.");}
    finally {if (!control.signal.aborted) setAsking(false);}
  }

  async function openPerson(person: Person) {
    setPath(snapshot?.paths[person.id] || []); setDetail({kind: "person", person});
    if (connected) try {setPath((await api<{paths: Path[]}>(`network/paths?person_id=${encodeURIComponent(person.id)}`)).paths);} catch {setPath([]);}
  }

  async function refresh() {
    if (!snapshot) return;
    if (mode === "live" && connected && workspace) {
      setLoading(true); setNotice("Checking real market and filing sources…");
      try {
        const tickers = workspace.portfolio.map(c => c.ticker).filter(t => t !== snapshot.scenario.workflow.ticker);
        const queued = await api<{id: string}>("refresh", {method: "POST", body: JSON.stringify({tickers, days: 7, fundamentals: true})});
        for (let i = 0; i < 90; i++) {
          const run = await api<{status: string}>(`refresh/${queued.id}`);
          if (!["queued", "running"].includes(run.status)) {setNotice(run.status === "completed" ? "Sources refreshed." : "Some sources were unavailable. Saved data and source gaps remain visible."); break;}
          await new Promise(resolve => setTimeout(resolve, 1000));
        }
      } catch (error) {setNotice(error instanceof Error ? error.message : "Refresh failed.");}
    }
    await loadBackend(mode, windowDays, snapshot);
  }

  const companyName = (symbol: string) => workspace?.portfolio.find(c => c.ticker === symbol)?.name || ({MOCKIT: "Mock IT Services", INFY: "Infosys", TITAN: "Titan", CDSL: "CDSL"}[symbol] || symbol);
  const showPersonId = (id: string) => {const person = people.find(p => p.id === id); if (person) void openPerson(person);};
  const nav = [{id: "today" as Tab, label: "Today", icon: Layers3}, {id: "ask" as Tab, label: "Ask FINN", icon: MessageSquare}, {id: "people" as Tab, label: "People", icon: Users}];

  function citations(ids: string[]) {
    return <span className="citation-chips">{ids.map(id => {const source = brief?.sources.find(s => s.citation_id === id); return source ? <button key={id} title={source.title} onClick={() => setDetail({kind: "source", source})}><FileText size={11}/>{(brief?.sources.findIndex(s => s.citation_id === id) ?? 0) + 1}</button> : null;})}</span>;
  }

  if (!workspace || !snapshot) return <main className="boot"><span className="brand-word">finn<span>✳</span></span><LoaderCircle className="spin"/><p>{notice || "Preparing your workspace…"}</p></main>;
  const {digest} = workspace;
  const material = digest.items.filter(i => i.type === "announcement");
  const latestComparison = brief?.guidance.filter(g => g.metric === "ebitda_margin" && g.unit === "percent" && g.actual != null).at(-1);

  return <div className="app-shell">
    <aside className="sidebar"><Link className="brand-word" href="/" aria-label="FINN home">finn<span>✳</span></Link><p className="brand-caption">A clearer investment picture.</p><div className="nav-caption">YOUR WORKSPACE</div><nav aria-label="Main navigation">{nav.map(n => <button key={n.id} className={tab === n.id ? "active" : ""} onClick={() => setTab(n.id)} aria-current={tab === n.id ? "page" : undefined}><n.icon size={19}/>{n.label}{n.id === "today" && <span className="nav-count">{digest.items.length}</span>}</button>)}</nav>
      <div className="sidebar-note"><div className="network-symbol"><Network size={26}/></div><h3>Your network is your edge.</h3><p>The right context. From the people you already know.</p><button onClick={() => setTab("people")}>Explore your people <ArrowRight size={14}/></button></div>
      <div className="sidebar-bottom"><button onClick={() => setDetail({kind: "settings"})}><Settings2 size={17}/>Alert preferences</button><button onClick={() => setDetail({kind: "about"})}><CircleHelp size={17}/>About this workspace</button><div className="investor"><span className="avatar">Y</span><div><strong>Your workspace</strong><small>Personal investor</small></div><span className="online-dot"/></div></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div className="mobile-brand brand-word">finn<span>✳</span></div><span className="breadcrumb">Workspace <ChevronRight size={13}/><strong>{nav.find(n => n.id === tab)?.label}</strong></span><div className="top-actions"><span className={`connection ${connected ? "" : "offline"}`}>{connected ? <span className="online-dot"/> : <WifiOff size={12}/>}<span>{connected ? "Connected" : "Saved demo"}</span></span><div className="mode-switch" aria-label="Data mode">{(["demo", "live"] as Mode[]).map(value => <button key={value} className={mode === value ? "selected" : ""} aria-pressed={mode === value} onClick={() => {setMode(value); setBrief(value === "demo" ? snapshot.briefs[ticker] || null : null); void loadBackend(value, windowDays, snapshot);}}>{value === "demo" ? "Demo" : "Real data"}</button>)}</div><button className="icon-button" aria-label="Alert preferences" onClick={() => setDetail({kind: "settings"})}><Settings2 size={18}/></button><span className="top-avatar">Y</span></div></header>
      <main className="content">
        <div className="demo-notice"><span className="demo-dot"/>{mode === "demo" ? "Demo workspace · financials, people and relationships are fictional." : "Real-source mode · filings retain their original dates. Demo contact profiles remain fictional."}<button onClick={() => setDetail({kind: "about"})}>Learn more <ArrowRight size={12}/></button></div>

        {tab === "today" && <><section className="page-heading"><div><div className="eyebrow">{new Date().toLocaleDateString("en-IN", {weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kolkata"})}</div><h1>A little less noise.<br/><em>A lot more perspective.</em></h1><p>Your portfolio, the important changes, and the people who can help.</p></div><button className="secondary-button" onClick={() => void refresh()} disabled={loading}><RefreshCw size={15} className={loading ? "spin" : ""}/>{loading ? "Checking sources" : "Refresh brief"}</button></section>
          <div className="overview-strip"><div><span className="overview-icon"><Activity size={18}/></span><div><strong>{material.length}</strong><span>updates to consider</span></div></div><div><span className="overview-icon"><GitBranch size={18}/></span><div><strong>{material.filter(i => i.network?.length).length}</strong><span>with a network connection</span></div></div><div><span className="overview-icon"><ShieldCheck size={18}/></span><div><strong>Primary sources</strong><span>Evidence before interpretation</span></div></div></div>
          <div className="feed-layout"><section className="feed"><div className="section-bar"><h2>Your attention, well spent <span>{digest.items.length}</span></h2><label className="window-select"><Clock3 size={14}/><select aria-label="Digest window" value={windowDays} onChange={e => {const days = Number(e.target.value); setWindowDays(days); void loadBackend(mode, days, snapshot);}}><option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option></select><ChevronDown size={13}/></label></div>
            {!digest.items.length && <div className="empty-state"><Layers3 size={30}/><h3>A quieter window.</h3><p>No material filings are stored for this period. Widen the window or refresh your sources.</p></div>}
            {digest.items.map((item, index) => <article className={`feed-card ${index === 0 ? "featured" : ""}`} key={item.id}><div className="card-top"><span className={`category-tag ${item.category === "management_change" ? "purple" : item.category === "capex" ? "ochre" : ""}`}>{item.type === "market_alert" ? "Market movement" : label(item.category || "Update")}</span><span className="time-label">{new Date(item.published_at).toLocaleTimeString("en-IN", {hour: "2-digit", minute: "2-digit", timeZone: "Asia/Kolkata"})}</span></div><div className="company-row"><span className="company-mark">{item.ticker.slice(0, 2)}</span><div><strong>{clean(companyName(item.ticker))}</strong><span>{item.ticker} <i/> {item.type === "market_alert" ? "End-of-day observation" : "Exchange filing"}</span></div><button className="icon-button" aria-label={`View ${item.ticker} ${item.category || "market alert"}`} onClick={() => setDetail({kind: "event", item})}><ArrowUpRight size={19}/></button></div>
              <h3 className="card-title">{item.category === "management_change" ? `${clean(item.enrichment?.management?.person?.name || "New leadership")}: a connection worth knowing` : item.category === "results" ? "The results are in. Here’s the context." : item.category === "capex" ? "A new investment. A useful perspective." : item.type === "market_alert" ? "A move beyond your usual threshold." : clean(item.title || item.summary)}</h3>
              {item.enrichment?.results ? <div className="metric-row">{["revenue", "ebitda", "pat"].map(metric => <div key={metric}><span>{metric === "revenue" ? "Revenue" : metric.toUpperCase()}</span><strong>₹{number(item.enrichment?.results?.period.metrics[metric])}<small> cr</small></strong><span className="positive">{item.enrichment?.results?.comparisons.qoq?.[metric]?.percent == null ? "QoQ unavailable" : `${number(item.enrichment.results.comparisons.qoq[metric].percent, 1)}% QoQ`} <ArrowUpRight size={11}/></span></div>)}</div> : <p className="card-summary">{item.category === "management_change" ? "A leadership change, with a recorded introduction through your network. Explore the background before forming a view." : item.category === "capex" ? "Your network includes a supplier perspective on capacity expansion. A useful place to start asking questions." : item.summary}</p>}
              {item.enrichment?.results?.cross_check.metrics?.revenue.status === "mismatch" && <button className="quality-note" onClick={() => setDetail({kind: "event", item})}><span>!</span>{mode === "demo" ? "Synthetic reference mismatch planted for review" : "Reported revenue differs from the reference"}<ChevronRight size={13}/></button>}
              {!!item.network?.length && <div className="card-network"><div className="avatar-stack">{item.network.slice(0, 2).map(p => <Avatar key={p.contact_id} person={p} small/>)}</div><button onClick={() => showPersonId(item.network[0].contact_id)}><strong>{clean(item.network[0].name).split(" ")[0]}</strong>{item.network.length > 1 ? ` +${item.network.length - 1} people who could add context` : " could add context"}<ArrowRight size={13}/></button></div>}
              <div className="card-footer"><span><FileText size={12}/>{item.enrichment?.results ? "Figures and comparisons available" : "Original filing context"}</span><button onClick={() => {setDetail(null); void ask(item.ticker, "Compare management guidance with delivered outcomes and explain the financial trajectory.");}}>Go deeper <ArrowRight size={13}/></button></div></article>)}
            {digest.routine_count > 0 && <div className="routine-block"><button onClick={() => setShowRoutine(!showRoutine)} aria-expanded={showRoutine}><FileText size={16}/><div><strong>{digest.routine_count} routine {digest.routine_count === 1 ? "filing" : "filings"}</strong><span>Kept out of your way. Still here if you need them.</span></div><ChevronDown size={17} className={showRoutine ? "rotate" : ""}/></button>{showRoutine && digest.routine.map(item => <button className="routine-item" key={item.id} onClick={() => setDetail({kind: "event", item})}>{item.ticker} · {clean(item.title || item.summary)}<ArrowUpRight size={14}/></button>)}</div>}
          </section><aside className="context-rail"><section className="rail-card"><div className="rail-heading"><span className="small-symbol"><Network size={17}/></span><h2>A reason to reconnect</h2></div><p className="rail-intro">Good conversations start with timely context.</p>{workspace.nudges.slice(0, 2).map(n => {const p = people.find(p => p.id === n.person_id); return <div className="nudge" key={n.person_id}><div className="person-row"><Avatar person={n}/><div><strong>{clean(n.name)}</strong><span>{Math.floor(n.days_since_contact / 30)} months since last contact</span></div></div><p>{n.reason}</p><button onClick={() => p && void openPerson(p)}>View context <ArrowRight size={13}/></button></div>;})}{!workspace.nudges.length && <p className="empty-note">Reconnect suggestions appear when a relevant event meets an older contact.</p>}</section>
            <section className="rail-card watchlist"><div className="rail-heading"><h2>On your radar</h2><span>{workspace.portfolio.length}</span></div>{workspace.portfolio.slice(0, 6).map(c => <button key={c.ticker} onClick={() => void ask(c.ticker)}><span className="company-mark small">{c.ticker.slice(0, 2)}</span><div><strong>{c.ticker}</strong><span>{c.sector}</span></div><ChevronRight size={14}/></button>)}<p>Explore any NSE ticker in Ask FINN.</p></section><div className="quiet-note"><BookOpen size={17}/><p>Useful intelligence starts with what the source actually says.</p></div></aside></div>
        </>}

        {tab === "ask" && <section className="ask-page"><div className="page-heading compact"><div><div className="eyebrow">PULL · COMPANY RESEARCH</div><h1>Ask a better question.</h1><p>Follow the evidence. Make the judgment yourself.</p></div><span className="outline-badge"><BookOpen size={13}/>Primary sources only</span></div>
          <form className="ask-form" onSubmit={e => {e.preventDefault(); void ask();}}><div className="ticker-input"><label htmlFor="ticker">Company ticker</label><input id="ticker" value={ticker} maxLength={30} onChange={e => setTicker(e.target.value.toUpperCase())} placeholder="e.g. TCS" required/></div><div className="question-input"><label htmlFor="question">Your question</label><input id="question" value={question} onChange={e => setQuestion(e.target.value)} placeholder="Business, cash quality, guidance… what would you like to understand?" maxLength={2000}/></div><button className="primary-button" type="submit" disabled={asking}>{asking ? <LoaderCircle size={17} className="spin"/> : <Sparkles size={17}/>}Research <ArrowRight size={16}/></button></form>
          <div className="suggestions"><span>Try a company</span>{snapshot.scenario.research_tickers.map(t => <button key={t} onClick={() => void ask(t)}>{t}<ArrowUpRight size={11}/></button>)}</div>
          {asking && <div className="research-loading" role="status"><div className="loading-orbit"><BookOpen size={27}/></div><h2>Making the connections.</h2><p>{progress}</p><button className="text-button" onClick={() => {requestRef.current?.abort(); setAsking(false);}}>Cancel research</button></div>}
          {!asking && brief && <><div className="brief-header"><div className="company-row"><span className="company-mark large">{brief.ticker.slice(0, 2)}</span><div><div className="eyebrow">RESEARCH BRIEF</div><h2>{clean(companyName(brief.ticker))}</h2><span>{brief.ticker} · {brief.mode === "demo" ? "Synthetic demonstration" : "Primary-source research"}</span></div></div><div className="brief-coverage"><strong>{brief.coverage.documents} documents</strong><span>{brief.coverage.transcripts} transcripts · {brief.coverage.annual_reports} annual reports</span><span>{brief.cached ? "Saved analysis · connections refreshed" : brief.status === "analysed" ? "Source-cited analysis" : "Source evidence available"}</span></div></div>
            <div className="research-layout"><div className="brief-main">{brief.status === "needs_sources" && <div className="empty-state"><BookOpen size={30}/><h3>We need the source material first.</h3><p>Switch to real data to discover reports and transcripts, or try one of the saved demo companies.</p></div>}
              {brief.sections.map(section => <section className="brief-section" key={section.id}><div className="section-title"><span>{String(brief.sections.findIndex(s => s.id === section.id) + 1).padStart(2, "0")}</span><h3>{section.title}</h3></div>
                {section.id === "financial" && !!brief.financials.length && <FinancialTable records={brief.financials}/>}
                {section.id === "guidance" && <><GuidanceChart brief={brief}/>{latestComparison && <div className="guidance-callout"><span className={latestComparison.status === "missed" ? "negative-icon" : "positive-icon"}>{latestComparison.status === "missed" ? <ArrowDownRight size={21}/> : <ArrowUpRight size={21}/>}</span><div><strong>{latestComparison.period}: {latestComparison.status === "missed" ? "below" : latestComparison.status === "exceeded" ? "above" : "within"} guidance</strong><p>{latestComparison.guided_low}% guided · {latestComparison.actual}% delivered · {number(Math.abs(latestComparison.delta || 0), 1)} percentage {Math.abs(latestComparison.delta || 0) === 1 ? "point" : "points"}{citations(latestComparison.citation_ids)}</p></div></div>}</>}
                {section.findings.length ? section.findings.map((finding, index) => <p className="finding" key={index}>{finding.text}{citations(finding.citation_ids)}</p>) : <p className="empty-note">{section.empty_message}</p>}
              </section>)}
              {!!brief.gaps.length && <section className="gaps-panel"><h3><CircleHelp size={16}/>What the sources don’t establish</h3><ul>{brief.gaps.map((gap, i) => <li key={i}>{gap}</li>)}</ul></section>}
              <div className="brief-footnote"><ShieldCheck size={15}/><span>References are checked. Open the excerpts to review the interpretation. {brief.model && <small>Analysis: {brief.model}</small>}</span></div>
            </div><aside className="research-rail"><section className="rail-card"><div className="rail-heading"><Users size={17}/><h2>People who’d know</h2></div><p className="rail-intro">A useful perspective beyond the page.</p>{brief.network.map(p => <button className="research-person" key={p.contact_id} onClick={() => showPersonId(p.contact_id)}><Avatar person={p}/><div><strong>{clean(p.name)}</strong><span>{p.reasons[0]}</span></div><ChevronRight size={13}/></button>)}{!brief.network.length && <p className="empty-note">No relevant supplied contacts found.</p>}</section><section className="rail-card"><div className="rail-heading"><FileText size={17}/><h2>Source library</h2></div>{brief.sources.filter((s, i, all) => all.findIndex(x => x.document_id === s.document_id) === i).map(s => <button className="source-row" key={s.document_id} onClick={() => setDetail({kind: "source", source: s})}><FileText size={17}/><div><strong>{clean(s.title)}</strong><span>{s.kind === "financial_table" ? "Structured observation" : dateText(s.published_on)}</span></div><ArrowUpRight size={13}/></button>)}</section></aside></div></>}
        </section>}

        {tab === "people" && <section className="people-page"><div className="page-heading compact"><div><div className="eyebrow">NETWORK · CONTEXT THROUGH CONNECTIONS</div><h1>People. Not just profiles.</h1><p>Find the expertise, shared experience, or introduction behind a question.</p></div><span className="outline-badge"><Users size={14}/>{people.length} profiles</span></div><div className="people-toolbar"><div className="search-field"><Search size={18}/><input aria-label="Search people" placeholder="Search a name, company or area of expertise" value={peopleQuery} onChange={e => setPeopleQuery(e.target.value)}/>{peopleQuery && <button className="icon-button" aria-label="Clear people search" onClick={() => setPeopleQuery("")}><X size={14}/></button>}</div><span><Filter size={13}/>{filteredPeople.length} {filteredPeople.length === 1 ? "person" : "people"}</span></div><div className="expertise-filters">{["All people", "IT services", "specialty chemicals", "banking", "retail"].map(topic => <button className={peopleQuery === topic || (!peopleQuery && topic === "All people") ? "selected" : ""} key={topic} onClick={() => setPeopleQuery(topic === "All people" ? "" : topic)}>{topic}</button>)}</div><div className="people-grid">{filteredPeople.map(p => <button key={p.id} className="person-card" onClick={() => void openPerson(p)}><div className="person-card-top"><Avatar person={p}/><span className="subtle-badge">{p.direct_contact === false ? "Research subject" : p.provenance === "synthetic" ? "Fictional contact" : "Your contact"}</span><ArrowUpRight size={16}/></div><h3>{personName(p)}</h3><p>{p.roles[0]?.title || "Independent perspective"}{p.roles[0] && <span>{p.roles[0].company}</span>}</p><div className="expertise-tags">{p.expertise.slice(0, 2).map(tag => <span key={tag}>{tag}</span>)}{!p.expertise.length && <span>{p.knows.length ? "Recorded connection" : "Professional background"}</span>}</div><div className="person-card-bottom"><span><GitBranch size={12}/>{p.knows.length ? `${p.knows.length} recorded connection` : "Explore shared context"}</span><ChevronRight size={13}/></div></button>)}</div>{!filteredPeople.length && <div className="empty-state"><Search size={28}/><h3>No profiles match that search.</h3><p>Try a company ticker or a broader area of expertise.</p></div>}</section>}
      </main><footer className="workspace-footer"><span className="mini-brand">finn✳</span><span>Context for your judgment.</span><button onClick={() => setDetail({kind: "about"})}>Sources & privacy <ArrowUpRight size={11}/></button></footer></div>
    <nav className="bottom-nav" aria-label="Mobile navigation">{nav.map(n => <button className={tab === n.id ? "active" : ""} key={n.id} onClick={() => setTab(n.id)} aria-current={tab === n.id ? "page" : undefined}><n.icon size={20}/><span>{n.label}</span></button>)}</nav>
    {!!notice && <div className="toast" role="status"><span>{notice}</span><button aria-label="Dismiss notification" onClick={() => setNotice("")}><X size={15}/></button></div>}

    {detail && <Dialog title={detail.kind === "source" ? "Behind the citation" : detail.kind === "person" ? "A closer connection" : detail.kind === "settings" ? "Your attention, your rules" : detail.kind === "about" ? "Built around the evidence" : "The story behind the update"} wide={detail.kind === "source" || detail.kind === "event"} onClose={() => setDetail(null)}>
      {detail.kind === "source" && <><span className="category-tag">{label(detail.source.kind)}</span><h3 className="dialog-title">{clean(detail.source.title)}</h3><p className="muted">{dateText(detail.source.published_on)}{detail.source.page != null && ` · Original page ${detail.source.page}`}</p>{detail.source.mode === "demo" && <p className="source-disclosure">Synthetic demonstration source. These are not real company financials.</p>}{detail.source.financial_record ? <FinancialTable records={[detail.source.financial_record]}/> : <blockquote className="source-excerpt">{detail.source.text}</blockquote>}{detail.source.mode === "live" && detail.source.url && <a className="primary-button inline-button" href={detail.source.url + (detail.source.page ? `#page=${detail.source.page}` : "")} target="_blank" rel="noopener noreferrer">Open original document <ExternalLink size={14}/></a>}</>}
      {detail.kind === "person" && <><div className="profile-heading"><Avatar person={detail.person}/><div><h3>{personName(detail.person)}</h3><span className="subtle-badge">{detail.person.provenance === "synthetic" ? "Fictional professional profile" : label(detail.person.provenance)}</span></div></div>{path.length ? <section className="profile-section"><h4><GitBranch size={16}/>Your route to this person</h4>{path.map((p, i) => <div className="intro-path" key={i}>{p.names.map((name, j) => <span key={j}>{j > 0 && <ArrowRight size={15}/>}<strong>{j === 0 ? "You" : clean(name).split(" ")[0]}</strong></span>)}<small>{p.hops === 1 ? "Direct" : "One introduction"} · recorded connections</small></div>)}</section> : <p className="empty-note">No recorded introduction path is available. Shared employment or education alone does not establish acquaintance.</p>}<section className="profile-section"><h4>Professional timeline</h4><div className="timeline">{detail.person.roles.map((role, i) => <div key={i}><i/><span>{role.start_year} — {role.end_year || "present"}</span><strong>{role.title}</strong><p>{role.company}</p></div>)}</div>{!detail.person.roles.length && <p className="empty-note">No employment history supplied.</p>}</section><section className="profile-section"><h4>Areas of expertise</h4><div className="expertise-tags">{detail.person.expertise.map(tag => <span key={tag}>{tag}</span>)}</div></section>{!!detail.person.education.length && <section className="profile-section"><h4>Education</h4>{detail.person.education.map((e, i) => <p key={i}>{typeof e === "string" ? e : `${e.institution} · ${e.start_year}–${e.end_year}`}</p>)}</section>}{detail.person.notes && <p className="empty-note">{detail.person.notes}</p>}</>}
      {detail.kind === "event" && <><div className="company-row"><span className="company-mark">{detail.item.ticker.slice(0, 2)}</span><div><strong>{clean(companyName(detail.item.ticker))}</strong><span>{detail.item.ticker} · {dateText(detail.item.published_at)}</span></div></div><h3 className="dialog-title">{clean(detail.item.title || detail.item.summary)}</h3><p className="detail-copy">{detail.item.body || detail.item.summary}</p>
        {detail.item.enrichment?.results && <><FinancialTable records={[detail.item.enrichment.results.period]}/><div className="comparison-grid">{["revenue", "ebitda", "pbt", "pat"].map(metric => <div key={metric}><strong>{metric.toUpperCase()}</strong><span>QoQ <b>{number(detail.item.enrichment?.results?.comparisons.qoq?.[metric]?.percent, 1)}%</b></span><span>YoY <b>{number(detail.item.enrichment?.results?.comparisons.yoy?.[metric]?.percent, 1)}%</b></span></div>)}</div><div className="quality-panel"><h4>Reference cross-check</h4><p>{detail.item.mode === "demo" ? "This reference is synthetic; a revenue mismatch is deliberately included so you can review the flag." : "Available reference figures are compared only when period, basis, units and currency match."}</p>{Object.entries(detail.item.enrichment.results.cross_check.metrics || {}).map(([metric, check]) => <div key={metric}><span>{metric.toUpperCase()}</span><strong className={check.status === "mismatch" ? "negative" : ""}>{check.status === "match" ? "Figures agree" : check.status === "mismatch" ? `${number(check.difference_percent, 1)}% difference` : "Reference unavailable"}</strong></div>)}</div></>}
        {detail.item.enrichment?.management && <><h4 className="detail-subheading">Recorded introduction</h4>{detail.item.enrichment.management.paths.map((p, i) => <div className="intro-path" key={i}>{p.names.map((name, j) => <span key={j}>{j > 0 && <ArrowRight size={15}/>}<strong>{j === 0 ? "You" : clean(name)}</strong></span>)}</div>)}{!!detail.item.enrichment.management.overlaps.length && <div className="overlap-panel"><h4>Shared professional context</h4>{detail.item.enrichment.management.overlaps.flatMap(o => o.work.map((w, i) => <div key={`${o.person_id}-${i}`}><span>{clean(o.name)}</span><strong>{w.company}</strong><p>{w.start_year}–{w.end_year} · {w.years} years of employment overlap</p><small>Overlap is not proof of acquaintance.</small></div>))}</div>}</>}
        {!!detail.item.enrichment?.gaps.length && <div className="gaps-panel"><h4>What’s missing</h4>{detail.item.enrichment.gaps.map((g, i) => <p key={i}>{g}</p>)}</div>}<h4 className="detail-subheading">People who could add context</h4>{detail.item.network.map(p => <button className="research-person" key={p.contact_id} onClick={() => showPersonId(p.contact_id)}><Avatar person={p}/><div><strong>{clean(p.name)}</strong><span>{p.reasons.join(" ")}</span></div><ChevronRight size={14}/></button>)}<div className="dialog-actions"><button className="primary-button" onClick={() => {const symbol = detail.item.ticker; setDetail(null); void ask(symbol);}}>Research this company <ArrowRight size={15}/></button>{detail.item.mode === "live" && detail.item.url && <a className="secondary-button" href={detail.item.url} target="_blank" rel="noopener noreferrer">Original filing <ExternalLink size={14}/></a>}</div></>}
      {detail.kind === "settings" && <SettingsForm settings={workspace.settings} connected={connected} onSave={async value => {if (connected) await api("alerts/settings", {method: "PUT", body: JSON.stringify(value)}); else localStorage.setItem("finn-demo-alerts", JSON.stringify(value)); setWorkspace({...workspace, settings: value}); setNotice(connected ? "Alert preferences saved." : "Preferences saved on this device. Connect the backend to apply them."); setDetail(null); if (connected) void loadBackend(mode, windowDays, snapshot);}}/>}
      {detail.kind === "about" && <div className="about-copy"><div className="about-symbol"><ShieldCheck size={30}/></div><h3>Evidence before interpretation.</h3><p>FINN connects portfolio changes, company research and your professional network. Every research finding links to the source excerpt used to support it.</p><h4>About this demonstration</h4><p>Demo financials, professional histories and relationships are fictional. Real company names do not make demo figures real. Switch to Real data to use primary filings and company reports.</p><h4>Your data stays yours</h4><p>Network profiles are not sent to the research model. Introduction paths use recorded relationships; overlapping employers or education do not prove acquaintance. API credentials stay on the server.</p><h4>What to check</h4><p>Open an update to inspect its figures and network path. In Ask FINN, compare guidance with delivered results and tap a numbered citation to read the evidence. Missing information is shown as a gap.</p><p className="empty-note">{connected ? "Connected to your local backend." : `Saved demo generated ${dateText(snapshot.generated_at)}. Connect the backend for new research and real-source refreshes.`}</p></div>}
    </Dialog>}
  </div>;
}

function SettingsForm({settings, connected, onSave}: {settings: Settings; connected: boolean; onSave: (value: Settings) => Promise<void>}) {
  const [draft, setDraft] = useState(settings);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  return <form className="settings-form" onSubmit={async e => {e.preventDefault(); setSaving(true); try {await onSave(draft);} catch (error) {setError(error instanceof Error ? error.message : "Could not save preferences");} finally {setSaving(false);}}}><p>Decide what deserves a place in your brief. Thresholds use completed daily observations.</p><label>Daily price movement<span>Notify when the close moves at least</span><div className="number-control"><input aria-label="Price threshold" type="number" min="0.1" max="100" step="0.1" value={draft.price_change_percent} onChange={e => setDraft({...draft, price_change_percent: Number(e.target.value)})}/><b>%</b></div></label><label>Unusual trading volume<span>Compared with the preceding trading-day average</span><div className="number-control"><input aria-label="Volume threshold" type="number" min="1.1" max="100" step="0.1" value={draft.volume_multiple} onChange={e => setDraft({...draft, volume_multiple: Number(e.target.value)})}/><b>×</b></div></label><label>Volume baseline<span>Requires the full number of prior observations</span><div className="number-control"><input aria-label="Volume baseline" type="number" min="2" max="90" value={draft.volume_lookback_days} onChange={e => setDraft({...draft, volume_lookback_days: Number(e.target.value)})}/><b>days</b></div></label><fieldset><legend>Filings that matter to you</legend>{["results", "management_change", "M&A", "capex", "litigation", "fund_raise", "credit_rating"].map(category => <label className="checkbox-row" key={category}><input type="checkbox" checked={draft.material_categories.includes(category)} onChange={e => setDraft({...draft, material_categories: e.target.checked ? [...draft.material_categories, category] : draft.material_categories.filter(c => c !== category)})}/>{label(category)}</label>)}</fieldset>{!connected && <p className="empty-note">The backend is offline. Changes will be saved locally.</p>}{error && <p className="negative" role="alert">{error}</p>}<button type="submit" className="primary-button" disabled={saving}>{saving ? <LoaderCircle className="spin" size={15}/> : <Check size={15}/>}Save preferences</button></form>;
}
