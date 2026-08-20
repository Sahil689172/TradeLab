/**
 * One row of the room transcript.
 *
 * Each MessageKind gets its own shape rather than a styled bubble, because
 * the transcript doubles as the decision log for the room's trades: a reader
 * scanning it later needs to tell a claim from a fill at a glance.
 */

import type { ChatMessage, TradeIdea } from '../../types/collab';
import { formatCurrency } from '../../utils/format';

function clockTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], {
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  } catch {
    return '--:--';
  }
}

/** Stable per-author tint so two speakers stay distinguishable. */
const AUTHOR_TINTS = [
  'text-sky-300',
  'text-amber-300',
  'text-violet-300',
  'text-teal-300',
];

function authorTint(author: string): string {
  let hash = 0;
  for (let i = 0; i < author.length; i += 1) {
    hash = (hash * 31 + author.charCodeAt(i)) >>> 0;
  }
  return AUTHOR_TINTS[hash % AUTHOR_TINTS.length];
}

function Stamp({ iso }: { iso: string }) {
  return (
    <time
      dateTime={iso}
      className="shrink-0 font-mono text-[11px] leading-6 text-slate-600"
    >
      {clockTime(iso)}
    </time>
  );
}

// ---------------------------------------------------------------------------

function ChatRow({ message }: { message: ChatMessage }) {
  return (
    <div className="flex gap-3 px-4 py-1.5 hover:bg-slate-900/40">
      <Stamp iso={message.created_at} />
      <p className="min-w-0 text-sm leading-6 text-slate-200">
        <span className={`mr-2 font-semibold ${authorTint(message.author)}`}>
          {message.author}
        </span>
        <span className="break-words">{message.text}</span>
      </p>
    </div>
  );
}

function SystemRow({ message }: { message: ChatMessage }) {
  return (
    <div className="flex gap-3 px-4 py-1">
      <Stamp iso={message.created_at} />
      <p className="text-xs italic leading-6 text-slate-600">{message.text}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------

function Level({
  label,
  value,
  tone,
}: {
  label: string;
  value: number | null;
  tone?: string;
}) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-slate-500">
        {label}
      </dt>
      <dd className={`font-mono text-sm ${tone ?? 'text-slate-200'}`}>
        {value == null ? '—' : formatCurrency(value)}
      </dd>
    </div>
  );
}

function TradeIdeaRow({ message }: { message: ChatMessage }) {
  const idea = message.trade_idea as TradeIdea | null;
  if (!idea) return <ChatRow message={message} />;

  const isLong = idea.direction === 'LONG';

  return (
    <div className="flex gap-3 px-4 py-2">
      <Stamp iso={message.created_at} />
      <article className="min-w-0 flex-1 rounded border border-terminal-border bg-terminal-bg/60">
        <header className="flex flex-wrap items-center gap-2 border-b border-terminal-border px-3 py-2">
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] font-bold tracking-wider ${
              isLong
                ? 'bg-terminal-buy/15 text-terminal-buy'
                : 'bg-terminal-sell/15 text-terminal-sell'
            }`}
          >
            {idea.direction}
          </span>
          <span className="font-mono text-sm font-semibold text-slate-100">
            {idea.symbol}
          </span>
          <span className="text-xs text-slate-500">
            called by{' '}
            <span className={authorTint(message.author)}>{message.author}</span>
          </span>

          {/* The scoreable field: what the market said when the call was made. */}
          <span className="ml-auto flex items-baseline gap-1.5 rounded bg-slate-800/70 px-2 py-1">
            <span className="text-[10px] uppercase tracking-wider text-slate-400">
              Price when posted
            </span>
            <span className="font-mono text-sm font-semibold text-slate-100">
              {idea.price_at_post == null
                ? 'unavailable'
                : formatCurrency(idea.price_at_post)}
            </span>
          </span>
        </header>

        {idea.thesis && (
          <p className="whitespace-pre-wrap px-3 py-2 text-sm leading-6 text-slate-300">
            {idea.thesis}
          </p>
        )}

        <dl className="grid grid-cols-3 gap-3 border-t border-terminal-border px-3 py-2">
          <Level label="Entry" value={idea.entry} />
          <Level label="Stop loss" value={idea.stop_loss} tone="text-terminal-sell" />
          <Level label="Target" value={idea.target} tone="text-terminal-buy" />
        </dl>
      </article>
    </div>
  );
}

// ---------------------------------------------------------------------------

function OrderEventRow({ message }: { message: ChatMessage }) {
  // `accepted` is the one key present on both the filled and the no-price
  // rejection path; `status` is absent when the symbol had no local price.
  const meta = message.metadata ?? {};
  const rejected = meta.accepted === false;
  const status = typeof meta.status === 'string' ? meta.status : null;
  const reason = typeof meta.reason === 'string' ? meta.reason : null;

  return (
    <div className="flex gap-3 px-4 py-1.5">
      <Stamp iso={message.created_at} />
      <div
        className={`min-w-0 flex-1 border-l-2 pl-3 ${
          rejected ? 'border-terminal-sell' : 'border-terminal-buy'
        }`}
      >
        <p className="flex flex-wrap items-baseline gap-2 text-sm leading-6">
          <span
            className={`text-[10px] font-bold uppercase tracking-wider ${
              rejected ? 'text-terminal-sell' : 'text-terminal-buy'
            }`}
          >
            {status ?? (rejected ? 'Rejected' : 'Order')}
          </span>
          <span className={rejected ? 'text-terminal-sell' : 'text-terminal-buy'}>
            {message.text}
          </span>
        </p>
        <p className="text-[11px] leading-5 text-slate-600">
          placed by {message.author}
          {rejected && reason ? ` · ${reason}` : ''}
        </p>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------

/** Which provider answered, and whether it was the fallback. */
function ProviderBadge({ message }: { message: ChatMessage }) {
  const source = message.ai_source;
  const fellBack = Boolean(message.metadata?.fell_back);
  if (!source || source === 'none') return null;

  return (
    <>
      <span className="rounded bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] uppercase tracking-wider text-slate-300">
        {source}
      </span>
      {fellBack && (
        <span
          className="rounded bg-terminal-warn/15 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-terminal-warn"
          title="The primary provider failed, so the fallback answered this."
        >
          fell back
        </span>
      )}
    </>
  );
}

function AIReplyRow({
  message,
  onShowStatus,
}: {
  message: ChatMessage;
  onShowStatus?: () => void;
}) {
  const unavailable = message.ai_source === 'none';
  const tools = message.ai_tools_used ?? [];

  return (
    <div className="flex gap-3 px-4 py-2">
      <Stamp iso={message.created_at} />
      <article
        className={`min-w-0 flex-1 border-l-2 pl-3 ${
          unavailable ? 'border-slate-700' : 'border-terminal-accent'
        }`}
      >
        <header className="flex flex-wrap items-center gap-2">
          <span
            className={`text-xs font-semibold uppercase tracking-wider ${
              unavailable ? 'text-slate-500' : 'text-terminal-accent'
            }`}
          >
            Assistant
          </span>
          <ProviderBadge message={message} />
          <span className="text-[10px] uppercase tracking-wider text-slate-600">
            read-only
          </span>
        </header>

        <p className="whitespace-pre-wrap py-1 text-sm leading-6 text-slate-300">
          {message.text}
        </p>

        {tools.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5 pb-0.5">
            <span className="text-[10px] uppercase tracking-wider text-slate-600">
              Grounded in
            </span>
            {tools.map((tool, index) => (
              <span
                key={`${tool}-${index}`}
                className="rounded border border-terminal-border px-1.5 py-0.5 font-mono text-[10px] text-slate-400"
              >
                {tool}
              </span>
            ))}
          </div>
        ) : (
          !unavailable && (
            <p className="pb-0.5 text-[10px] uppercase tracking-wider text-slate-600">
              No tools called — answered from the conversation only
            </p>
          )
        )}

        {unavailable && onShowStatus && (
          <button
            type="button"
            onClick={onShowStatus}
            className="pb-0.5 text-xs text-slate-400 underline underline-offset-2 hover:text-slate-200"
          >
            Why is the assistant unavailable?
          </button>
        )}
      </article>
    </div>
  );
}

// ---------------------------------------------------------------------------

export function MessageRow({
  message,
  onShowStatus,
}: {
  message: ChatMessage;
  onShowStatus?: () => void;
}) {
  switch (message.kind) {
    case 'TRADE_IDEA':
      return <TradeIdeaRow message={message} />;
    case 'ORDER_EVENT':
      return <OrderEventRow message={message} />;
    case 'AI_REPLY':
      return <AIReplyRow message={message} onShowStatus={onShowStatus} />;
    case 'SYSTEM':
      return <SystemRow message={message} />;
    case 'CHAT':
    default:
      return <ChatRow message={message} />;
  }
}
