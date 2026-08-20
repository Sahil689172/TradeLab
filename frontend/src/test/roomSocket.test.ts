import { describe, expect, it } from 'vitest';
import { mergeMessages } from '../hooks/useRoomSocket';
import type { ChatMessage } from '../types/collab';

function message(id: string, at: string, text = id): ChatMessage {
  return {
    message_id: id,
    room_id: 'room-1',
    author: 'sahil',
    kind: 'CHAT',
    text,
    created_at: at,
    trade_idea: null,
    ai_source: null,
    ai_tools_used: [],
    metadata: {},
  };
}

describe('mergeMessages', () => {
  it('renders a message once even when the server echoes it back', () => {
    // The author's own message arrives from the server, not from a local
    // echo. Appending it twice is the bug the demo client has.
    const own = message('m1', '2024-01-01T10:00:00Z');
    const merged = mergeMessages([own], [own]);
    expect(merged).toHaveLength(1);
  });

  it('de-duplicates history replayed after a reconnect', () => {
    const existing = [
      message('m1', '2024-01-01T10:00:00Z'),
      message('m2', '2024-01-01T10:01:00Z'),
    ];
    const replayed = [
      message('m1', '2024-01-01T10:00:00Z'),
      message('m2', '2024-01-01T10:01:00Z'),
      message('m3', '2024-01-01T10:02:00Z'),
    ];
    const merged = mergeMessages(existing, replayed);
    expect(merged.map((m) => m.message_id)).toEqual(['m1', 'm2', 'm3']);
  });

  it('orders by creation time when frames arrive out of order', () => {
    const merged = mergeMessages(
      [message('m2', '2024-01-01T10:01:00Z')],
      [message('m1', '2024-01-01T10:00:00Z')],
    );
    expect(merged.map((m) => m.message_id)).toEqual(['m1', 'm2']);
  });

  it('keeps the newer copy when a message is re-sent', () => {
    const merged = mergeMessages(
      [message('m1', '2024-01-01T10:00:00Z', 'first')],
      [message('m1', '2024-01-01T10:00:00Z', 'edited')],
    );
    expect(merged).toHaveLength(1);
    expect(merged[0].text).toBe('edited');
  });

  it('returns an empty list when a room has no history', () => {
    expect(mergeMessages([], [])).toEqual([]);
  });
});
