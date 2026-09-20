import type { Run } from "@/lib/neura/types";
import { relativeTime } from "@/lib/neura/api";
import { runId } from "@/lib/neura/types";

const statusStyle = (status?: string) => {
  switch ((status ?? "").toLowerCase()) {
    case "running":
      return "bg-primary/15 text-primary animate-pulse";
    case "completed":
      return "bg-worker/15 text-worker";
    case "failed":
      return "bg-destructive/15 text-destructive";
    default:
      return "bg-white/10 text-muted-foreground";
  }
};

export function RunsSidebar({
  runs,
  loading,
  selectedId,
  onSelect,
}: {
  runs: Run[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <aside className="glass flex w-[260px] shrink-0 flex-col overflow-hidden rounded-xl">
      <div className="border-b border-border px-3 py-2 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        runs
      </div>
      <div className="scroll-thin flex-1 overflow-y-auto">
        {loading &&
          runs.length === 0 &&
          [0, 1, 2].map((i) => (
            <div key={i} className="space-y-2 border-b border-border/60 px-3 py-3">
              <div className="h-3 w-4/5 animate-pulse rounded bg-white/10" />
              <div className="h-2 w-1/3 animate-pulse rounded bg-white/5" />
            </div>
          ))}
        {!loading && runs.length === 0 && (
          <div className="px-3 py-6 font-mono text-[11px] text-muted-foreground">
            waiting for agents…
          </div>
        )}
        {runs.map((run) => {
          const id = runId(run);
          const obj = String(run.objective ?? "untitled goal");
          const selected = id === selectedId;
          return (
            <button
              key={id}
              type="button"
              onClick={() => onSelect(id)}
              className={`transition-console block w-full border-b border-border/60 px-3 py-3 text-left hover:bg-white/[0.04] ${
                selected ? "bg-primary/10 shadow-[inset_2px_0_0_0_var(--primary)]" : ""
              }`}
            >
              <div className="text-xs leading-5 text-foreground/90">
                {obj.length > 60 ? `${obj.slice(0, 60)}…` : obj}
              </div>
              <div className="mt-2 flex items-center justify-between gap-2">
                <span
                  className={`rounded-full px-2 py-[1px] font-mono text-[10px] uppercase ${statusStyle(
                    String(run.status ?? ""),
                  )}`}
                >
                  {String(run.status ?? "unknown")}
                </span>
                <span className="font-mono text-[10px] text-muted-foreground">
                  {relativeTime(String(run.created_at ?? run.updated_at ?? ""))}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </aside>
  );
}
