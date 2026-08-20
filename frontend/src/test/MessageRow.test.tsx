import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MessageRow } from '../components/room/MessageRow';
import type { ChatMessage, MessageKind } from '../types/collab';

function build(kind: MessageKind, overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    message_id: 'm1',
    room_id: 'room-1',
    author: 'sahil',
    kind,
    text: 'hello desk',
    created_at: '2024-01-01T10:00:00Z',
    trade_idea: null,
    ai_source: null,
    ai_tools_used: [],
    metadata: {},
    ...overrides,
  };
}

describe('MessageRow', () => {
  it('shows author and text for plain chat', () => {
    render(<MessageRow message={build('CHAT')} />);
    expect(screen.getByText('sahil')).toBeInTheDocument();
    expect(screen.getByText('hello desk')).toBeInTheDocument();
  });

  it('surfaces price_at_post prominently on a trade idea', () => {
    render(
      <MessageRow
        message={build('TRADE_IDEA', {
          trade_idea: {
            symbol: 'RELIANCE',
            direction: 'LONG',
            thesis: 'Breakout above range',
            entry: 1300,
            stop_loss: 1250,
            target: 1400,
            price_at_post: 1288.5,
          },
        })}
      />,
    );
    expect(screen.getByText('RELIANCE')).toBeInTheDocument();
    expect(screen.getByText('LONG')).toBeInTheDocument();
    expect(screen.getByText(/Price when posted/i)).toBeInTheDocument();
    expect(screen.getByText(/1,288.50/)).toBeInTheDocument();
  });

  it('says so plainly when a call could not be priced', () => {
    render(
      <MessageRow
        message={build('TRADE_IDEA', {
          trade_idea: {
            symbol: 'TCS',
            direction: 'SHORT',
            thesis: '',
            entry: null,
            stop_loss: null,
            target: null,
            price_at_post: null,
          },
        })}
      />,
    );
    expect(screen.getByText('unavailable')).toBeInTheDocument();
  });

  it('marks a rejected order with its reason', () => {
    render(
      <MessageRow
        message={build('ORDER_EVENT', {
          text: 'No local price for FOO.',
          metadata: { accepted: false, reason: 'NO_PRICE' },
        })}
      />,
    );
    expect(screen.getByText(/NO_PRICE/)).toBeInTheDocument();
  });

  it('labels a filled order with its status', () => {
    render(
      <MessageRow
        message={build('ORDER_EVENT', {
          text: 'BUY 10 RELIANCE filled',
          metadata: { accepted: true, status: 'FILLED', side: 'BUY' },
        })}
      />,
    );
    expect(screen.getByText('FILLED')).toBeInTheDocument();
  });

  it('shows the provider badge and the tools that grounded an AI reply', () => {
    render(
      <MessageRow
        message={build('AI_REPLY', {
          author: 'AI',
          text: 'RELIANCE last closed at 1288.50.',
          ai_source: 'groq',
          ai_tools_used: ['get_latest_price', 'get_room_portfolio'],
          metadata: { model: 'llama-3.3-70b-versatile', fell_back: true },
        })}
      />,
    );
    expect(screen.getByText('groq')).toBeInTheDocument();
    expect(screen.getByText('get_latest_price')).toBeInTheDocument();
    expect(screen.getByText('get_room_portfolio')).toBeInTheDocument();
    expect(screen.getByText('fell back')).toBeInTheDocument();
  });

  it('offers a route to the reason when the assistant is unavailable', () => {
    render(
      <MessageRow
        message={build('AI_REPLY', {
          author: 'AI',
          text: 'I could not reach any AI provider just now.',
          ai_source: 'none',
          ai_tools_used: [],
        })}
        onShowStatus={() => undefined}
      />,
    );
    expect(screen.getByText(/Why is the assistant unavailable/i)).toBeInTheDocument();
    // A dead provider must not be dressed up as a working one.
    expect(screen.queryByText('fell back')).not.toBeInTheDocument();
  });
});
