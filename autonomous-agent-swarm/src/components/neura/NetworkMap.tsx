import { useEffect, useMemo, useRef, useState } from "react";
import type { MarketplaceEvent } from "@/lib/neura/types";
import { roleColor, type Role } from "@/lib/neura/eventMap";

type NodeState = "idle" | "working" | "done" | "failed";

interface GNode {
  id: string;
  label: string;
  role: Role;
  x: number;
  y: number;
  state: NodeState;
}

const g = (o: unknown, k: string): unknown =>
  o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined;
const str = (v: unknown) => (v === undefined || v === null ? undefined : String(v));

function workerKey(name: string) {
  return `w:${name.toLowerCase()}`;
}

function buildGraph(events: MarketplaceEvent[]) {
  const nodes = new Map<string, GNode>();
  nodes.set("jarvis", {
    id: "jarvis",
    label: "JARVIS",
    role: "jarvis",
    x: 400,
    y: 56,
    state: "idle",
  });
  nodes.set("marcelo", {
    id: "marcelo",
    label: "MARCELO",
    role: "marcelo",
    x: 400,
    y: 200,
    state: "idle",
  });
  nodes.set("seller", {
    id: "seller",
    label: "SELLER · FreshMart",
    role: "seller",
    x: 720,
    y: 150,
    state: "idle",
  });

  const workers: string[] = [];
  const verifiers: string[] = [];
  let finalDone = false;

  const ensureWorker = (name: string) => {
    const id = workerKey(name);
    if (!nodes.has(id)) {
      workers.push(id);
      nodes.set(id, { id, label: name, role: "worker", x: 0, y: 0, state: "idle" });
    }
    return nodes.get(id)!;
  };

  for (const ev of events) {
    const p = ev.payload ?? {};
    const t = (ev.event_type ?? "").toUpperCase();
    const actor = ev.actor ?? "";
    if (t === "GOAL_DELEGATED" || t === "GOAL_RECEIVED") {
      nodes.get("jarvis")!.state = "working";
      nodes.get("marcelo")!.state = "working";
    }
    if (t === "PLAN_CREATED" || t === "DISCOVER" || t === "EVALUATE") {
      nodes.get("marcelo")!.state = "working";
    }
    if (t === "HIRE") {
      const name = str(p["agent_name"]) ?? str(p["agent_id"]);
      if (name) ensureWorker(name);
    }
    if (t === "DELEGATE") {
      const name = str(p["agent_name"]) ?? str(p["agent_id"]);
      if (name) ensureWorker(name).state = "working";
    }
    if (t === "WORKER_PROGRESS" && actor) {
      const n = ensureWorker(actor);
      if (n.state !== "done") n.state = "working";
      if (String(p["tool"] ?? "") === "a2a.call") nodes.get("seller")!.state = "working";
      const wt = String(p["worker_event_type"] ?? "").toUpperCase();
      if (wt === "AGENT_COMPLETED") n.state = "done";
    }
    if (t === "WORKER_RESULT" && actor) ensureWorker(actor).state = "done";
    if (t === "VERIFY_HIRE" || t === "VERIFY_PASS" || t === "VERIFY_FAIL") {
      const id = `v:${str(p["task_id"]) ?? str(p["task"]) ?? verifiers.length}`;
      if (!nodes.has(id)) {
        verifiers.push(id);
        nodes.set(id, {
          id,
          label: `VERIFIER${verifiers.length > 1 ? ` ${verifiers.length}` : ""}`,
          role: "verifier",
          x: 0,
          y: 0,
          state: "working",
        });
      }
      const n = nodes.get(id)!;
      if (t === "VERIFY_PASS") n.state = "done";
      if (t === "VERIFY_FAIL") n.state = "failed";
    }
    if (t === "FINAL_RESULT") {
      finalDone = true;
      nodes.get("jarvis")!.state = "done";
      nodes.get("marcelo")!.state = "done";
    }
    if (t === "RUN_FAILED") {
      nodes.get("marcelo")!.state = "failed";
      nodes.get("jarvis")!.state = "failed";
    }
  }

  workers.forEach((id, i) => {
    const n = nodes.get(id)!;
    const count = workers.length;
    const spread = Math.min(300, 90 * Math.max(count - 1, 1));
    n.x = 400 - spread / 2 + (count === 1 ? spread / 2 : (spread / (count - 1)) * i);
    n.y = 340;
  });
  verifiers.forEach((id, i) => {
    const n = nodes.get(id)!;
    n.x = 110 + i * 90;
    n.y = 200;
  });

  return { nodes: [...nodes.values()], workers, verifiers, finalDone };
}

function activeEdgesFor(ev: MarketplaceEvent | undefined): string[] {
  if (!ev) return [];
  const t = (ev.event_type ?? "").toUpperCase();
  const p = ev.payload ?? {};
  const actor = ev.actor ?? "";
  const name = str(p["agent_name"]) ?? str(p["agent_id"]);
  switch (t) {
    case "GOAL_DELEGATED":
    case "GOAL_RECEIVED":
      return ["jarvis|marcelo"];
    case "DISCOVER":
    case "EVALUATE":
    case "HIRE":
      return name ? [`marcelo|${workerKey(name)}`] : ["marcelo|mesh"];
    case "DELEGATE":
      return name ? [`marcelo|${workerKey(name)}`] : [];
    case "WORKER_PROGRESS":
      return String(p["tool"] ?? "") === "a2a.call" && actor
        ? [`${workerKey(actor)}|seller`]
        : actor
          ? [`marcelo|${workerKey(actor)}`]
          : [];
    case "WORKER_RESULT":
      return actor ? [`${workerKey(actor)}|marcelo`] : [];
    case "FINAL_RESULT":
      return ["marcelo|jarvis"];
    default:
      return [];
  }
}

export function NetworkMap({
  events,
  connected,
}: {
  events: MarketplaceEvent[];
  connected: boolean;
}) {
  const { nodes, workers, verifiers, finalDone } = useMemo(() => buildGraph(events), [events]);
  const [live, setLive] = useState<string[]>([]);
  const [flash, setFlash] = useState(false);
  const lastSeq = useRef<number>(-1);

  const latest = events.length ? events[events.length - 1] : undefined;
  useEffect(() => {
    if (!latest || latest.seq === lastSeq.current) return;
    lastSeq.current = latest.seq;
    setLive(activeEdgesFor(latest));
    if ((latest.event_type ?? "").toUpperCase() === "FINAL_RESULT") {
      setFlash(true);
      const f = setTimeout(() => setFlash(false), 1700);
      return () => clearTimeout(f);
    }
    const timer = setTimeout(() => setLive([]), 2000);
    return () => clearTimeout(timer);
  }, [latest]);

  const byId = new Map(nodes.map((n) => [n.id, n]));
  const edges: Array<[string, string]> = [["jarvis", "marcelo"]];
  for (const w of workers) {
    edges.push(["marcelo", w]);
    edges.push([w, "seller"]);
  }
  for (const v of verifiers) edges.push(["marcelo", v]);

  const isLive = (a: string, b: string) => live.includes(`${a}|${b}`) || live.includes(`${b}|${a}`);

  return (
    <div className="glass relative min-h-0 flex-[45] overflow-hidden rounded-xl">
      <div className="absolute left-4 top-3 z-10 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        agent network
      </div>
      {flash && <div className="gold-flash pointer-events-none absolute inset-0 z-20 bg-gold/40" />}
      {!connected && events.length === 0 && (
        <div className="absolute inset-0 z-10 flex items-center justify-center font-mono text-xs text-muted-foreground">
          waiting for agents…
        </div>
      )}
      <svg
        viewBox="0 0 800 420"
        className={`h-full w-full transition-console ${!connected && events.length === 0 ? "opacity-25" : ""}`}
        preserveAspectRatio="xMidYMid meet"
      >
        {edges.map(([a, b]) => {
          const na = byId.get(a);
          const nb = byId.get(b);
          if (!na || !nb) return null;
          const active = isLive(a, b);
          return (
            <line
              key={`${a}-${b}`}
              x1={na.x}
              y1={na.y}
              x2={nb.x}
              y2={nb.y}
              stroke={active ? roleColor[nb.role] : "rgba(255,255,255,0.10)"}
              strokeWidth={active ? 2 : 1}
              className={active ? "edge-flow" : "transition-console"}
            />
          );
        })}
        {nodes.map((n) => {
          const color = roleColor[n.role];
          const dim = n.state === "idle";
          const failed = n.state === "failed";
          const stroke = failed ? "var(--destructive)" : color;
          return (
            <g key={n.id} className="transition-console">
              {n.state === "working" && (
                <circle cx={n.x} cy={n.y} r={26} fill={color} className="node-pulse" />
              )}
              {n.role === "jarvis" && finalDone && (
                <circle cx={n.x} cy={n.y} r={38} fill="var(--gold)" opacity={0.18} />
              )}
              <circle
                cx={n.x}
                cy={n.y}
                r={22}
                fill={n.state === "done" ? stroke : "rgba(11,15,26,0.9)"}
                fillOpacity={n.state === "done" ? 0.85 : 1}
                stroke={stroke}
                strokeWidth={1.6}
                opacity={dim ? 0.45 : 1}
              />
              <text
                x={n.x}
                y={n.y + 42}
                textAnchor="middle"
                fontSize={11}
                fontFamily="var(--font-mono)"
                fill={failed ? "var(--destructive)" : color}
                opacity={dim ? 0.6 : 1}
              >
                {n.label.length > 16 ? `${n.label.slice(0, 16)}…` : n.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
