import { useRef, useState } from "react";
import { Mic, MicOff } from "lucide-react";
import type { VoiceConfig } from "@/lib/neura/types";
import { base, fetchRtcToken } from "@/lib/neura/api";

interface AgoraTrack {
  close: () => void;
}
interface AgoraClient {
  join: (
    appId: string,
    channel: string,
    token: string | null,
    uid?: string | number | null,
  ) => Promise<unknown>;
  leave: () => Promise<void>;
  publish: (tracks: AgoraTrack[]) => Promise<void>;
}

interface AgoraRTCLike {
  createClient: (cfg: { mode: string; codec: string }) => unknown;
  createMicrophoneAudioTrack: () => Promise<unknown>;
}

export function VoiceOrb({ config, apiUrl }: { config: VoiceConfig | null; apiUrl: string }) {
  const [joined, setJoined] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const clientRef = useRef<AgoraClient | null>(null);
  const trackRef = useRef<AgoraTrack | null>(null);

  const configured = Boolean(config?.configured && config?.app_id && config?.channel);

  async function toggle() {
    if (!configured || busy) return;
    setBusy(true);
    setError(null);
    try {
      if (joined) {
        trackRef.current?.close();
        trackRef.current = null;
        await clientRef.current?.leave();
        clientRef.current = null;
        setJoined(false);
      } else {
        const mod = (await import("agora-rtc-sdk-ng")) as unknown as {
          default?: AgoraRTCLike;
        } & AgoraRTCLike;
        const AgoraRTC: AgoraRTCLike = mod.default ?? mod;
        const client = AgoraRTC.createClient({ mode: "rtc", codec: "vp8" }) as AgoraClient;

        // Projects with app certificate enabled require a dynamic RTC token;
        // mint one from the backend (the certificate never leaves the server).
        let token: string | null = (config?.token as string | null) ?? null;
        let uid: string | number | null = (config?.uid as string | number | null) ?? null;
        if (!token) {
          try {
            const t = await fetchRtcToken(base(apiUrl), String(config?.channel ?? "neura-demo"));
            token = t.token;
            uid = t.uid ?? uid;
          } catch {
            // tokenless join only works with certificate disabled; let Agora report it
          }
        }
        await client.join(String(config?.app_id), String(config?.channel), token, uid);
        const track = (await AgoraRTC.createMicrophoneAudioTrack()) as AgoraTrack;
        await client.publish([track]);
        clientRef.current = client;
        trackRef.current = track;
        setJoined(true);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "voice error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex flex-col items-center">
      <button
        type="button"
        onClick={toggle}
        disabled={!configured}
        title={
          configured
            ? joined
              ? "leave voice channel"
              : "join voice channel"
            : "voice offline — type below"
        }
        className={`transition-console group flex h-12 w-12 items-center justify-center rounded-full border ${
          joined
            ? "orb-listening border-jarvis bg-jarvis/20 text-jarvis"
            : configured
              ? "border-jarvis/50 bg-jarvis/10 text-jarvis hover:bg-jarvis/20"
              : "cursor-not-allowed border-border bg-white/5 text-muted-foreground"
        }`}
      >
        {configured ? <Mic className="h-5 w-5" /> : <MicOff className="h-5 w-5" />}
      </button>
      <span className="mt-1 font-mono text-[9px] uppercase tracking-widest text-muted-foreground">
        {error ? error.slice(0, 140) : joined ? "listening" : configured ? "voice" : "offline"}
      </span>
    </div>
  );
}
