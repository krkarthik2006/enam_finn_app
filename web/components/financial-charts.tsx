"use client";

import {useState} from "react";
import type {Financial} from "@/lib/types";

const format = (value: number) => value.toLocaleString("en-IN", {maximumFractionDigits: 1});
const period = (value: string) => new Date(value).toLocaleDateString("en-IN", {month: "short", year: "2-digit", timeZone: "UTC"});

function Trend({title, rows, metric, margin = false}: {title: string; rows: Financial[]; metric: string; margin?: boolean}) {
  const values = rows.map(row => margin ? row.metrics.pat != null && row.metrics.revenue != null && row.metrics.revenue > 0 ? row.metrics.pat / row.metrics.revenue * 100 : null : row.metrics[metric] ?? null);
  const points = values.filter((value): value is number => value != null && Number.isFinite(value));
  if (points.length < 2) return null;
  const low = Math.min(0, ...points), high = Math.max(0, ...points), span = high - low || 1;
  const x = (index: number) => 65 + index * 310 / Math.max(1, rows.length - 1);
  const y = (value: number) => 155 - (value - low) / span * 120;
  const path = values.map((value,index)=>value==null?"":`${index>0&&values[index-1]!=null?"L":"M"}${x(index)},${y(value)}`).join(" ");
  const latest = values.findLast(value => value != null);
  return <figure className="financial-trend"><figcaption><h4>{title}</h4><strong>{latest == null ? "—" : format(latest)}{margin ? "%" : ""}</strong><span>{margin ? "PAT ÷ revenue" : `${rows[0].currency || "INR"} ${rows[0].unit}`}</span></figcaption><svg viewBox="0 0 400 200" role="img" aria-label={`${title} by period ended`}><title>{title}. {rows.map((row, index) => `${row.period_end}: ${values[index] == null ? "unavailable" : format(values[index] as number)}`).join("; ")}</title>
    {[low, low + span / 2, low + span].map(value => <g key={value}><line x1="60" x2="380" y1={y(value)} y2={y(value)} stroke="var(--line)"/><text x="2" y={y(value) + 4} fontSize="11" fill="var(--muted)">{format(value)}{margin ? "%" : ""}</text></g>)}
    <path d={path} fill="none" stroke="var(--accent)" strokeWidth="2.5"/>
    {rows.map((row, index) => <g key={row.period_end}>{values[index] != null && <a href={row.source_url} target="_blank" rel="noopener noreferrer" aria-label={`Source: ${title}, ${row.period_end}`}><circle cx={x(index)} cy={y(values[index] as number)} r="4" fill="var(--accent)" stroke="var(--surface)" strokeWidth="1.5"/><title>{row.period_end}: {format(values[index] as number)}{margin ? "%" : ` ${row.unit}`}. Open source.</title></a>}{(rows.length <= 5 || index % 2 === 0 || index === rows.length - 1) && <text x={x(index)} y="184" textAnchor="middle" fontSize="11" fill="var(--muted)">{period(row.period_end)}</text>}</g>)}
  </svg></figure>;
}

export default function FinancialCharts({records, preferAnnual = false}: {records: Financial[]; preferAnnual?: boolean}) {
  const [selected, setSelected] = useState("");
  const [profit, setProfit] = useState("pat");
  const grouped = new Map<string, Financial[]>();
  for (const row of records) {
    const key = `${row.frequency}|${row.basis}|${row.currency || "INR"}|${row.unit}`;
    const group = grouped.get(key) || [];
    if (!group.some(existing => existing.period_end === row.period_end)) group.push(row);
    grouped.set(key, group);
  }
  const groups = [...grouped.entries()].filter(([, rows]) => rows.length >= 2).sort((a,b) => Number(b[1][0].basis === "consolidated") - Number(a[1][0].basis === "consolidated") || Number(b[1][0].frequency === "quarterly") - Number(a[1][0].frequency === "quarterly"));
  if (!groups.length) return null;
  const preferred = preferAnnual ? groups.find(([, group])=>group[0].frequency === "annual") || groups[0] : groups[0];
  const key = groups.some(([id]) => id === selected) ? selected : preferred[0];
  const rows = [...(grouped.get(key) || [])].sort((a,b) => a.period_end.localeCompare(b.period_end));
  const profits = [["pat","Profit after tax"],["pbt","Profit before tax"],["ebitda","EBITDA"]].filter(([metric]) => rows.filter(row => row.metrics[metric] != null).length >= 2);
  const chosen = profits.some(([metric]) => metric === profit) ? profit : profits[0]?.[0];
  return <div className="financial-charts"><div className="financial-chart-controls"><h4>Financial trends</h4><label><span>Periods and basis</span><select value={key} onChange={event=>setSelected(event.target.value)}>{groups.map(([id, group])=><option key={id} value={id}>{group[0].frequency === "quarterly" ? "Quarterly" : "Annual"} · {group[0].basis} · {group[0].currency || "INR"} {group[0].unit}</option>)}</select></label>{profits.length > 1 && <label><span>Profit measure</span><select value={chosen} onChange={event=>setProfit(event.target.value)}>{profits.map(([metric,title])=><option key={metric} value={metric}>{title}</option>)}</select></label>}</div><div className="financial-chart-grid"><Trend title="Revenue" rows={rows} metric="revenue"/>{chosen && <Trend title={profits.find(([metric])=>metric === chosen)?.[1] || "Profit"} rows={rows} metric={chosen}/>}<Trend title="Net profit margin" rows={rows} metric="pat" margin/></div><p className="chart-source-note">Period-end dates · select a point to open its source. Net margin is calculated from PAT and revenue. Missing observations stay blank.</p></div>;
}
