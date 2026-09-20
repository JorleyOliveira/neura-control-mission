import type { MarketplaceEvent } from "./types";

export type Role = "jarvis" | "marcelo" | "worker" | "verifier" | "seller" | "system";
export type Tone = "normal" | "good" | "warn" | "bad" | "gold";

const g = (o: unknown, k: string): unknown =>
  o && typeof o === "object" ? (o as Record<string, unknown>)[k] : undefined;

const s = (v: unknown): string | undefined =>
  v === undefined || v === null ? undefined : String(v);

export function roleOf(actor?: string): Role {
  const a = (actor ?? "").toLowerCase();
  if (a.includes("jarvis")) return "jarvis";
  if (a.includes("marcelo")) return "marcelo";
  if (a.includes("verifier") || a.includes("verify")) return "verifier";
  if (a.includes("seller") || a.includes("freshmart")) return "seller";
  if (!a || a === "system") return "system";
  return "worker";
}

export const roleColor: Record<Role, string> = {
  jarvis: "var(--jarvis)",
  marcelo: "var(--marcelo)",
  worker: "var(--worker)",
  verifier: "var(--verifier)",
  seller: "var(--seller)",
  system: "var(--muted-foreground)",
};

function argHint(args: unknown): string {
  for (const k of ["query", "url", "command", "path", "message", "text"]) {
    const v = g(args, k);
    if (typeof v === "string" && v.trim()) {
      return v.length > 70 ? `${v.slice(0, 70)}…` : v;
    }
  }
  return "";
}

export interface RowInfo {
  summary: string;
  tone: Tone;
  badge: string;
}

export function describe(ev: MarketplaceEvent): RowInfo {
  const p = ev.payload ?? {};
  const t = (ev.event_type ?? "").toUpperCase();
  const actor = ev.actor ?? "agent";
  const badge = t || "EVENT";

  switch (t) {
    case "GOAL_DELEGATED":
      return { badge, tone: "normal", summary: `Goal delegated → ${s(p["to"]) ?? "MARCELO"}` };
    case "GOAL_RECEIVED":
      return {
        badge,
        tone: "normal",
        summary: `Goal received: ${s(p["goal"]) ?? s(p["objective"]) ?? ""}`,
      };
    case "PLAN_CREATED": {
      const tasks = Array.isArray(p["tasks"]) ? (p["tasks"] as unknown[]) : [];
      const titles = tasks
        .map((x) => s(g(x, "title")) ?? s(g(x, "name")) ?? s(x))
        .filter(Boolean)
        .slice(0, 4)
        .join(" · ");
      return {
        badge,
        tone: "normal",
        summary: `Planned ${tasks.length} tasks${titles ? ` — ${titles}` : ""}`,
      };
    }
    case "DISCOVER": {
      const cands = p["candidates"] ?? p["results"];
      const n = Array.isArray(cands) ? cands.length : (s(p["count"]) ?? "?");
      return {
        badge,
        tone: "normal",
        summary: `Searched mesh: ${s(p["query"]) ?? ""} → ${n} candidates`,
      };
    }
    case "EVALUATE":
      return {
        badge,
        tone: "normal",
        summary: `Selected ${s(p["selected_agent_id"]) ?? "?"} (confidence ${s(p["confidence"]) ?? "?"})`,
      };
    case "HIRE":
      return {
        badge,
        tone: "good",
        summary: `Hired ${s(p["agent_name"]) ?? s(p["agent_id"]) ?? "agent"}${
          s(g(p["contract"], "task")) ? ` · ${s(g(p["contract"], "task"))}` : ""
        }`,
      };
    case "DELEGATE":
      return {
        badge,
        tone: "normal",
        summary: `Delegated to ${s(p["agent_name"]) ?? s(p["agent_id"]) ?? "worker"}`,
      };
    case "WORKER_PROGRESS": {
      const wt = String(p["worker_event_type"] ?? p["event_type"] ?? "").toUpperCase();
      const tool = s(p["tool"]);
      switch (wt) {
        case "AGENT_STARTED":
          return {
            badge: wt,
            tone: "normal",
            summary: `▶ ${actor} started · model ${s(p["model"]) ?? "?"}`,
          };
        case "TOOL_REQUESTED":
          return {
            badge: wt,
            tone: "normal",
            summary: `🔧 ${tool ?? "tool"} ${argHint(p["arguments"])}`,
          };
        case "TOOL_COMPLETED":
          return {
            badge: wt,
            tone: "good",
            summary: `🔧 ${tool ?? "tool"} ${argHint(p["arguments"])} ✓`,
          };
        case "TOOL_FAILED":
          return {
            badge: wt,
            tone: "bad",
            summary: `🔧 ${tool ?? "tool"} ${argHint(p["arguments"])} failed`,
          };
        case "AGENT_ACTION_INVALID":
          return { badge: wt, tone: "bad", summary: "invalid action — recovering" };
        case "AGENT_FINAL_BLOCKED":
          return {
            badge: wt,
            tone: "warn",
            summary: "blocked from finishing until required tool really runs",
          };
        case "AGENT_COMPLETED": {
          const used = Array.isArray(p["used_tools"])
            ? (p["used_tools"] as unknown[]).join(", ")
            : "";
          return {
            badge: wt,
            tone: "good",
            summary: `${actor} finished${used ? ` · used ${used}` : ""}`,
          };
        }
        default:
          return {
            badge: wt || badge,
            tone: "normal",
            summary: `${actor} · ${tool ?? (wt.toLowerCase() || "progress")}`,
          };
      }
    }
    case "WORKER_RESULT":
      return {
        badge,
        tone: "good",
        summary: `result from ${actor} · model ${s(p["model"]) ?? "?"}`,
      };
    case "VERIFY_HIRE":
      return {
        badge,
        tone: "warn",
        summary: `verifier hired for ${s(p["task"]) ?? s(p["task_id"]) ?? "task"}`,
      };
    case "VERIFY_PASS":
      return { badge, tone: "good", summary: `verified · score ${s(p["score"]) ?? "?"}` };
    case "VERIFY_FAIL": {
      const fc = p["failed_criteria"];
      const list = Array.isArray(fc) ? fc.join(", ") : (s(fc) ?? "");
      return { badge, tone: "bad", summary: `verification failed${list ? ` · ${list}` : ""}` };
    }
    case "REJECT_AND_REHIRE":
      return {
        badge,
        tone: "warn",
        summary: `rejected, rehiring (attempt ${s(p["attempt"]) ?? "?"})`,
      };
    case "FINAL_RESULT":
      return { badge, tone: "gold", summary: "FINAL ANSWER delivered by JARVIS" };
    case "RUN_FAILED":
      return { badge, tone: "bad", summary: `run failed · ${s(p["error"]) ?? "unknown error"}` };
    default:
      return { badge, tone: "normal", summary: s(p["message"]) ?? s(p["summary"]) ?? actor };
  }
}

export const toneClass: Record<Tone, string> = {
  normal: "text-foreground/85",
  good: "text-worker",
  warn: "text-verifier",
  bad: "text-destructive",
  gold: "text-gold",
};
