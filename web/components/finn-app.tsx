"use client";

import {useEffect, useId, useMemo, useRef, useState} from "react";
import {ArrowDownRight, ArrowRight, ArrowUpRight, BookOpen, Check, ChevronDown, ChevronRight, CircleHelp, Clock3, ExternalLink, FileText, Filter, GitBranch, Layers3, LoaderCircle, MessageSquare, Network, RefreshCw, Search, Settings2, Users, WifiOff, X} from "lucide-react";
import Link from "next/link";
import {api, ApiError, isPrimaryBrief, research, ResearchError} from "@/lib/api";
import type {Brief, Citation, Company, Digest, FeedItem, Financial, Path, Person, Settings, Snapshot, SystemStatus} from "@/lib/types";

const DEFAULT_QUESTION = "Explain the business, financial trajectory, management guidance delivery, positives and risks.";
const symbolText = (ticker: string) => ticker.replace(/^US-/, "");
const number = (value: number | null | undefined, digits = 0) => value == null ? "—" : value.toLocaleString("en-IN", {maximumFractionDigits: digits});
const clean = (value: string) => value.replace(/\s*\(fictional\)/gi, "").replace(/^SYNTHETIC(?: REVIEW)?[: ]*/i, "");
const sourceTitle = (value: string) => clean(value).replace(/\s+AI Summary\b.*$/i, "").replace(/\s+from bse\b/i, "").replace(/\s+(?:PPT|REC)(?:\s+(?:PPT|REC))*$/i, "");
const readerText = (value: string) => value.replace(/\s+AI Summary(?:\s+(?:PPT|REC))*/gi, "").replace(/null published_on dates/gi, "unknown publication dates").replace(/published_on is null/gi, "publication date is unknown").replace(/\bpublished_on\b/g, "publication date").replace(/\bnull\b/g, "unavailable").replace(/computed guidance comparisons/gi, "comparisons between guidance and results");
const researchGap = (value: string) => {
  if (/model (?:narrative|key|provider)|hyde\/|glm-\d/i.test(value)) return "Some research is unavailable. Please try again.";
  if (/published_on|publication dates?.*null|null.*published/i.test(value)) return "Publication dates are unavailable for some documents.";
  if (/no computed guidance/i.test(value)) return "The available sources don’t support a guidance-versus-results comparison.";
  return readerText(value);
};
const label = (value: string) => value.replaceAll("_", " ");
const personName = (p: Person) => clean(p.name);
const initials = (name: string) => clean(name).split(" ").slice(0, 2).map(p => p[0]).join("");
const dateText = (date?: string | null) => date ? new Date(date).toLocaleDateString("en-IN", {day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Kolkata"}) : "Publication date unavailable";
type Tab = "today" | "ask" | "people";
type Detail = {kind: "event"; item: FeedItem} | {kind: "person"; person: Person} | {kind: "source"; source: Citation} | {kind: "settings"} | {kind: "about"} | {kind: "portfolio"};

function savedWindow(saved: Snapshot, days: number): Snapshot {
  const since = Date.now() - days * 86400000;
  const inWindow = (item: FeedItem) => item.mode === "live" && new Date(item.published_at).getTime() >= since && new Date(item.published_at).getTime() <= Date.now();
  const routine = saved.digest.routine.filter(inWindow);
  return {...saved, digest: {...saved.digest, items: saved.digest.items.filter(inWindow), routine, routine_count: routine.length}};
}

function Dialog({title, onClose, children, wide = false}: {title: string; onClose: () => void; children: React.ReactNode; wide?: boolean}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {ref.current?.showModal();}, []);
  return <dialog ref={ref} aria-labelledby={titleId} className={`dialog ${wide ? "wide" : ""}`} onCancel={onClose} onClick={event => {if (event.target === event.currentTarget) onClose();}}>
    <div className="dialog-head"><h2 id={titleId}>{title}</h2><button className="icon-button" aria-label="Close dialog" onClick={onClose}><X size={20}/></button></div>
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
  if (!rows.length) return null;
  const values = rows.flatMap(r => [r.guided_low, r.guided_high, r.actual as number]);
  const low = Math.min(...values) - 1, high = Math.max(...values) + 1;
  const x = (i: number) => rows.length === 1 ? 280 : 55 + i * 450 / (rows.length - 1);
  const y = (value: number) => 170 - (value - low) * 125 / (high - low);
  return <div className="guidance-chart"><div className="chart-legend"><span><i className="dot dashed"/>Guided</span><span><i className="dot"/>Delivered</span><span className="muted">EBITDA margin</span></div>
    <svg viewBox="0 0 560 220" role="img" aria-label="Guided versus delivered EBITDA margin by quarter">
      {[low, (low + high) / 2, high].map(v => <g key={v}><line x1="44" x2="520" y1={y(v)} y2={y(v)} stroke="var(--line)"/><text x="5" y={y(v) + 4} fill="var(--muted)" fontSize="11">{number(v, 1)}%</text></g>)}
      <polyline points={rows.map((r, i) => `${x(i)},${y(r.guided_low)}`).join(" ")} fill="none" stroke="var(--muted)" strokeWidth="2" strokeDasharray="5 5"/>
      <polyline points={rows.map((r, i) => `${x(i)},${y(r.actual as number)}`).join(" ")} fill="none" stroke="var(--accent)" strokeWidth="3"/>
      {rows.map((r, i) => <g key={r.period}><circle cx={x(i)} cy={y(r.actual as number)} r="5" fill="var(--accent)" stroke="var(--surface)" strokeWidth="2"/><text x={x(i)} y={y(r.actual as number) + 23} textAnchor="middle" fontSize="12" fill="var(--ink)">{r.actual}%</text><text x={x(i)} y="210" textAnchor="middle" fill="var(--muted)" fontSize="11">{r.period}</text></g>)}
    </svg></div>;
}

export default function FinnApp() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [workspace, setWorkspace] = useState<Snapshot | null>(null);
  const [tab, setTab] = useState<Tab>("today");
  const [enriching,setEnriching] = useState(false);
  const [eventError,setEventError] = useState("");
  const [preparing,setPreparing] = useState<string[]>([]);
  const preparedRef = useRef(new Set<string>());
  const [researchError, setResearchError] = useState("");
  const [connected, setConnected] = useState(false);
  const [windowDays, setWindowDays] = useState(1);
  const windowDaysRef = useRef(1);
  useEffect(() => {windowDaysRef.current = windowDays;}, [windowDays]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const refreshRef = useRef<Promise<void> | null>(null);
  const [notice, setNotice] = useState("");
  const [detail, setDetail] = useState<Detail | null>(null);
  const [ticker, setTicker] = useState("");
  const [question, setQuestion] = useState("");
  const [brief, setBrief] = useState<Brief | null>(null);
  const [progress, setProgress] = useState("");
  const [asking, setAsking] = useState(false);
  const [peopleQuery, setPeopleQuery] = useState("");
  const [showRoutine, setShowRoutine] = useState(false);
  const [path, setPath] = useState<Path[]>([]);
  const [profileOverlaps,setProfileOverlaps]=useState<{person_id:string;name:string;work:{company:string;start_year:number;end_year:number}[];education:{institution:string;start_year?:number|null;end_year?:number|null}[]}[]>([]);
  const requestRef = useRef<AbortController | null>(null);
  const backendLoadRef = useRef(0);

  async function loadBackend(days: number, saved: Snapshot) {
    const load = ++backendLoadRef.current;
    setLoading(true);
    try {
      const end = Date.now();
      const since = new Date(end - days * 86400000).toISOString();
      const [portfolio, digest, contacts, investor, settings, nudges] = await Promise.all([
        api<{companies: Company[]}>("portfolio"), api<Digest>(`digest?mode=live&since=${since}&include_routine=true`),
        api<{contacts: Person[]}>("network"), api<Person>("network/investor"), api<Settings>("alerts/settings"),
        api<{nudges: Snapshot["nudges"]}>("network/reconnect?mode=live")
      ]);
      if (load !== backendLoadRef.current) return;
      setWorkspace({...saved, portfolio: portfolio.companies.filter(c => !c.ticker.startsWith("MOCK")), digest, contacts: contacts.contacts, investor, settings, nudges: nudges.nudges});
      setConnected(true);
    } catch {
      if (load !== backendLoadRef.current) return;
      setConnected(false);
      setWorkspace(savedWindow(saved, days));
    } finally { if (load === backendLoadRef.current) setLoading(false); }
  }

  useEffect(() => {
    let mounted = true;
    fetch("/snapshot.json").then(r => {if (!r.ok) throw new Error("Saved company data is missing"); return r.json();}).then((saved: Snapshot) => {
      if (!mounted) return;
      try {const local = localStorage.getItem("finn-demo-alerts"); if (local) saved.settings = JSON.parse(local);} catch {}
      // Keep fictional scenario companies out of the investor-facing workspace.
      saved.portfolio = saved.portfolio.filter(c => !c.ticker.startsWith("MOCK"));
      saved.digest.items = saved.digest.items.filter(i => i.mode === "live");
      saved.digest.routine = saved.digest.routine.filter(i => i.mode === "live");
      saved.digest.routine_count = saved.digest.routine.length;
      saved.briefs = Object.fromEntries(Object.entries(saved.briefs).filter(([, value]) => isPrimaryBrief(value)));
      setSnapshot(saved); setWorkspace(savedWindow(saved, 1));
      void loadBackend(1, saved);
    }).catch(() => setNotice("Could not load your updates. Please reload."));
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    return () => {mounted = false; requestRef.current?.abort();};
  }, []);

  useEffect(() => {if (notice) {const timer = setTimeout(() => setNotice(""), 6500); return () => clearTimeout(timer);}}, [notice]);

  const people = useMemo(() => workspace?.contacts.map(p => ({...p, roles: p.roles.filter(r => !r.ticker?.startsWith("MOCK"))})) || [], [workspace]);
  const filteredPeople = useMemo(() => people.filter(p => [p.name, ...p.expertise, ...p.roles.flatMap(r => [r.company, r.title, r.ticker || ""]), ...(p.related_companies || []).map(r => r.ticker)].join(" ").toLowerCase().includes(peopleQuery.trim().toLowerCase())), [people, peopleQuery]);

  async function ask(symbol = ticker, prompt = question) {
    requestRef.current?.abort();
    const control = new AbortController(); requestRef.current = control;
    const normalized = symbol.trim().toUpperCase();
    setTicker(symbolText(normalized)); navigate("ask"); setResearchError(""); setAsking(true); setProgress("Looking through primary sources"); setBrief(null);
    if (!connected) {
      const saved = snapshot?.briefs[normalized];
      if (saved && isPrimaryBrief(saved)) {setBrief(saved); setNotice("Offline: showing the saved overview. Reconnect for an answer to your question.");}
      else setResearchError("You’re offline. Reconnect to research this company.");
      setAsking(false); return;
    }
    try {const result = await research(normalized, {question: prompt.trim() || DEFAULT_QUESTION, mode: "live", prepare_sources: true}, setProgress, control.signal); setBrief(result); setTicker(result.ticker);}
    catch (error) {if (!control.signal.aborted) setResearchError(error instanceof ResearchError ? error.message : "Research couldn’t be completed. Please try again.");}
    finally {if (!control.signal.aborted) setAsking(false);}
  }

  async function prepareGroup(items: FeedItem[]) {
    if(!connected)return;
    for(const item of items){
      if(item.ticker.startsWith("US-")||preparedRef.current.has(item.id)||item.enrichment?.source_quotes||item.enrichment?.results)continue;
      preparedRef.current.add(item.id);setPreparing(old=>[...old,item.id]);
      try{
        const enrichment=await api<NonNullable<FeedItem["enrichment"]>>(`announcements/${item.id}/enrich`,{method:"POST"});
        setWorkspace(old=>old?{...old,digest:{...old.digest,items:old.digest.items.map(row=>row.id===item.id?{...row,enrichment}:row),routine:old.digest.routine.map(row=>row.id===item.id?{...row,enrichment}:row)}}:old);
      }catch{preparedRef.current.delete(item.id);setNotice("Some filing details could not be read. The original document is still available.");}
      finally{setPreparing(old=>old.filter(id=>id!==item.id));}
    }
  }

  async function openPerson(person: Person) {
    setProfileOverlaps([]);setPath(snapshot?.paths[person.id] || []); setDetail({kind: "person", person});
    if (connected) try {const result=await api<{paths:Path[];overlaps:typeof profileOverlaps}>(`network/paths?person_id=${encodeURIComponent(person.id)}`);setPath(result.paths);setProfileOverlaps(result.overlaps||[]);} catch {setPath([]);}
  }

  async function refresh(companies = workspace?.portfolio || [], days = windowDays) {
    if (!snapshot) return;
    if (!connected) {await loadBackend(days, snapshot);return;}
    if (refreshRef.current) {await refreshRef.current;return refresh(companies, days);}
    const work = (async () => {
      setRefreshing(true);setNotice("Checking news, filings and daily prices…");
      try {
        for(let attempt=0;attempt<2;attempt++){
          let run:SystemStatus["refresh_runs"][number];let own=true;
          try {run=await api("refresh",{method:"POST",body:JSON.stringify({tickers:companies.map(c=>c.ticker),days:Math.max(7,days),fundamentals:true,enrich:true,news:true})});}
          catch(error){
            if(!(error instanceof ApiError)||error.status!==409)throw error;
            const active=(await api<{runs:SystemStatus["refresh_runs"]}>("refresh")).runs.find(run=>["queued","running"].includes(run.status));
            if(!active)throw error;run=active;own=false;
          }
          if(!run.id)throw new Error("Could not start the update check. Please try again.");
          let loadedNews=false;
          for(let i=0;i<180;i++){
            run=await api(`refresh/${run.id}`);
            if(!loadedNews&&["queued","running"].includes(run.status)&&run.sources?.some(source=>source.source==="news"&&source.count)){await loadBackend(windowDaysRef.current,snapshot);loadedNews=true;}
            if(!["queued","running"].includes(run.status))break;
            await new Promise(resolve=>setTimeout(resolve,1000));
          }
          if(!own&&attempt===0)continue;
          setNotice(["queued","running"].includes(run.status)?"Still checking updates. You can keep browsing.":run.status==="completed"?"News, filings and daily prices checked.":"Some updates couldn’t be checked. Available news and filings are shown.");
          break;
        }
      } catch(error){setNotice(error instanceof Error?error.message:"Could not check updates. Please try again.");}
      finally {await loadBackend(windowDaysRef.current,snapshot);setRefreshing(false);}
    })();
    refreshRef.current=work;
    try {await work;} finally {refreshRef.current=null;}
  }

  const companyName = (symbol: string) => ({TCS: "Tata Consultancy Services", INFY: "Infosys", TITAN: "Titan Company", CDSL: "Central Depository Services", HCLTECH: "HCL Technologies"}[symbol] || workspace?.portfolio.find(c => c.ticker === symbol)?.name || symbol);
  const filingUrl = (item: FeedItem) => connected && item.mode === "live" && item.type !== "news" && !item.ticker.startsWith("US-") ? `/api/announcements/${encodeURIComponent(item.id)}/document` : item.url;
  const showPersonId = (id: string) => {const person = people.find(p => p.id === id); if (person) void openPerson(person);};
  function navigate(next: Tab) {setTab(next); window.scrollTo({top: 0, behavior: "instant"});}
  const nav = [{id: "today" as Tab, label: "Today", icon: Layers3}, {id: "ask" as Tab, label: "Research", icon: MessageSquare}, {id: "people" as Tab, label: "People", icon: Users}];

  function citations(ids: string[]) {
    return <span className="citation-chips">{ids.map(id => {const source = brief?.sources.find(s => s.citation_id === id); return source ? <button key={id} title={sourceTitle(source.title)} onClick={() => setDetail({kind: "source", source})}><FileText size={11}/>{(brief?.sources.findIndex(s => s.citation_id === id) ?? 0) + 1}</button> : null;})}</span>;
  }

  if (!workspace || !snapshot) return <main className="boot"><span className="brand-word">finn<span>✳</span></span><LoaderCircle className="spin"/><p>{notice || "Preparing your workspace…"}</p></main>;
  const {digest} = workspace;
  const allFilings = [...digest.items, ...digest.routine].filter((item, index, all) => all.findIndex(other => other.id === item.id) === index);
  const groups = [
    {id:"management",title:"Management changes",description:"Appointments, departures and the people behind them",items:allFilings.filter(item=>item.type!=="news"&&item.category==="management_change")},
    {id:"results",title:"Quarterly results",description:"Revenue, EBITDA, PBT and PAT · QoQ and YoY",items:allFilings.filter(item=>item.type!=="news"&&item.category==="results")},
    {id:"material",title:"Material events",description:"M&A, capex and litigation · who can add context",items:allFilings.filter(item=>item.type!=="news"&&["M&A","capex","litigation"].includes(item.category||""))},
    {id:"market",title:"Market alerts",description:"Daily price and volume moves",items:digest.items.filter(item=>item.type==="market_alert")},
    {id:"news",title:"News",description:"Publisher headlines and original articles",items:digest.items.filter(item=>item.type==="news")},
    {id:"other",title:"Other filings",description:"Routine disclosures and announcements",items:allFilings.filter(item=>item.type!=="news"&&item.type!=="market_alert"&&!["management_change","results","M&A","capex","litigation"].includes(item.category||""))}
  ].sort((a,b)=>b.items.length-a.items.length);
  const latestComparison = brief?.guidance.filter(g => g.metric === "ebitda_margin" && g.unit === "percent" && g.actual != null).at(-1);

  return <div className="app-shell">
    <aside className="sidebar"><Link className="brand-word" href="/" aria-label="FINN home">finn<span>✳</span></Link><p className="brand-caption">YOUR INVESTING COPILOT</p><nav aria-label="Main navigation">{nav.map(n => <button key={n.id} aria-label={n.label} className={tab === n.id ? "active" : ""} onClick={() => navigate(n.id)} aria-current={tab === n.id ? "page" : undefined}><n.icon size={19}/>{n.label}{n.id === "today" && <span className="nav-count">{digest.items.length}</span>}</button>)}</nav>
      <div className="sidebar-bottom"><button onClick={() => setDetail({kind: "settings"})}><Settings2 size={17}/>Alert preferences</button><button onClick={() => setDetail({kind: "about"})}><CircleHelp size={17}/>About FINN</button><div className="investor"><span className="avatar">Y</span><div><strong>Your workspace</strong><small>Personal investor</small></div><span className="online-dot"/></div></div>
    </aside>
    <div className="main-shell"><header className="topbar"><div className="mobile-brand brand-word">finn<span>✳</span></div><span className="breadcrumb">Workspace <ChevronRight size={13}/><strong>{nav.find(n => n.id === tab)?.label}</strong></span><div className="top-actions">{!connected && <span className="offline-status"><WifiOff size={13}/>Offline · saved data</span>}<button className="icon-button" aria-label="Alert preferences" onClick={() => setDetail({kind: "settings"})}><Settings2 size={18}/></button><span className="top-avatar">Y</span></div></header>
      <main className="content" aria-busy={loading}>
        {tab === "today" && <><section className="page-heading"><div><div className="eyebrow">{new Date().toLocaleDateString("en-IN", {weekday: "long", day: "numeric", month: "long", timeZone: "Asia/Kolkata"})}</div><h1>Portfolio Status</h1></div><div className="heading-actions"><button className="secondary-button" onClick={() => setDetail({kind: "portfolio"})}><Layers3 size={15}/>Manage portfolio</button><button className="primary-button" onClick={() => void refresh()} disabled={loading || refreshing} title="Check the latest news, company filings and daily prices"><RefreshCw size={15} className={loading || refreshing ? "spin" : ""}/>{loading || refreshing ? "Checking updates…" : "Check updates"}</button></div></section>
          <div className="feed-layout"><section className="feed"><div className="section-bar"><h2>Updates <span title="Individual updates across all sections in the selected period">{allFilings.length}</span></h2><label className="window-select"><Clock3 size={14}/><select aria-label="Digest window" value={windowDays} onChange={e => {const days = Number(e.target.value); setWindowDays(days); void loadBackend(days, snapshot);}}><option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option></select><ChevronDown size={13}/></label></div>
            {!allFilings.length && <div className="empty-state"><Layers3 size={30}/><h3>No updates in this window.</h3><p>Try a longer timeframe or check for recent news and filings.</p>{windowDays === 1 && <button className="secondary-button" onClick={() => {setWindowDays(7); void loadBackend(7, snapshot);}}>Show last 7 days <ArrowRight size={14}/></button>}</div>}
            {groups.map(group => <details className="feed-group" key={group.id} onToggle={event=>{if(event.currentTarget.open&&["management","results","material"].includes(group.id))void prepareGroup(group.items);}}><summary><div><h2>{group.title}<span>{group.items.length}</span></h2><p>{group.description}</p></div><ChevronDown size={18}/></summary><div className="feed-group-content">{!group.items.length&&<p className="empty-note">No {group.title.toLowerCase()} in this window.</p>}{group.items.map((item, index) => <article className={`feed-card ${index === 0 ? "featured" : ""}`} key={item.id}><div className="card-top"><span className={`category-tag ${item.category === "management_change" ? "purple" : item.category === "capex" ? "ochre" : ""}`}>{item.type === "news" ? "News" : item.type === "market_alert" ? "Market movement" : label(item.category || "Update")}</span><span className="time-label">{dateText(item.published_at)}</span></div><div className="company-row"><span className="company-mark">{symbolText(item.ticker).slice(0, 2)}</span><div><strong>{clean(companyName(item.ticker))}</strong><span>{symbolText(item.ticker)} <i/> {item.type === "news" ? item.source?.publisher || "News article" : item.type === "market_alert" ? "End-of-day observation" : item.source?.publisher || "Exchange filing"}</span></div><button className="icon-button" aria-label={`View ${symbolText(item.ticker)} ${item.category || "market alert"}`} onClick={() => {setEventError(""); setDetail({kind: "event", item});}}><ArrowUpRight size={19}/></button></div>
              <h3 className="card-title">{clean(item.title || item.summary)}</h3>
              {item.enrichment?.results ? <div className="metric-row">{["revenue", "ebitda", "pbt", "pat"].map(metric => <div key={metric}><span>{metric === "revenue" ? "Revenue" : metric.toUpperCase()}</span><strong>{item.enrichment?.results?.period.metrics[metric]==null?"—":`₹${number(item.enrichment.results.period.metrics[metric])}`}<small> {item.enrichment?.results?.period.unit || "unit unavailable"}</small></strong><span className={(item.enrichment?.results?.comparisons.qoq?.[metric]?.percent || 0) < 0 ? "negative" : "positive"}>{item.enrichment?.results?.comparisons.qoq?.[metric]?.percent == null ? "QoQ unavailable" : `${number(item.enrichment.results.comparisons.qoq[metric].percent, 1)}% QoQ`}</span><span className={(item.enrichment?.results?.comparisons.yoy?.[metric]?.percent || 0) < 0 ? "negative" : "positive"}>{item.enrichment?.results?.comparisons.yoy?.[metric]?.percent == null ? "YoY unavailable" : `${number(item.enrichment.results.comparisons.yoy[metric].percent, 1)}% YoY`}</span></div>)}</div> : clean(item.enrichment?.summary || item.summary) !== clean(item.title || item.summary) && <p className="card-summary">{clean(item.enrichment?.summary || item.summary)}</p>}
              {preparing.includes(item.id)&&<p className="empty-note"><LoaderCircle size={13} className="spin"/> Reading the original filing…</p>}
              {item.enrichment?.management?.incoming&&<div className="incoming-profile"><strong>{item.enrichment.management.incoming.name}</strong><span>{item.enrichment.management.incoming.title}</span><p>{item.enrichment.management.incoming.bio||"The filing names this person but does not include a professional background."}</p></div>}
              {item.enrichment?.results?.cross_check.metrics?.revenue.status === "mismatch" && <button className="quality-note" onClick={() => {setEventError(""); setDetail({kind: "event", item});}}><span>!</span>Reported revenue differs from the reference<ChevronRight size={13}/></button>}
              {!!item.network?.length && <div className="card-network"><div className="avatar-stack">{item.network.slice(0, 2).map(p => <Avatar key={p.contact_id} person={p} small/>)}</div><button onClick={() => showPersonId(item.network[0].contact_id)}><strong>{clean(item.network[0].name).split(" ")[0]}</strong>{item.network.length > 1 ? ` +${item.network.length - 1} people who could add context` : " could add context"}<span className="contact-reason">{item.network[0].reasons[0]}</span><ArrowRight size={13}/></button></div>}
              <div className="card-footer">{item.type === "news" ? <a href={item.url} target="_blank" rel="noopener noreferrer"><ExternalLink size={12}/>Read article</a> : item.url ? <a href={filingUrl(item)} target="_blank" rel="noopener noreferrer"><FileText size={12}/>Open filing</a> : <button onClick={() => {setEventError(""); setDetail({kind: "event", item});}}><FileText size={12}/>Filing details</button>}<button onClick={() => {setDetail(null); void ask(item.ticker, "Compare management guidance with delivered outcomes and explain the financial trajectory.");}}>Research company <ArrowRight size={13}/></button></div></article>)}</div></details>)}

          </section><aside className="context-rail">{!!workspace.nudges.length && <section className="rail-card"><div className="rail-heading"><span className="small-symbol"><Network size={17}/></span><h2>Reconnect</h2></div><p className="rail-intro">Contacts linked to recent portfolio events.</p>{workspace.nudges.slice(0, 2).map(n => {const p = people.find(p => p.id === n.person_id); return <div className="nudge" key={n.person_id}><div className="person-row"><Avatar person={n}/><div><strong>{clean(n.name)}</strong><span>{Math.floor(n.days_since_contact / 30)} months since last contact</span></div></div><p>{n.reason}</p><button onClick={() => p && void openPerson(p)}>View context <ArrowRight size={13}/></button></div>;})}</section>}
            <section className="rail-card watchlist"><div className="rail-heading"><h2>Portfolio</h2><span>{workspace.portfolio.length}</span></div>{workspace.portfolio.slice(0, 6).map(c => <button key={symbolText(c.ticker)} onClick={() => void ask(c.ticker)}><span className="company-mark small">{symbolText(c.ticker).slice(0, 2)}</span><div><strong>{symbolText(c.ticker)}</strong><span>{clean(companyName(c.ticker))}</span></div><ChevronRight size={14}/></button>)}<button className="portfolio-manage" onClick={()=>setDetail({kind:"portfolio"})}>{workspace.portfolio.length>6?`View all ${workspace.portfolio.length} companies`:"Add or remove companies"}<ArrowRight size={14}/></button></section></aside></div>
        </>}

        {tab === "ask" && <section className="ask-page"><div className="page-heading compact"><div><h1>Company research</h1><p>Search Indian and US companies by name or ticker.</p></div><span className="outline-badge"><BookOpen size={13}/>Primary sources only</span></div>
          <form className="ask-form" onSubmit={e => {e.preventDefault(); void ask();}}><div className="ticker-input"><label htmlFor="ticker">Company</label><input id="ticker" value={ticker} maxLength={120} onChange={e => setTicker(e.target.value)} placeholder="Name or ticker" required/></div><div className="question-input"><label htmlFor="question">Your question</label><input id="question" value={question} onChange={e => setQuestion(e.target.value)} placeholder="Leave blank for a company overview" maxLength={2000}/></div><button className="primary-button" type="submit" disabled={asking || loading}>{asking ? <LoaderCircle size={17} className="spin"/> : <Search size={17}/>}Ask FINN <ArrowRight size={16}/></button></form>
          <div className="suggestions"><span>Try a company</span>{[...new Set([...workspace.portfolio.map(c => c.ticker), ...Object.keys(snapshot.briefs)])].filter(t => !t.startsWith("MOCK")).slice(0, 6).map(t => <button key={t} disabled={loading} onClick={() => void ask(t)}>{symbolText(t)}<ArrowUpRight size={11}/></button>)}</div>
          {researchError && <div className="error-panel" role="alert"><CircleHelp size={18}/><div><strong>Research could not finish</strong><p>{researchError}</p><button onClick={() => void ask()}>Retry research <RefreshCw size={13}/></button></div></div>}
          {asking && <div className="research-loading" role="status"><div className="loading-orbit"><BookOpen size={27}/></div><h2>Preparing research</h2><p>{progress}</p><button className="text-button" onClick={() => {requestRef.current?.abort(); setAsking(false);}}>Cancel research</button></div>}
          {!asking && brief?.status === "needs_sources" && <div className="empty-state"><BookOpen size={30}/><h3>No reports found yet.</h3><p>No usable annual reports or transcripts were found for this company. Try another company or retry later.</p></div>}
          {!asking && brief && brief.status !== "needs_sources" && <><div className="brief-header"><div className="company-row"><span className="company-mark large">{brief.ticker.slice(0, 2)}</span><div><div className="eyebrow">RESEARCH BRIEF</div><h2>{clean(brief.company_name && brief.company_name !== brief.ticker ? brief.company_name : companyName(brief.ticker))}</h2><span>{brief.ticker} · Primary-source research</span></div></div><div className="brief-coverage"><strong>{brief.coverage.documents} documents</strong><span>{brief.coverage.transcripts} transcripts · {brief.coverage.annual_reports} annual reports</span></div></div>
            <nav id="research-overview" className="research-overview" aria-label="Research overview" tabIndex={-1}><h2>At a glance</h2>
              {brief.sections.map(section => <div className="research-summary-item" key={section.id}><a className="summary-jump" href={`#research-${section.id}`}><strong>{section.title}</strong><p>{section.findings.length ? readerText(section.findings[0].text) : section.empty_message}</p><ArrowRight size={16}/></a>{section.findings.some(finding => finding.citation_ids.some(id => brief.sources.some(source => source.citation_id === id))) && <a className="summary-sources" href={`#research-${section.id}-sources`} aria-label={`View sources for ${section.title}`}><FileText size={12}/>Sources</a>}</div>)}
            </nav>
            <div className="research-layout"><div className="brief-main">
              {brief.sections.map(section => {
                const ids = new Set([...section.findings.flatMap(finding => finding.citation_ids), ...(section.id === "guidance" ? brief.guidance.flatMap(row => row.citation_ids) : [])]);
                const sources = brief.sources.filter(source => ids.has(source.citation_id)).filter((source, i, all) => all.findIndex(other => other.document_id === source.document_id) === i);
                return <section id={`research-${section.id}`} aria-labelledby={`research-title-${section.id}`} tabIndex={-1} className="brief-section" key={section.id}><div className="section-title"><span>{String(brief.sections.findIndex(s => s.id === section.id) + 1).padStart(2, "0")}</span><h3 id={`research-title-${section.id}`}>{section.title}</h3></div>
                {section.id === "financial" && !!brief.financials.length && <FinancialTable records={brief.financials}/>}
                {section.id === "guidance" && <><GuidanceChart brief={brief}/>{latestComparison && <div className="guidance-callout"><span className={latestComparison.status === "missed" ? "negative-icon" : "positive-icon"}>{latestComparison.status === "missed" ? <ArrowDownRight size={21}/> : <ArrowUpRight size={21}/>}</span><div><strong>{latestComparison.period}: {latestComparison.status === "missed" ? "below" : latestComparison.status === "exceeded" ? "above" : "within"} guidance</strong><p>{latestComparison.guided_low}% guided · {latestComparison.actual}% delivered · {number(Math.abs(latestComparison.delta || 0), 1)} percentage {Math.abs(latestComparison.delta || 0) === 1 ? "point" : "points"}{citations(latestComparison.citation_ids)}</p></div></div>}</>}
                {section.findings.length ? section.findings.map((finding, index) => <p className="finding" key={index}>{readerText(finding.text)}{citations(finding.citation_ids)}</p>) : <p className="empty-note">{section.empty_message}</p>}
                {!!sources.length && <div id={`research-${section.id}-sources`} tabIndex={-1} className="section-sources"><h4>Original sources</h4>{sources.map(source => <a key={source.document_id} href={source.url + (source.page ? `#page=${source.page}` : "")} target="_blank" rel="noopener noreferrer" title={sourceTitle(source.title)}><FileText size={13}/><span>{sourceTitle(source.title)}{source.page != null && ` · p. ${source.page}`}</span><ExternalLink size={13}/></a>)}</div>}
                <a className="back-to-overview" href="#research-overview">Back to overview</a>
              </section>;})}
              {!!brief.gaps.length && <section className="gaps-panel"><h3><CircleHelp size={16}/>What the sources don’t establish</h3><ul>{[...new Set(brief.gaps.map(researchGap))].map((gap, i) => <li key={i}>{gap}</li>)}</ul></section>}
            </div><aside className="research-rail">{!!brief.network.length && <section className="rail-card"><div className="rail-heading"><Users size={17}/><h2>Relevant contacts</h2></div><p className="rail-intro">Selected from company links and professional expertise.</p>{brief.network.map(p => <button className="research-person" key={p.contact_id} onClick={() => showPersonId(p.contact_id)}><Avatar person={p}/><div><strong>{clean(p.name)}</strong><span>{p.reasons[0]}</span></div><ChevronRight size={13}/></button>)}</section>}<section className="rail-card"><div className="rail-heading"><FileText size={17}/><h2>Source library</h2></div>{brief.sources.filter((s, i, all) => all.findIndex(x => x.document_id === s.document_id) === i).map(s => <button className="source-row" key={s.document_id} onClick={() => setDetail({kind: "source", source: s})}><FileText size={17}/><div><strong>{sourceTitle(s.title)}</strong><span>{s.kind === "financial_table" ? "Structured observation" : dateText(s.published_on)}</span></div><ArrowUpRight size={13}/></button>)}</section></aside></div></>}
        </section>}

        {tab === "people" && <section className="people-page"><div className="page-heading compact"><div><h1>Your network</h1><p>Find someone who can help you understand a company.</p></div><span className="outline-badge"><Users size={14}/>{people.length} profiles</span></div><div className="people-toolbar"><div className="search-field"><Search size={18}/><input aria-label="Search people" placeholder="Search a name, company or area of expertise" value={peopleQuery} onChange={e => setPeopleQuery(e.target.value)}/>{peopleQuery && <button className="icon-button" aria-label="Clear people search" onClick={() => setPeopleQuery("")}><X size={14}/></button>}</div><span><Filter size={13}/>{filteredPeople.length} {filteredPeople.length === 1 ? "person" : "people"}</span></div><div className="expertise-filters">{["All people", "IT services", "specialty chemicals", "banking", "retail"].map(topic => <button className={peopleQuery === topic || (!peopleQuery && topic === "All people") ? "selected" : ""} key={topic} onClick={() => setPeopleQuery(topic === "All people" ? "" : topic)}>{topic}</button>)}</div><div className="people-grid">{filteredPeople.map(p => <button key={p.id} className="person-card" onClick={() => void openPerson(p)}><div className="person-card-top"><Avatar person={p}/><span className="subtle-badge">{p.direct_contact === false ? "Research subject" : "Your contact"}</span><ArrowUpRight size={16}/></div><h3>{personName(p)}</h3><p>{p.roles[0]?.title || "Independent perspective"}{p.roles[0] && <span>{clean(p.roles[0].company)}</span>}</p><div className="expertise-tags">{p.expertise.slice(0, 2).map(tag => <span key={tag}>{tag}</span>)}{!p.expertise.length && <span>{p.knows.length ? "Recorded connection" : "Professional background"}</span>}</div><div className="person-card-bottom"><span><GitBranch size={12}/>{p.knows.length ? `${p.knows.length} recorded ${p.knows.length === 1 ? "connection" : "connections"}` : "Explore shared context"}</span><ChevronRight size={13}/></div></button>)}</div>{!filteredPeople.length && <div className="empty-state"><Search size={28}/><h3>No profiles match that search.</h3><p>Try a company name or a broader area of expertise.</p><button className="secondary-button" onClick={() => setPeopleQuery("")}>Show all people <ArrowRight size={14}/></button></div>}</section>}
      </main><footer className="workspace-footer"><span className="mini-brand">finn✳</span><span>Filings · Research · Network</span><button onClick={() => setDetail({kind: "about"})}>Sources & privacy <ArrowUpRight size={11}/></button></footer></div>
    <nav className="bottom-nav" aria-label="Mobile navigation">{nav.map(n => <button className={tab === n.id ? "active" : ""} key={n.id} onClick={() => navigate(n.id)} aria-current={tab === n.id ? "page" : undefined}><n.icon size={20}/><span>{n.label}</span></button>)}</nav>
    {!!notice && <div className="toast" role="status"><span>{notice}</span><button aria-label="Dismiss notification" onClick={() => setNotice("")}><X size={15}/></button></div>}

    {detail && <Dialog title={detail.kind === "source" ? "Source excerpt" : detail.kind === "person" ? "Contact details" : detail.kind === "settings" ? "Alert preferences" : detail.kind === "about" ? "About FINN" : detail.kind === "portfolio" ? "Manage portfolio" : detail.item.type === "news" ? "News details" : "Filing details"} wide={detail.kind === "source" || detail.kind === "event"} onClose={() => setDetail(null)}>
      {detail.kind === "source" && <><span className="category-tag">{label(detail.source.kind)}</span><h3 className="dialog-title">{sourceTitle(detail.source.title)}</h3><p className="muted">{dateText(detail.source.published_on)}{detail.source.page != null && ` · Original page ${detail.source.page}`}</p>{detail.source.financial_record ? <FinancialTable records={[detail.source.financial_record]}/> : <blockquote className="source-excerpt">{detail.source.text}</blockquote>}{detail.source.mode === "live" && detail.source.url && <a className="primary-button inline-button" href={detail.source.url + (detail.source.page ? `#page=${detail.source.page}` : "")} target="_blank" rel="noopener noreferrer">Open original document <ExternalLink size={14}/></a>}</>}
      {detail.kind === "person" && <><div className="profile-heading"><Avatar person={detail.person}/><div><h3>{personName(detail.person)}</h3></div></div>{path.length ? <section className="profile-section"><h4><GitBranch size={16}/>Your route to this person</h4>{path.map((p, i) => <div className="intro-path" key={i}>{p.names.map((name, j) => <span key={j}>{j > 0 && <ArrowRight size={15}/>}<strong>{j === 0 ? "You" : clean(name).split(" ")[0]}</strong></span>)}<small>{p.hops === 1 ? "Direct" : "One introduction"} · recorded connections</small></div>)}</section> : <p className="empty-note">No recorded introduction path is available. Shared employment or education alone does not establish acquaintance.</p>}{!!profileOverlaps.length&&<section className="profile-section"><h4>People with shared professional history</h4>{profileOverlaps.slice(0,6).map(person=><button className="research-person" key={person.person_id} onClick={()=>showPersonId(person.person_id)}><Avatar person={person}/><div><strong>{clean(person.name)}</strong><span>{[...person.work.map(role=>`${role.company} · ${role.start_year}–${role.end_year}`),...person.education.map(education=>`${education.institution}${education.start_year!=null?` · ${education.start_year}–${education.end_year}`:""}`)].join("; ")}</span></div><ChevronRight size={13}/></button>)}</section>}<section className="profile-section"><h4>Professional timeline</h4><div className="timeline">{detail.person.roles.map((role, i) => <div key={i}><i/><span>{role.start_year} — {role.end_year || "present"}</span><strong>{role.title}</strong><p>{clean(role.company)}</p></div>)}</div>{!detail.person.roles.length && <p className="empty-note">No employment history supplied.</p>}</section><section className="profile-section"><h4>Areas of expertise</h4><div className="expertise-tags">{detail.person.expertise.map(tag => <span key={tag}>{tag}</span>)}</div></section>{!!detail.person.education.length && <section className="profile-section"><h4>Education</h4>{detail.person.education.map((e, i) => <p key={i}>{typeof e === "string" ? e : `${e.institution} · ${e.start_year}–${e.end_year}`}</p>)}</section>}{detail.person.notes && <p className="empty-note">{detail.person.notes}</p>}</>}
      {detail.kind === "event" && <><div className="company-row"><span className="company-mark">{symbolText(detail.item.ticker).slice(0, 2)}</span><div><strong>{clean(companyName(detail.item.ticker))}</strong><span>{symbolText(detail.item.ticker)} · {dateText(detail.item.published_at)}</span></div></div><h3 className="dialog-title">{clean(detail.item.title || detail.item.summary)}</h3>{detail.item.url&&<div className="dialog-actions"><a className="primary-button" href={filingUrl(detail.item)} target="_blank" rel="noopener noreferrer">{detail.item.type==="news"?"Read article":"Open filing"}<ExternalLink size={14}/></a>{detail.item.type!=="news"&&filingUrl(detail.item)!==detail.item.url&&<a className="secondary-button" href={detail.item.url} target="_blank" rel="noopener noreferrer">Source website<ExternalLink size={14}/></a>}</div>}{detail.item.type === "news" ? <p className="muted">{detail.item.source?.publisher}</p> : <p className="detail-copy">{detail.item.body || detail.item.summary}</p>}
        {detail.item.enrichment?.results && <><FinancialTable records={[detail.item.enrichment.results.period]}/><div className="comparison-grid">{["revenue", "ebitda", "pbt", "pat"].map(metric => <div key={metric}><strong>{metric.toUpperCase()}</strong>{["qoq","yoy"].map(comparison=><span key={comparison}>{comparison==="qoq"?"Last quarter":"Year-ago quarter"}: <b>{number(detail.item.enrichment?.results?.comparisons[comparison]?.[metric]?.previous)}</b> · {detail.item.enrichment?.results?.comparisons[comparison]?.[metric]?.percent==null?"Change unavailable":`${number(detail.item.enrichment.results.comparisons[comparison][metric].percent,1)}%`}</span>)}</div>)}</div><div className="quality-panel"><h4>Reference cross-check</h4><p>Available reference figures are compared only when period, basis, units and currency match.</p>{Object.entries(detail.item.enrichment.results.cross_check.metrics || {}).map(([metric, check]) => <div key={metric}><span>{metric.toUpperCase()}</span><strong className={check.status === "mismatch" ? "negative" : ""}>{check.status === "match" ? "Figures agree" : check.status === "mismatch" ? `${number(check.difference_percent, 1)}% difference` : "Reference unavailable"}</strong></div>)}</div></>}
        {detail.item.enrichment?.management && <>{detail.item.enrichment.management.incoming&&<section className="incoming-profile"><h4>Incoming person</h4><strong>{detail.item.enrichment.management.incoming.name}</strong><span>{detail.item.enrichment.management.incoming.title}</span><p>{detail.item.enrichment.management.incoming.bio||"No background was supplied in this filing."}</p><a href={detail.item.url} target="_blank" rel="noopener noreferrer">Read the source filing <ExternalLink size={12}/></a></section>}<h4 className="detail-subheading">Recorded introduction</h4>{detail.item.enrichment.management.paths.map((p, i) => <div className="intro-path" key={i}>{p.names.map((name, j) => <span key={j}>{j > 0 && <ArrowRight size={15}/>}<strong>{j === 0 ? "You" : clean(name)}</strong></span>)}</div>)}{!!detail.item.enrichment.management.overlaps.length && <div className="overlap-panel"><h4>Shared professional context</h4>{detail.item.enrichment.management.overlaps.flatMap(o => [...o.work.map(w=>({label:w.company,detail:`${w.start_year}–${w.end_year} · employment overlap`})),...o.education.map(e=>({label:e.institution,detail:e.start_year!=null?`${e.start_year}–${e.end_year} · education overlap`:"Shared institution; dates unavailable"}))].map((w, i) => <div key={`${o.person_id}-${i}`}><span>{clean(o.name)}</span><strong>{w.label}</strong><p>{w.detail}</p><small>Overlap is not proof of acquaintance.</small></div>))}</div>}</>}
        {!!detail.item.enrichment?.management?.professional_context?.length&&<section className="profile-section"><h4>Shared employer or education</h4>{detail.item.enrichment.management.professional_context.map(person=><button className="research-person" key={person.person_id} onClick={()=>showPersonId(person.person_id)}><Avatar person={person}/><div><strong>{clean(person.name)}</strong><span>{person.reasons.join(" ")}</span></div><ChevronRight size={14}/></button>)}</section>}
        {!!detail.item.enrichment?.gaps.length && <div className="gaps-panel"><h4>What’s missing</h4>{detail.item.enrichment.gaps.map((g, i) => <p key={i}>{researchGap(g)}</p>)}</div>}{!!detail.item.network.length&&<h4 className="detail-subheading">People who could add context</h4>}{detail.item.network.map(p => <button className="research-person" key={p.contact_id} onClick={() => showPersonId(p.contact_id)}><Avatar person={p}/><div><strong>{clean(p.name)}</strong><span>{p.reasons.join(" ")}</span></div><ChevronRight size={14}/></button>)}{detail.item.mode === "live" && detail.item.type !== "news" && !detail.item.ticker.startsWith("US-") && ["results","management_change","M&A","capex","litigation"].includes(detail.item.category||"") && <div className="filing-extraction"><button className="secondary-button" disabled={enriching} onClick={async()=>{setEnriching(true);setEventError("");try{const enrichment=await api<NonNullable<FeedItem["enrichment"]>>(`announcements/${detail.item.id}/enrich`,{method:"POST"});setDetail({kind:"event",item:{...detail.item,enrichment}});void loadBackend(windowDays,snapshot);}catch{setEventError("Analysis couldn’t be completed. You can still open the filing above.");}finally{setEnriching(false);}}}><FileText size={15}/>{enriching?"Analysing filing…":"Analyse filing"}</button>{eventError&&<p className="negative" role="alert">{eventError}</p>}</div>}<div className="dialog-actions"><button className="primary-button" onClick={() => {const symbol = detail.item.ticker; setDetail(null); void ask(symbol);}}>Research this company <ArrowRight size={15}/></button></div></>}
      {detail.kind === "portfolio" && <PortfolioForm companies={workspace.portfolio} connected={connected} onSave={async companies => {await api("portfolio", {method:"PUT",body:JSON.stringify({companies})}); const added=companies.filter(company=>!workspace.portfolio.some(old=>old.ticker===company.ticker)); setWorkspace({...workspace,portfolio:companies}); setDetail(null); if(added.length){setWindowDays(7);void refresh(added,7);}else{await loadBackend(windowDays,snapshot);setNotice("Portfolio saved.");}}}/>}
      {detail.kind === "settings" && <SettingsForm settings={workspace.settings} connected={connected} onSave={async value => {if (connected) await api("alerts/settings", {method: "PUT", body: JSON.stringify(value)}); else localStorage.setItem("finn-demo-alerts", JSON.stringify(value)); setWorkspace({...workspace, settings: value}); setNotice(connected ? "Alert preferences saved." : "Preferences saved on this device. Reconnect to sync them."); setDetail(null); if (connected) void loadBackend(windowDays, snapshot);}}/>}
      {detail.kind === "about" && <div className="about-copy"><h3>About FINN</h3><p>Follow portfolio updates, research Indian and US companies, and find a contact who can help.</p><h4>Sources</h4><p>Portfolio news links to publisher articles. Research uses annual reports, earnings call transcripts and Screener financial tables. Tap a citation to read the evidence. Missing information stays visible.</p><h4>People and company data</h4><p>Contact profiles, professional histories and relationships are synthetic. Company financials and research use original public sources, including when viewing saved data offline.</p><h4>Privacy</h4><p>Contact profiles are not shared when researching companies. Introduction paths use recorded relationships. Shared employers or education alone do not establish a connection.</p></div>}
    </Dialog>}
  </div>;
}

function SettingsForm({settings, connected, onSave}: {settings: Settings; connected: boolean; onSave: (value: Settings) => Promise<void>}) {
  const [draft, setDraft] = useState(settings);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  return <form className="settings-form" onSubmit={async e => {e.preventDefault(); setSaving(true); try {await onSave(draft);} catch (error) {setError(error instanceof Error ? error.message : "Could not save preferences");} finally {setSaving(false);}}}><p>Decide what deserves a place in your brief. Thresholds use completed daily observations.</p><label>Daily price movement<span>Notify when the close moves at least</span><div className="number-control"><input aria-label="Price threshold" type="number" min="0.1" max="100" step="0.1" value={draft.price_change_percent} onChange={e => setDraft({...draft, price_change_percent: Number(e.target.value)})}/><b>%</b></div></label><label>Unusual trading volume<span>Compared with the preceding trading-day average</span><div className="number-control"><input aria-label="Volume threshold" type="number" min="1.1" max="100" step="0.1" value={draft.volume_multiple} onChange={e => setDraft({...draft, volume_multiple: Number(e.target.value)})}/><b>×</b></div></label><label>Volume baseline<span>Requires the full number of prior observations</span><div className="number-control"><input aria-label="Volume baseline" type="number" min="2" max="90" value={draft.volume_lookback_days} onChange={e => setDraft({...draft, volume_lookback_days: Number(e.target.value)})}/><b>days</b></div></label><fieldset><legend>Filings that matter to you</legend>{["results", "management_change", "M&A", "capex", "litigation", "fund_raise", "credit_rating"].map(category => <label className="checkbox-row" key={category}><input type="checkbox" checked={draft.material_categories.includes(category)} onChange={e => setDraft({...draft, material_categories: e.target.checked ? [...draft.material_categories, category] : draft.material_categories.filter(c => c !== category)})}/>{label(category)}</label>)}</fieldset>{!connected && <p className="empty-note">You’re offline. Changes will be saved on this device.</p>}{error && <p className="negative" role="alert">{error}</p>}<button type="submit" className="primary-button" disabled={saving}>{saving ? <LoaderCircle className="spin" size={15}/> : <Check size={15}/>}Save preferences</button></form>;
}

function PortfolioForm({companies,connected,onSave}:{companies:Company[];connected:boolean;onSave:(companies:Company[])=>Promise<void>}) {
 const [adding,setAdding]=useState(false);const [draft,setDraft]=useState(companies);const [symbol,setSymbol]=useState("");const [error,setError]=useState("");const [saving,setSaving]=useState(false);
 async function addCompany(){
  if(adding||saving||!connected)return;
  if(!symbol.trim()){setError("Enter a company name or ticker.");return;}
  if(draft.length>=50){setError("Your portfolio can hold up to 50 companies. Remove one before adding another.");return;}
  setAdding(true);setError("");
  try{
   const company=await api<Company>("portfolio/resolve",{method:"POST",body:JSON.stringify({query:symbol.trim()})});
   if(draft.some(old=>old.ticker===company.ticker)){setError("This company is already in your portfolio.");return;}
   setDraft([...draft,company]);setSymbol("");
  }catch(error){setError(error instanceof Error?error.message:"Could not find this company. Please try again.");}
  finally{setAdding(false);}
 }

 return <form className="portfolio-form" onSubmit={async event=>{event.preventDefault();setSaving(true);setError("");try{await onSave(draft);}catch(error){setError(error instanceof Error?error.message:"Could not save portfolio");}finally{setSaving(false);}}}><p>Follow Indian and US companies for news, filings and price alerts.</p><div className="portfolio-add"><label htmlFor="add-ticker">Company name or ticker</label><div><input id="add-ticker" onKeyDown={event=>{if(event.key==="Enter"){event.preventDefault();addCompany();}}} value={symbol} onChange={e=>setSymbol(e.target.value)} placeholder="e.g. Infosys or NVIDIA" maxLength={120} disabled={adding||saving||!connected}/><button type="button" className="secondary-button" onClick={()=>void addCompany()} disabled={adding||saving||!connected}>{adding?<><LoaderCircle size={14} className="spin"/>Finding company…</>:"Add company"}</button></div></div><p aria-live="polite">{draft.length} {draft.length===1?"company":"companies"}</p><div className="portfolio-list">{draft.map(company=><div key={symbolText(company.ticker)}><span className="company-mark">{symbolText(company.ticker).slice(0,2)}</span><div><strong>{symbolText(company.ticker)}</strong><span>{clean(company.name)}</span></div><button type="button" className="icon-button" aria-label={`Remove ${symbolText(company.ticker)}`} onClick={()=>setDraft(draft.filter(c=>c.ticker!==company.ticker))}><X size={17}/></button></div>)}</div>{error&&<p className="negative" role="alert">{error}</p>}{!connected&&<p className="empty-note">Reconnect to save portfolio changes.</p>}<button type="submit" className="primary-button" disabled={!connected||saving||adding||!draft.length||draft.length>50}>{saving?<LoaderCircle size={16} className="spin"/>:<Check size={16}/>}Save portfolio</button></form>;
}
