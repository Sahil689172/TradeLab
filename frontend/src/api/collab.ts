/**
 * REST surface for collaborative rooms.
 *
 * The websocket is the primary interface once inside a room; these calls
 * cover the things that happen before it opens (listing, creating, joining)
 * plus the AI status banner.
 */

import type { PortfolioResponse } from '../types/api';
import type {
  AIStatus,
  ChatMessage,
  MessageListResponse,
  RoomCreateRequest,
  RoomListResponse,
  RoomOrderRequest,
  RoomSummary,
  TradeIdea,
} from '../types/collab';
import { request } from './client';

export const collabApi = {
  listRooms() {
    return request<RoomListResponse>('/collab/rooms');
  },

  getRoom(roomId: string) {
    return request<RoomSummary>(`/collab/rooms/${encodeURIComponent(roomId)}`);
  },

  createRoom(body: RoomCreateRequest) {
    return request<RoomSummary>('/collab/rooms', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  deleteRoom(roomId: string) {
    return request<Record<string, unknown>>(
      `/collab/rooms/${encodeURIComponent(roomId)}`,
      { method: 'DELETE' },
    );
  },

  joinRoom(roomId: string, user: string) {
    return request<RoomSummary>(
      `/collab/rooms/${encodeURIComponent(roomId)}/join?user=${encodeURIComponent(user)}`,
      { method: 'POST' },
    );
  },

  getMessages(roomId: string, limit = 50) {
    return request<MessageListResponse>(
      `/collab/rooms/${encodeURIComponent(roomId)}/messages?limit=${limit}`,
    );
  },

  getPortfolio(roomId: string) {
    return request<PortfolioResponse>(
      `/collab/rooms/${encodeURIComponent(roomId)}/portfolio`,
    );
  },

  postTradeIdea(roomId: string, author: string, idea: Partial<TradeIdea>) {
    return request<ChatMessage>(
      `/collab/rooms/${encodeURIComponent(roomId)}/trade-ideas`,
      { method: 'POST', body: JSON.stringify({ author, idea }) },
    );
  },

  placeOrder(roomId: string, body: RoomOrderRequest) {
    return request<unknown>(`/collab/rooms/${encodeURIComponent(roomId)}/orders`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  aiStatus() {
    return request<AIStatus>('/collab/ai/status');
  },
};
