import type { ChatMessage, Negotiation, Run, VoiceConfig } from "./types";

export const DEFAULT_API = "http://localhost:18000";
const LS_KEY = "neura.apiUrl";

// The API runs on the same host as this UI (JARVIS on its canonical port).
// Local dev keeps the port-override default; any deployed origin derives itself.
function defaultApi(): string {
  if (typeof window === "undefined") return DEFAULT_API;
  const host = window.location.hostname;
  if (host === "localhost" || host === "127.0.0.1") return DEFAULT_API;
  return `${window.location.protocol}//${host}:8000`;
}

export function loadApiUrl(): string {
  if (typeof window === "undefined") return DEFAULT_API;
  const host = window.location.hostname;
  const localHost = host === "localhost" || host === "127.0.0.1";
  const saved = window.localStorage.getItem(LS_KEY);
  // A deployed origin can never reach localhost — treat such saved values as stale
  // (e.g. left over from earlier debugging) so visitors always reconnect automatically.
  if (saved && !localHost && (saved.includes("//localhost") || saved.includes("//127.0.0.1"))) {
    window.localStorage.removeItem(LS_KEY);
    return defaultApi();
  }
  return saved || defaultApi();
}

export function saveApiUrl(url: string) {
  if (typeof window !== "undefined") window.localStorage.setItem(LS_KEY, url);
}

export const base = (api: string) => api.replace(/\/+$/, "");

async function getJson<T>(url: string, signal?: AbortSignal | undefined): Promise<T> {
  const res = await fetch(url, { signal: signal ?? null });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

function asArray<T>(data: unknown, ...keys: string[]): T[] {
  if (Array.isArray(data)) return data as T[];
  if (data && typeof data === "object") {
    for (const k of keys) {
      const v = (data as Record<string, unknown>)[k];
      if (Array.isArray(v)) return v as T[];
    }
  }
  return [];
}

export async function checkHealth(api: string, signal?: AbortSignal | undefined) {
  const res = await fetch(`${base(api)}/health`, { signal: signal ?? null });
  return res.ok;
}

export async function fetchRuns(api: string, signal?: AbortSignal | undefined): Promise<Run[]> {
  const data = await getJson<unknown>(`${base(api)}/api/runs`, signal);
  return asArray<Run>(data, "runs", "items", "data");
}

export async function fetchRun(
  api: string,
  id: string,
  signal?: AbortSignal | undefined,
): Promise<Run> {
  const data = await getJson<Run | { run: Run }>(`${base(api)}/api/runs/${id}`, signal);
  return (data as { run?: Run }).run ?? (data as Run);
}

export async function fetchEvents(
  api: string,
  id: string,
  after = 0,
  signal?: AbortSignal | undefined,
) {
  const data = await getJson<unknown>(`${base(api)}/api/runs/${id}/events?after=${after}`, signal);
  return asArray<Record<string, unknown>>(data, "events", "items", "data");
}

export async function fetchNegotiations(
  api: string,
  id: string,
  signal?: AbortSignal | undefined,
): Promise<Negotiation[]> {
  const data = await getJson<unknown>(`${base(api)}/api/runs/${id}/negotiations`, signal);
  return asArray<Negotiation>(data, "negotiations", "items", "data");
}

export async function fetchVoiceConfig(
  api: string,
  signal?: AbortSignal | undefined,
): Promise<VoiceConfig> {
  return getJson<VoiceConfig>(`${base(api)}/api/voice/config`, signal);
}

export async function fetchSessionMessages(
  api: string,
  sessionId: string,
  signal?: AbortSignal | undefined,
): Promise<ChatMessage[]> {
  const data = await getJson<unknown>(`${base(api)}/api/sessions/${sessionId}/messages`, signal);
  const raw = asArray<Record<string, unknown>>(data, "messages", "items", "data");
  return raw.map((m, i) => {
    const role = String(m["role"] ?? m["sender"] ?? m["from"] ?? "jarvis").toLowerCase();
    return {
      id: String(m["id"] ?? `${sessionId}-${i}`),
      role: role === "user" || role === "human" ? "user" : role === "system" ? "system" : "jarvis",
      content: String(m["content"] ?? m["text"] ?? m["message"] ?? ""),
    } as ChatMessage;
  });
}

export interface ChatResponse {
  status?: string;
  session_id?: string;
  run_id?: string;
  message?: string;
  reply?: string;
  question?: string;
  [k: string]: unknown;
}

export async function postChat(
  api: string,
  message: string,
  sessionId: string | null,
): Promise<ChatResponse> {
  const res = await fetch(`${base(api)}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: sessionId }),
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as ChatResponse;
}

export function relativeTime(input?: string | number): string {
  if (!input) return "";
  const t = typeof input === "number" ? input : Date.parse(input);
  if (Number.isNaN(t)) return "";
  const diff = Math.max(0, Date.now() - t) / 1000;
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

export function clockTime(input?: string | number): string {
  const t = input ? (typeof input === "number" ? input : Date.parse(input)) : Date.now();
  const d = new Date(Number.isNaN(t) ? Date.now() : t);
  return d.toLocaleTimeString("en-GB", { hour12: false });
}

export interface RtcToken {
  token: string;
  app_id?: string;
  channel?: string;
  uid?: number;
}

export async function fetchRtcToken(api: string, channel: string): Promise<RtcToken> {
  const res = await fetch(`${base(api)}/api/voice/rtc-token?channel=${encodeURIComponent(channel)}&uid=0`);
  if (!res.ok) throw new Error(`rtc-token ${res.status}`);
  return (await res.json()) as RtcToken;
}
