/**
 * Centre pane: the room transcript plus the composer.
 *
 * The composer never appends locally — the server echoes every message back
 * over the socket, and the stream renders each message once by id.
 */

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { AIStatus, ChatMessage } from '../../types/collab';
import { MessageRow } from './MessageRow';

/** Treat "close enough to the bottom" as following the conversation. */
const STICK_THRESHOLD_PX = 80;

function AIUnavailableNotice({ status }: { status: AIStatus }) {
  const failure = status.last_error;
  return (
    <div className="border-b border-terminal-border bg-slate-900/60 px-4 py-2">
      <p className="text-xs text-slate-400">
        <span className="font-semibold text-terminal-warn">
          Assistant unavailable.
        </span>{' '}
        {failure
          ? `${failure.provider} could not be used${
              failure.is_auth_error ? ' — its API key was rejected' : ''
            }.`
          : 'No provider is currently reachable.'}{' '}
        Chat, trading, and market data are unaffected.
      </p>
      {failure?.hint && (
        <p className="mt-0.5 text-[11px] text-slate-600">Fix: {failure.hint}</p>
      )}
    </div>
  );
}

function AIThinkingIndicator({ askedBy }: { askedBy: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-2" aria-live="polite">
      <span className="flex gap-1" aria-hidden="true">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-terminal-accent" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-terminal-accent [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-terminal-accent [animation-delay:300ms]" />
      </span>
      <span className="text-xs text-slate-500">
        Assistant is reading the room for {askedBy}…
      </span>
    </div>
  );
}

interface ChatStreamProps {
  messages: ChatMessage[];
  aiThinkingFor: string | null;
  aiStatus: AIStatus | null;
  canSend: boolean;
  onSend: (text: string) => boolean;
  onShowStatus: () => void;
}

export function ChatStream({
  messages,
  aiThinkingFor,
  aiStatus,
  canSend,
  onSend,
  onShowStatus,
}: ChatStreamProps) {
  const [draft, setDraft] = useState('');
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);

  const trigger = aiStatus?.trigger ?? '@ai';
  const willAskAI =
    Boolean(aiStatus?.enabled) &&
    draft.toLowerCase().includes(trigger.toLowerCase());

  // Only auto-scroll when the reader was already at the bottom, so scrolling
  // back through the decision log is not yanked away by a new message.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node || !stickToBottom.current) return;
    node.scrollTop = node.scrollHeight;
  }, [messages, aiThinkingFor]);

  useLayoutEffect(() => {
    const node = scrollRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, []);

  function handleScroll() {
    const node = scrollRef.current;
    if (!node) return;
    const distance = node.scrollHeight - node.scrollTop - node.clientHeight;
    stickToBottom.current = distance < STICK_THRESHOLD_PX;
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    const text = draft.trim();
    if (!text || !canSend) return;
    stickToBottom.current = true;
    if (onSend(text)) setDraft('');
  }

  const assistantDown = aiStatus?.enabled && aiStatus.primary === 'none';

  return (
    <div className="panel flex h-full min-h-0 flex-col">
      <div className="panel-header">
        <span className="panel-title">Room chat</span>
        <span className="text-[11px] text-slate-600">
          {messages.length} message{messages.length === 1 ? '' : 's'}
        </span>
      </div>

      {assistantDown && aiStatus ? <AIUnavailableNotice status={aiStatus} /> : null}

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="min-h-0 flex-1 divide-y divide-transparent overflow-y-auto py-2"
        role="log"
        aria-label="Room transcript"
      >
        {messages.length === 0 ? (
          <p className="px-4 py-8 text-center text-sm text-slate-600">
            No messages yet. Post a trade idea, or type {trigger} to ask the
            assistant about a symbol.
          </p>
        ) : (
          messages.map((message) => (
            <MessageRow
              key={message.message_id}
              message={message}
              onShowStatus={onShowStatus}
            />
          ))
        )}
        {aiThinkingFor && <AIThinkingIndicator askedBy={aiThinkingFor} />}
      </div>

      <form
        onSubmit={submit}
        className="border-t border-terminal-border px-3 py-2.5"
      >
        <div className="flex gap-2">
          <input
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={
              canSend ? `Message the room, or ${trigger} to ask…` : 'Reconnecting…'
            }
            disabled={!canSend}
            aria-label="Message the room"
            className="input-field"
          />
          <button type="submit" className="btn-primary" disabled={!canSend || !draft.trim()}>
            Send
          </button>
        </div>
        <p className="mt-1.5 h-4 text-[11px] text-slate-600">
          {willAskAI ? (
            <span className="text-terminal-accent">
              This message will be sent to the assistant. Plain chat is free.
            </span>
          ) : (
            <span>
              Plain chat stays between members — include {trigger} to bring the
              assistant in.
            </span>
          )}
        </p>
      </form>
    </div>
  );
}
