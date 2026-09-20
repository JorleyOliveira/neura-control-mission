import { useState } from "react";
import type { MarketplaceEvent } from "@/lib/neura/types";
import { describe, roleColor, roleOf, toneClass } from "@/lib/neura/eventMap";
import { clockTime } from "@/lib/neura/api";

function Row({ ev }: { ev: MarketplaceEvent }) {
  const [open, setOpen] = useState(false);
  const info = describe(ev);
  const role = roleOf(ev.actor);
  const color = roleColor[role];
  const payload = ev.payload as Record<string, unknown> | null ?? {};
  const messageTo = typeof payload.message_to_worker === "string" ? payload.message_to_worker : null;
  const messageFrom = typeof payload.message_from_worker === "string" ? payload.message_from_worker : null;
  return (
    <li className="transition-console border-b border-border/60 px-3 py-2 hover:bg-white/[0.03]">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start gap-2 text-left"
      >
        <span className="mt-[2px] shrink-0 font-mono text-[10px] text-muted-foreground">
          {clockTime(ev.ts ?? ev.received_at)}
        </span>
        <span
          className="mt-[1px] shrink-0 rounded px-1.5 py-[1px] font-mono text-[10px] uppercase"
          style={{ color, background: `color-mix(in oklab, ${color} 16%, transparent)` }}
        >
          {ev.actor ?? "system"}
        </span>
        <span className="mt-[1px] shrink-0 rounded border border-border px-1.5 py-[1px] font-mono text-[10px] text-muted-foreground">
          {info.badge}
        </span>
        <span className={`min-w-0 flex-1 text-xs leading-5 ${toneClass[info.tone]}`}>
          {info.summary}
          {(messageTo || messageFrom) && (
            <span className="ml-1 text-jarvis">✉ message</span>
          )}
        </span>
      </button>
      {open && (
        <div className="mt-2 space-y-2">
          {messageTo && (
            <div className="rounded-md border border-jarvis/30 bg-jarvis/[0.06] p-2">
              <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-jarvis">
                ✉ MARCELO → {String(payload.agent_name ?? "worker")} · the exact message sent (JSON-RPC message/send)
              </div>
              <div className="scroll-thin max-h-52 overflow-auto whitespace-pre-wrap text-xs leading-5 text-foreground/90">
                {messageTo}
              </div>
            </div>
          )}
          {messageFrom && (
            <div className="rounded-md border border-worker/30 bg-worker/[0.06] p-2">
              <div className="mb-1 font-mono text-[10px] uppercase tracking-wider text-worker">
                ✉ {ev.actor} → MARCELO · the exact message received back
              </div>
              <div className="scroll-thin max-h-52 overflow-auto whitespace-pre-wrap text-xs leading-5 text-foreground/90">
                {messageFrom}
              </div>
            </div>
          )}
          <pre className="scroll-thin max-h-60 overflow-auto rounded-md bg-black/50 p-2 font-mono text-[10px] leading-4 text-muted-foreground">
            {JSON.stringify(ev.payload ?? {}, null, 2)}
          </pre>
        </div>
      )}
    </li>
  );
}

export function Timeline({
  events,
  connected,
}: {
  events: MarketplaceEvent[];
  connected: boolean;
}) {
  const rows = [...events].slice(-200).reverse();
  if (rows.length === 0) {
    return (
      <div className="flex h-full items-center justify-center font-mono text-xs text-muted-foreground">
        {connected ? "no events yet — send a goal to JARVIS" : "waiting for agents…"}
      </div>
    );
  }
  return (
    <ul className="scroll-thin h-full overflow-y-auto">
      {rows.map((ev) => (
        <Row key={ev.seq} ev={ev} />
      ))}
    </ul>
  );
}
