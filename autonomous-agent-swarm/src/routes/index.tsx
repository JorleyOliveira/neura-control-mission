import { createFileRoute } from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Header } from "@/components/neura/Header";
import { RunsSidebar } from "@/components/neura/RunsSidebar";
import { ChatColumn } from "@/components/neura/ChatColumn";
import { NetworkMap } from "@/components/neura/NetworkMap";
import { Timeline } from "@/components/neura/Timeline";
import { Negotiations } from "@/components/neura/Negotiations";
import {
  DEFAULT_API,
  base,
  checkHealth,
  fetchEvents,
  fetchNegotiations,
  fetchRun,
  fetchRuns,
  fetchSessionMessages,
  fetchVoiceConfig,
  loadApiUrl,
  postChat,
  saveApiUrl,
} from "@/lib/neura/api";
import type {
  ChatMessage,
  MarketplaceEvent,
  Negotiation,
  Run,
  VoiceConfig,
} from "@/lib/neura/types";
import { runId } from "@/lib/neura/types";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "NEURA Mission Control — Autonomous Agent Console" },
      {
        name: "description",
        content:
          "Live mission control for an autonomous AI agent marketplace: speak a goal, watch agents get hired, delegate, verify and negotiate in real time.",
      },
      { property: "og:title", content: "NEURA Mission Control" },
      {
        property: "og:description",
        content:
          "Voice console where JARVIS delegates your business goal to a self-organizing mesh of AI agents.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: MissionControl,
});

const asEvent = (raw: Record<string, unknown>): MarketplaceEvent => ({
  seq: Number(raw["seq"] ?? 0),
  event_type: String(raw["event_type"] ?? raw["type"] ?? "EVENT"),
  actor: raw["actor"] === undefined || raw["actor"] === null ? undefined : String(raw["actor"]),
  payload:
    raw["payload"] && typeof raw["payload"] === "object"
      ? (raw["payload"] as Record<string, unknown>)
      : {},
  ts: raw["ts"] === undefined || raw["ts"] === null ? undefined : String(raw["ts"]),
  received_at: Date.now(),
});

function textOf(value: unknown): string | null {
  if (value === undefined || value === null) return null;
  if (typeof value === "string") return value;
  if (typeof value === "object") {
    const o = value as Record<string, unknown>;
    for (const k of ["answer", "text", "summary", "result", "content", "message"]) {
      if (typeof o[k] === "string") return o[k] as string;
    }
    return JSON.stringify(value, null, 2);
  }
  return String(value);
}

function MissionControl() {
  const [apiUrl, setApiUrl] = useState(DEFAULT_API);
  const [connected, setConnected] = useState(false);
  const [runs, setRuns] = useState<Run[]>([]);
  const [runsLoading, setRunsLoading] = useState(true);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<MarketplaceEvent[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [finalResult, setFinalResult] = useState<string | null>(null);
  const [voiceConfig, setVoiceConfig] = useState<VoiceConfig | null>(null);
  const [negotiations, setNegotiations] = useState<Negotiation[]>([]);
  const [tab, setTab] = useState<"timeline" | "negotiation">("timeline");

  const lastSeqRef = useRef(0);
  const doneRef = useRef(false);

  useEffect(() => {
    setApiUrl(loadApiUrl());
  }, []);

  const updateApiUrl = useCallback((v: string) => {
    setApiUrl(v);
    saveApiUrl(v);
  }, []);

  // health polling
  useEffect(() => {
    let alive = true;
    const ping = async () => {
      try {
        const ok = await checkHealth(apiUrl);
        if (alive) setConnected(ok);
      } catch {
        if (alive) setConnected(false);
      }
    };
    void ping();
    const t = setInterval(() => void ping(), 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [apiUrl]);

  // runs list
  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const list = await fetchRuns(apiUrl);
        if (alive) setRuns(list);
      } catch {
        if (alive) setRuns([]);
      } finally {
        if (alive) setRunsLoading(false);
      }
    };
    setRunsLoading(true);
    void load();
    const t = setInterval(() => void load(), 5000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [apiUrl]);

  // voice config
  useEffect(() => {
    let alive = true;
    fetchVoiceConfig(apiUrl)
      .then((c) => alive && setVoiceConfig(c))
      .catch(() => alive && setVoiceConfig({ configured: false }));
    return () => {
      alive = false;
    };
  }, [apiUrl]);

  // hydrate + stream the selected run
  useEffect(() => {
    if (!selectedRunId) return;
    let alive = true;
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    lastSeqRef.current = 0;
    doneRef.current = false;
    setEvents([]);
    setNegotiations([]);
    setTab("timeline");
    setFinalResult(null);

    const refreshRun = async () => {
      try {
        const run = await fetchRun(apiUrl, selectedRunId);
        if (!alive) return;
        setSelectedRun(run);
        setFinalResult(textOf(run.final_result));
        if (run.session_id) {
          setSessionId(String(run.session_id));
          try {
            const msgs = await fetchSessionMessages(apiUrl, String(run.session_id));
            if (alive && msgs.length) setMessages(msgs);
          } catch {
            /* tolerate */
          }
        }
      } catch {
        /* tolerate */
      }
    };

    const connect = () => {
      if (!alive || doneRef.current) return;
      source = new EventSource(
        `${base(apiUrl)}/api/runs/${selectedRunId}/events?after=${lastSeqRef.current}`,
      );
      source.addEventListener("marketplace", (e) => {
        try {
          const raw = JSON.parse((e as MessageEvent).data as string) as Record<string, unknown>;
          const ev = asEvent(raw);
          if (ev.seq <= lastSeqRef.current) return;
          lastSeqRef.current = ev.seq;
          setEvents((prev) => [...prev, ev].slice(-200));
          if (
            ev.event_type.toUpperCase() === "WORKER_PROGRESS" &&
            String(ev.payload?.["tool"] ?? "") === "a2a.call"
          ) {
            setTab((cur) => cur);
          }
        } catch {
          /* ignore malformed frame */
        }
      });
      source.addEventListener("done", () => {
        doneRef.current = true;
        source?.close();
        void refreshRun();
      });
      source.onerror = () => {
        source?.close();
        source = null;
        if (!doneRef.current && alive) retry = setTimeout(connect, 2000);
      };
    };

    const boot = async () => {
      try {
        const history = await fetchEvents(apiUrl, selectedRunId, 0);
        if (!alive) return;
        const mapped = history.map(asEvent).sort((a, b) => a.seq - b.seq);
        if (mapped.length) lastSeqRef.current = mapped[mapped.length - 1]!.seq;
        setEvents(mapped.slice(-200));
      } catch {
        /* tolerate */
      }
      await refreshRun();
      connect();
    };

    void boot();

    return () => {
      alive = false;
      source?.close();
      if (retry) clearTimeout(retry);
    };
  }, [apiUrl, selectedRunId]);

  const hasA2A = useMemo(
    () =>
      events.some(
        (e) =>
          e.event_type.toUpperCase() === "WORKER_PROGRESS" &&
          String(e.payload?.["tool"] ?? "") === "a2a.call",
      ),
    [events],
  );

  const runActive = useMemo(() => {
    const status = String(selectedRun?.status ?? "").toLowerCase();
    return status === "running" || status === "accepted" || !doneRef.current;
  }, [selectedRun]);

  // negotiations polling
  useEffect(() => {
    if (!selectedRunId || !hasA2A) return;
    let alive = true;
    const load = async () => {
      try {
        const list = await fetchNegotiations(apiUrl, selectedRunId);
        if (alive) setNegotiations(list);
      } catch {
        /* tolerate */
      }
    };
    void load();
    if (!runActive) return;
    const t = setInterval(() => void load(), 3000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [apiUrl, selectedRunId, hasA2A, runActive]);

  const selectRun = useCallback((id: string) => {
    setSelectedRunId(id);
  }, []);

  const handleSend = useCallback(
    async (text: string) => {
      setMessages((prev) => [...prev, { id: `u-${Date.now()}`, role: "user", content: text }]);
      setSending(true);
      try {
        const res = await postChat(apiUrl, text, sessionId);
        if (res.session_id) setSessionId(String(res.session_id));
        const status = String(res.status ?? "");
        const reply = res.question ?? res.message ?? res.reply;
        if (reply) {
          setMessages((prev) => [
            ...prev,
            { id: `j-${Date.now()}`, role: "jarvis", content: String(reply) },
          ]);
        }
        if (status === "accepted" && res.run_id) {
          setMessages((prev) => [
            ...prev,
            {
              id: `s-${Date.now()}`,
              role: "system",
              content: "Delegated to MARCELO — Run started",
            },
          ]);
          setSelectedRunId(String(res.run_id));
          void fetchRuns(apiUrl)
            .then(setRuns)
            .catch(() => undefined);
        }
      } catch (e) {
        setMessages((prev) => [
          ...prev,
          {
            id: `e-${Date.now()}`,
            role: "system",
            content: `request failed — ${e instanceof Error ? e.message : "unknown error"}`,
          },
        ]);
      } finally {
        setSending(false);
      }
    },
    [apiUrl, sessionId],
  );

  return (
    <div className="flex h-screen flex-col bg-[#0B0F1A] text-foreground">
      <Header apiUrl={apiUrl} connected={connected} onApiUrlChange={updateApiUrl} />
      <main className="flex min-h-0 flex-1 gap-3 px-4 pb-4">
        <RunsSidebar
          runs={runs}
          loading={runsLoading}
          selectedId={selectedRunId}
          onSelect={selectRun}
        />
        <ChatColumn
          messages={messages}
          finalResult={finalResult}
          sending={sending}
          voiceConfig={voiceConfig}
          apiUrl={apiUrl}
          disabled={!connected}
          onSend={(t) => void handleSend(t)}
        />
        <section className="flex min-w-0 flex-1 flex-col gap-3">
          <NetworkMap events={events} connected={connected} />
          <div className="glass flex min-h-0 flex-[55] flex-col overflow-hidden rounded-xl">
            <div className="flex items-center gap-1 border-b border-border px-2 py-1.5">
              <button
                type="button"
                onClick={() => setTab("timeline")}
                className={`transition-console rounded px-2 py-1 font-mono text-[11px] uppercase tracking-[0.18em] ${
                  tab === "timeline" ? "bg-white/10 text-foreground" : "text-muted-foreground"
                }`}
              >
                activity
              </button>
              {hasA2A && (
                <button
                  type="button"
                  onClick={() => setTab("negotiation")}
                  className={`transition-console rounded px-2 py-1 font-mono text-[11px] uppercase tracking-[0.18em] ${
                    tab === "negotiation" ? "bg-seller/15 text-seller" : "text-seller/70"
                  }`}
                >
                  negotiation
                </button>
              )}
              <span className="ml-auto pr-2 font-mono text-[10px] text-muted-foreground">
                {events.length} events
              </span>
            </div>
            <div className="min-h-0 flex-1">
              {tab === "timeline" ? (
                <Timeline events={events} connected={connected} />
              ) : (
                <Negotiations negotiations={negotiations} />
              )}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}
