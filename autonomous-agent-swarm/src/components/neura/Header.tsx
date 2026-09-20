export function Header({
  apiUrl,
  connected,
  onApiUrlChange,
}: {
  apiUrl: string;
  connected: boolean;
  onApiUrlChange: (v: string) => void;
}) {
  return (
    <header className="flex shrink-0 items-center gap-4 px-4 py-3">
      <div className="flex items-baseline gap-2">
        <span className="font-mono text-sm font-semibold tracking-[0.3em] text-jarvis">NEURA</span>
        <span className="font-mono text-[11px] uppercase tracking-[0.25em] text-muted-foreground">
          mission control
        </span>
      </div>
      <div className="ml-auto flex items-center gap-3">
        <label className="font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
          api url
        </label>
        <input
          value={apiUrl}
          onChange={(e) => onApiUrlChange(e.target.value)}
          spellCheck={false}
          className="w-[260px] rounded-md border border-input bg-black/40 px-3 py-1.5 font-mono text-xs text-foreground outline-none focus:border-jarvis/60"
        />
        <span className="flex items-center gap-2 font-mono text-[10px] uppercase tracking-widest text-muted-foreground">
          <span
            className={`h-2.5 w-2.5 rounded-full transition-console ${
              connected
                ? "bg-worker shadow-[0_0_10px_var(--worker)]"
                : "bg-destructive shadow-[0_0_10px_var(--destructive)]"
            }`}
          />
          {connected ? "online" : "offline"}
        </span>
      </div>
    </header>
  );
}
