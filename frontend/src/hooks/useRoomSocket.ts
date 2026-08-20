/**
 * Live room channel: chat, presence, shared portfolio, and AI turns.
 *
 * Two behaviours here are load-bearing and easy to get wrong:
 *
 * 1. Nothing is echoed locally. The server broadcasts the author's own
 *    message back, so optimistically appending would render it twice — the
 *    terminal demo client double-prints for exactly this reason. Messages
 *    are also de-duplicated by message_id, because a reconnect replays
 *    history that overlaps what is already on screen.
 * 2. Close codes 4404 and 4409 are refusals, not drops. Retrying them would
 *    loop forever against a room that does not exist or is full, so they end
 *    the connection with a specific message instead.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { PortfolioResponse } from '../types/api';
import {
  CLOSE_ROOM_FULL,
  CLOSE_ROOM_NOT_FOUND,
  type ChatMessage,
  type HistoryFrame,
  type PresenceFrame,
  type RoomOrderRequest,
  type TradeIdea,
  type WSInbound,
  type WSOutbound,
} from '../types/collab';

export type ConnectionState =
  | 'connecting'
  | 'open'
  | 'reconnecting'
  | 'closed'
  | 'refused';

const PING_INTERVAL_MS = 25_000;
const BACKOFF_BASE_MS = 500;
const BACKOFF_CEILING_MS = 15_000;
/** An AI turn that has produced nothing by then has failed silently. */
const AI_THINKING_TIMEOUT_MS = 60_000;

/** Callers omit `author`; the hook stamps it from the connected handle. */
type OrderFrame = Omit<RoomOrderRequest, 'author'>;
type IdeaFrame = Partial<TradeIdea> & { symbol: string };

function socketUrl(roomId: string, user: string): string {
  const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const base = scheme + '//' + window.location.host + '/api/v1/collab/ws/rooms';
  return base + '/' + encodeURIComponent(roomId) + '?user=' + encodeURIComponent(user);
}

/** Merge incoming messages, keyed by id, keeping chronological order. */
export function mergeMessages(
  existing: ChatMessage[],
  incoming: ChatMessage[],
): ChatMessage[] {
  const byId = new Map(existing.map((m) => [m.message_id, m]));
  for (const message of incoming) byId.set(message.message_id, message);
  return [...byId.values()].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at),
  );
}

export interface RoomSocket {
  messages: ChatMessage[];
  onlineMembers: string[];
  portfolio: PortfolioResponse | null;
  connection: ConnectionState;
  /** Set when the room refused us (4404/4409) or the server sent an error. */
  error: string | null;
  aiThinkingFor: string | null;
  clearError: () => void;
  sendChat: (text: string) => boolean;
  sendTradeIdea: (idea: IdeaFrame) => boolean;
  sendOrder: (order: OrderFrame) => boolean;
  requestHistory: (limit?: number) => boolean;
}

export function useRoomSocket(
  roomId: string | undefined,
  user: string,
): RoomSocket {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [onlineMembers, setOnlineMembers] = useState<string[]>([]);
  const [portfolio, setPortfolio] = useState<PortfolioResponse | null>(null);
  const [connection, setConnection] = useState<ConnectionState>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [aiThinkingFor, setAiThinkingFor] = useState<string | null>(null);

  const socketRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const retryTimerRef = useRef<number | null>(null);
  const pingTimerRef = useRef<number | null>(null);
  const aiTimerRef = useRef<number | null>(null);
  /** Guards a queued reconnect from firing after unmount or a room change. */
  const disposedRef = useRef(false);

  const send = useCallback((frame: WSInbound): boolean => {
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) return false;
    socket.send(JSON.stringify(frame));
    return true;
  }, []);

  useEffect(() => {
    if (!roomId || !user) return undefined;

    disposedRef.current = false;
    attemptRef.current = 0;
    // A room switch must not inherit the previous room's transcript.
    setMessages([]);
    setOnlineMembers([]);
    setPortfolio(null);
    setError(null);

    let socket: WebSocket | null = null;

    const clearTimers = () => {
      if (pingTimerRef.current) window.clearInterval(pingTimerRef.current);
      if (retryTimerRef.current) window.clearTimeout(retryTimerRef.current);
      pingTimerRef.current = null;
      retryTimerRef.current = null;
    };

    const connect = () => {
      if (disposedRef.current) return;
      setConnection(attemptRef.current === 0 ? 'connecting' : 'reconnecting');

      socket = new WebSocket(socketUrl(roomId, user));
      socketRef.current = socket;

      socket.onopen = () => {
        if (disposedRef.current) return;
        attemptRef.current = 0;
        setConnection('open');
        setError(null);
        pingTimerRef.current = window.setInterval(() => {
          if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: 'ping' }));
          }
        }, PING_INTERVAL_MS);
      };

      socket.onmessage = (event) => {
        if (disposedRef.current) return;
        let frame: WSOutbound;
        try {
          frame = JSON.parse(event.data as string) as WSOutbound;
        } catch {
          return; // A frame we cannot parse is not worth tearing the room down.
        }

        switch (frame.type) {
          case 'history': {
            const data = frame.data as HistoryFrame;
            setMessages((prev) => mergeMessages(prev, data.messages ?? []));
            break;
          }
          case 'message': {
            const message = frame.data as ChatMessage;
            setMessages((prev) => mergeMessages(prev, [message]));
            // Any AI reply resolves the pending "thinking" indicator.
            if (message.kind === 'AI_REPLY') setAiThinkingFor(null);
            break;
          }
          case 'presence': {
            const data = frame.data as PresenceFrame;
            setOnlineMembers(data.online_members ?? []);
            break;
          }
          case 'portfolio': {
            setPortfolio(frame.data as PortfolioResponse);
            break;
          }
          case 'ai_thinking': {
            const data = frame.data as { asked_by: string };
            setAiThinkingFor(data.asked_by);
            if (aiTimerRef.current) window.clearTimeout(aiTimerRef.current);
            aiTimerRef.current = window.setTimeout(
              () => setAiThinkingFor(null),
              AI_THINKING_TIMEOUT_MS,
            );
            break;
          }
          case 'error': {
            const data = frame.data as { message?: string };
            setError(data?.message ?? 'The room reported an error');
            setAiThinkingFor(null);
            break;
          }
          case 'pong':
          default:
            break;
        }
      };

      socket.onclose = (event) => {
        clearTimers();
        if (disposedRef.current) return;

        // Room-level refusals are terminal: retrying cannot change the answer.
        if (event.code === CLOSE_ROOM_NOT_FOUND) {
          setConnection('refused');
          setError('That room no longer exists — it may have been deleted.');
          return;
        }
        if (event.code === CLOSE_ROOM_FULL) {
          setConnection('refused');
          setError(
            event.reason ||
              'This room is at capacity. Ask a member to leave, or open another room.',
          );
          return;
        }

        setConnection('reconnecting');
        const delay = Math.min(
          BACKOFF_BASE_MS * 2 ** attemptRef.current,
          BACKOFF_CEILING_MS,
        );
        attemptRef.current += 1;
        retryTimerRef.current = window.setTimeout(connect, delay);
      };

      socket.onerror = () => {
        // onclose always follows and owns the retry decision.
      };
    };

    connect();

    return () => {
      disposedRef.current = true;
      clearTimers();
      if (aiTimerRef.current) window.clearTimeout(aiTimerRef.current);
      socketRef.current = null;
      // 1000 = normal closure, so the server records a clean leave.
      if (socket) socket.close(1000, 'Left room');
    };
  }, [roomId, user]);

  const clearError = useCallback(() => setError(null), []);
  const sendChat = useCallback(
    (text: string) => send({ type: 'chat', text }),
    [send],
  );
  const sendTradeIdea = useCallback(
    (idea: IdeaFrame) => send({ type: 'trade_idea', idea }),
    [send],
  );
  const sendOrder = useCallback(
    (order: OrderFrame) => send({ type: 'order', order: { ...order, author: user } }),
    [send, user],
  );
  const requestHistory = useCallback(
    (limit = 50) => send({ type: 'history', limit }),
    [send],
  );

  return useMemo(
    () => ({
      messages,
      onlineMembers,
      portfolio,
      connection,
      error,
      aiThinkingFor,
      clearError,
      sendChat,
      sendTradeIdea,
      sendOrder,
      requestHistory,
    }),
    [
      messages,
      onlineMembers,
      portfolio,
      connection,
      error,
      aiThinkingFor,
      clearError,
      sendChat,
      sendTradeIdea,
      sendOrder,
      requestHistory,
    ],
  );
}
