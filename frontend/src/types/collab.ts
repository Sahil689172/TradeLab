/**
 * Wire contracts for collaborative rooms.
 *
 * Mirrors app/collab/schemas.py. Keep the two in step: the socket sends
 * these shapes verbatim, so drift here shows up as a silently missing
 * field rather than a type error.
 */

export type MessageKind =
  | 'CHAT'
  | 'TRADE_IDEA'
  | 'ORDER_EVENT'
  | 'AI_REPLY'
  | 'SYSTEM';

export type TradeDirection = 'LONG' | 'SHORT';

/** 'none' means every provider failed; the reply carries no numbers. */
export type AISource = 'gemini' | 'groq' | 'none';

export interface TradeIdea {
  symbol: string;
  direction: TradeDirection;
  thesis: string;
  entry: number | null;
  stop_loss: number | null;
  target: number | null;
  /** Stamped server-side at write time — what makes a call scoreable. */
  price_at_post: number | null;
}

export interface ChatMessage {
  message_id: string;
  room_id: string;
  author: string;
  kind: MessageKind;
  text: string;
  created_at: string;
  trade_idea: TradeIdea | null;
  ai_source: AISource | null;
  ai_tools_used: string[];
  metadata: Record<string, unknown>;
}

export interface RoomSummary {
  room_id: string;
  name: string;
  created_by: string;
  created_at: string;
  capacity: number;
  initial_capital: number;
  members: string[];
  online_members: string[];
  message_count: number;
}

export interface RoomListResponse {
  total: number;
  rooms: RoomSummary[];
}

export interface MessageListResponse {
  room_id: string;
  total: number;
  messages: ChatMessage[];
}

export interface RoomCreateRequest {
  name: string;
  created_by: string;
  initial_capital?: number;
  capacity?: number;
}

export interface RoomOrderRequest {
  author: string;
  side: 'BUY' | 'SELL';
  symbol: string;
  quantity: number;
  price?: number | null;
  stop_loss?: number | null;
  target?: number | null;
}

export interface AIProviderFailure {
  provider: string;
  reason: string;
  hint: string | null;
  is_auth_error: boolean;
  occurred_at: string;
}

export interface AIStatus {
  enabled: boolean;
  primary: string;
  fallback: string | null;
  gemini_configured: boolean;
  groq_configured: boolean;
  gemini_model: string | null;
  groq_model: string | null;
  trigger: string;
  read_only: boolean;
  last_error: AIProviderFailure | null;
}

// ---------------------------------------------------------------------------
// WebSocket frames
// ---------------------------------------------------------------------------

export type WSEventType =
  | 'message'
  | 'history'
  | 'presence'
  | 'portfolio'
  | 'ai_thinking'
  | 'error'
  | 'pong';

export interface WSOutbound<T = unknown> {
  type: WSEventType;
  data: T;
  sent_at: string;
}

export interface HistoryFrame {
  room_id: string;
  messages: ChatMessage[];
}

export interface PresenceFrame {
  online_members: string[];
}

export interface AIThinkingFrame {
  asked_by: string;
}

export interface ErrorFrame {
  message: string;
  detail?: unknown;
}

/** Client-to-server frames, matching WSInbound's permissive single shape. */
export type WSInbound =
  | { type: 'chat'; text: string }
  | { type: 'trade_idea'; idea: Partial<TradeIdea> & { symbol: string } }
  // `author` is required by the schema but the server overwrites it with
  // the socket's user, so a client cannot trade in someone else's name.
  | { type: 'order'; order: RoomOrderRequest }
  | { type: 'history'; limit?: number }
  | { type: 'ping' };

/**
 * Close codes the server uses for room-specific refusals. Anything else is
 * a genuine transport drop and is worth retrying.
 */
export const CLOSE_ROOM_NOT_FOUND = 4404;
export const CLOSE_ROOM_FULL = 4409;
