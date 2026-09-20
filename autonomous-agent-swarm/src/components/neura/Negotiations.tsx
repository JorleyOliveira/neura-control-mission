import type { Negotiation, NegotiationMessage, SellerReply } from "@/lib/neura/types";

const money = (cents?: number) =>
  typeof cents === "number" ? `$${(cents / 100).toFixed(2)}` : "—";

function isSeller(m: NegotiationMessage) {
  const r = String(m.role ?? m.sender ?? m.from ?? "").toLowerCase();
  return r.includes("seller") || r.includes("assistant") || r.includes("freshmart");
}

function parseSeller(content: string): SellerReply | null {
  try {
    const obj = JSON.parse(content) as unknown;
    return obj && typeof obj === "object" ? (obj as SellerReply) : null;
  } catch {
    return null;
  }
}

function OfferCard({ offer }: { offer: NonNullable<SellerReply["offer"]> }) {
  const items = Array.isArray(offer.items) ? offer.items : [];
  return (
    <div className="mt-2 rounded-md border border-seller/40 bg-black/30 p-2 font-mono text-[10px]">
      {items.map((it, i) => (
        <div key={i} className="flex justify-between gap-2 text-foreground/80">
          <span className="truncate">
            {it.name ?? "item"} ×{it.qty ?? it.quantity ?? 1}
          </span>
          <span>@ {money(it.unit_price_cents)}</span>
        </div>
      ))}
      <div className="mt-1 border-t border-border pt-1 text-muted-foreground">
        <div className="flex justify-between">
          <span>subtotal</span>
          <span>{money(offer.subtotal_cents)}</span>
        </div>
        <div className="flex justify-between">
          <span>discount</span>
          <span>-{money(offer.discount_cents ?? 0).replace("$", "$")}</span>
        </div>
        <div className="flex justify-between text-gold">
          <span>total</span>
          <span>{money(offer.total_cents)}</span>
        </div>
      </div>
    </div>
  );
}

function Bubble({ m }: { m: NegotiationMessage }) {
  const seller = isSeller(m);
  const content = String(m.content ?? m["text"] ?? "");
  const parsed = seller ? parseSeller(content) : null;
  const action = parsed?.action ? String(parsed.action) : undefined;
  const text = parsed ? (parsed.reply ?? parsed.message ?? parsed.text ?? "") : content;

  return (
    <div className={`flex ${seller ? "justify-start" : "justify-end"}`}>
      <div
        className={`max-w-[85%] rounded-lg border px-3 py-2 text-xs leading-5 ${
          seller ? "border-seller/40 bg-seller/10" : "border-worker/40 bg-worker/10"
        }`}
      >
        <div className="mb-1 font-mono text-[10px] uppercase tracking-wide text-muted-foreground">
          {seller ? "seller" : "buyer"}
        </div>
        {text && <div className="whitespace-pre-wrap text-foreground/90">{text}</div>}
        {!text && !parsed && <div className="text-muted-foreground">—</div>}
        {action && (
          <span
            className={`mt-2 inline-block rounded px-1.5 py-[1px] font-mono text-[10px] uppercase ${
              action === "accept"
                ? "bg-gold/20 text-gold"
                : action === "reject"
                  ? "bg-destructive/20 text-destructive"
                  : "bg-white/10 text-muted-foreground"
            }`}
          >
            {action}
          </span>
        )}
        {action === "accept" && (
          <span className="ml-2 inline-block rounded border border-gold px-1.5 py-[1px] font-mono text-[10px] uppercase tracking-widest text-gold">
            deal closed
          </span>
        )}
        {parsed?.offer && <OfferCard offer={parsed.offer} />}
      </div>
    </div>
  );
}

export function Negotiations({ negotiations }: { negotiations: Negotiation[] }) {
  if (negotiations.length === 0) {
    return (
      <div className="flex h-full items-center justify-center font-mono text-xs text-muted-foreground">
        no negotiation threads yet…
      </div>
    );
  }
  return (
    <div className="scroll-thin h-full space-y-4 overflow-y-auto p-3">
      {negotiations.map((n, i) => {
        const msgs = Array.isArray(n.messages) ? n.messages : [];
        return (
          <div key={String(n.negotiation_id ?? n.id ?? i)} className="space-y-2">
            <div className="font-mono text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
              thread {String(n.negotiation_id ?? n.id ?? i + 1)} · {String(n.status ?? "open")}
            </div>
            {msgs.map((m, j) => (
              <Bubble key={j} m={m} />
            ))}
          </div>
        );
      })}
    </div>
  );
}
