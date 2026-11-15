import type { Brief } from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number) {super(message);}
}

export class ResearchError extends Error {}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api/${path}`, {cache: "no-store", ...init, headers: {"Content-Type": "application/json", ...init?.headers}});
  if (!response.ok) {
    let message="This request couldn’t be completed. Please try again.";
    if(response.status===422){
      const body=await response.json().catch(()=>({}));
      if(typeof body.detail==="string"&&body.detail.startsWith("Company not found"))message="Company not found. Try its full name or ticker.";
    }
    throw new ApiError(message,response.status);
  }
  return response.json();
}

export function isPrimaryBrief(brief: Brief): boolean {
  return brief.mode === "live" && brief.sources.every(source => source.mode === "live" && source.url.startsWith("https://") && (!source.financial_record || source.financial_record.mode === "live")) && brief.financials.every(row => row.mode === "live");
}

export async function research(ticker: string, body: object, progress: (text: string) => void, signal: AbortSignal): Promise<Brief> {
  const response = await fetch(`/api/research/${encodeURIComponent(ticker)}/brief`, {method: "POST", signal, headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  if (!response.ok || !response.body) throw new ResearchError("Research is unavailable right now. Please try again.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result: Brief | null = null;
  while (true) {
    const {done, value} = await reader.read();
    buffer += decoder.decode(value, {stream: !done});
    const lines = buffer.split("\n"); buffer = lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.type === "progress") progress("Reading company reports and transcripts…");
      if (event.type === "error") throw new ResearchError(typeof event.data === "string" && event.data.startsWith("Company not found") ? "Company not found. Try its full name or ticker." : "Research couldn’t be completed. Please try again.");
      if (event.type === "result") result = event.data;
    }
    if (done) break;
  }
  if (!result) throw new ResearchError("Research ended without a result. Please retry.");
  if (!isPrimaryBrief(result)) throw new ResearchError("Research returned non-primary sources. Please retry.");
  return result;
}
