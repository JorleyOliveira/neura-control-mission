export type RunStatus = "accepted" | "running" | "completed" | "failed" | string;

export interface Run {
  run_id?: string;
  id?: string;
  objective?: string;
  status?: RunStatus;
  created_at?: string;
  updated_at?: string;
  final_result?: unknown;
  session_id?: string;
  [k: string]: unknown;
}

export interface MarketplaceEvent {
  seq: number;
  event_type: string;
  actor?: string | undefined;
  payload?: Record<string, unknown> | undefined;
  ts?: string | undefined;
  received_at?: number | undefined;
}

export interface ChatMessage {
  id: string;
  role: "user" | "jarvis" | "system";
  content: string;
  ts?: number;
}

export interface VoiceConfig {
  configured?: boolean;
  app_id?: string;
  channel?: string;
  token?: string | null;
  uid?: string | number | null;
  [k: string]: unknown;
}

export interface Negotiation {
  id?: string;
  negotiation_id?: string;
  buyer?: string;
  seller?: string;
  status?: string;
  messages?: NegotiationMessage[];
  [k: string]: unknown;
}

export interface NegotiationMessage {
  role?: string;
  sender?: string;
  from?: string;
  content?: string;
  ts?: string | undefined;
  [k: string]: unknown;
}

export interface SellerReply {
  reply?: string;
  message?: string;
  text?: string;
  action?: string;
  offer?: {
    items?: Array<{
      name?: string;
      qty?: number;
      quantity?: number;
      unit_price_cents?: number;
    }>;
    subtotal_cents?: number;
    discount_cents?: number;
    total_cents?: number;
    [k: string]: unknown;
  };
  [k: string]: unknown;
}

export const runId = (r: Run) => String(r.run_id ?? r.id ?? "");
