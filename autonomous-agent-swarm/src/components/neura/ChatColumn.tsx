import { useEffect, useRef, useState } from "react";
import { Send } from "lucide-react";
import type { ChatMessage, VoiceConfig } from "@/lib/neura/types";
import { VoiceOrb } from "./VoiceOrb";

export function ChatColumn({
  messages,
  finalResult,
  sending,
  voiceConfig,
  apiUrl,
  disabled,
  onSend,
}: {
  messages: ChatMessage[];
  finalResult: string | null;
  sending: boolean;
  voiceConfig: VoiceConfig | null;
  apiUrl: string;
  disabled: boolean;
  onSend: (text: string) => void;
}) {
  const [text, setText] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const endRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, finalResult]);

  useEffect(() => {
    if (!sending) inputRef.current?.focus();
  }, [sending]);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const t = text.trim();
    if (!t || sending || disabled) return;
    setText("");
    onSend(t);
  }

  return (
    <section className="glass flex w-[420px] shrink-0 flex-col overflow-hidden rounded-xl">
      <div className="border-b border-border px-3 py-2 font-mono text-[11px] uppercase tracking-[0.18em] text-muted-foreground">
        jarvis · consultant
      </div>

      <div className="scroll-thin flex-1 space-y-3 overflow-y-auto p-3">
        {finalResult && (
          <div className="rounded-lg border border-gold/60 bg-gold/10 p-3">
            <div className="font-mono text-[10px] uppercase tracking-[0.2em] text-gold">
              final answer
            </div>
            <div className="mt-2 whitespace-pre-wrap text-sm leading-6 text-foreground/95">
              {finalResult}
            </div>
          </div>
        )}
        {messages.length === 0 && !finalResult && (
          <div className="pt-10 text-center font-mono text-xs text-muted-foreground">
            speak or type a business goal…
          </div>
        )}
        {messages.map((m) =>
          m.role === "system" ? (
            <div
              key={m.id}
              className="mx-auto w-fit rounded-full border border-marcelo/40 bg-marcelo/10 px-3 py-1 font-mono text-[10px] uppercase tracking-wide text-marcelo"
            >
              {m.content}
            </div>
          ) : (
            <div
              key={m.id}
              className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}
            >
              <div
                className={`max-w-[85%] rounded-lg px-3 py-2 text-sm leading-6 ${
                  m.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "border border-jarvis/30 bg-jarvis/10 text-foreground/95"
                }`}
              >
                {m.content}
              </div>
            </div>
          ),
        )}
        {sending && (
          <div className="font-mono text-[10px] text-muted-foreground">jarvis is thinking…</div>
        )}
        <div ref={endRef} />
      </div>

      <form onSubmit={submit} className="flex items-end gap-3 border-t border-border p-3">
        <VoiceOrb config={voiceConfig} apiUrl={apiUrl} />
        <div className="flex flex-1 items-center gap-2 rounded-lg border border-input bg-black/30 px-3 py-2">
          <input
            ref={inputRef}
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={disabled}
            placeholder={disabled ? "API offline" : "Describe your business goal…"}
            className="min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
          />
          <button
            type="submit"
            disabled={disabled || sending || !text.trim()}
            className="transition-console flex h-7 w-7 items-center justify-center rounded-md bg-primary text-primary-foreground disabled:opacity-40"
          >
            <Send className="h-3.5 w-3.5" />
          </button>
        </div>
      </form>
    </section>
  );
}
