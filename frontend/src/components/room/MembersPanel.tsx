/** Left pane: who is in the room and who is actually connected right now. */

import type { ConnectionState } from '../../hooks/useRoomSocket';
import type { AIStatus, RoomSummary } from '../../types/collab';
import { formatCurrency } from '../../utils/format';

const CONNECTION_LABEL: Record<ConnectionState, string> = {
  connecting: 'Connecting',
  open: 'Live',
  reconnecting: 'Reconnecting',
  closed: 'Disconnected',
  refused: 'Refused',
};

const CONNECTION_TONE: Record<ConnectionState, string> = {
  connecting: 'bg-terminal-warn text-terminal-warn',
  open: 'bg-terminal-buy text-terminal-buy',
  reconnecting: 'bg-terminal-warn text-terminal-warn',
  closed: 'bg-slate-500 text-slate-400',
  refused: 'bg-terminal-sell text-terminal-sell',
};

export function ConnectionBadge({ state }: { state: ConnectionState }) {
  const tone = CONNECTION_TONE[state];
  const [dot, text] = tone.split(' ');
  return (
    <span className="flex items-center gap-1.5">
      <span
        className={`status-dot ${dot} ${
          state === 'connecting' || state === 'reconnecting' ? 'animate-pulse' : ''
        }`}
      />
      <span className={`text-[11px] uppercase tracking-wider ${text}`}>
        {CONNECTION_LABEL[state]}
      </span>
    </span>
  );
}

interface MembersPanelProps {
  room: RoomSummary | null;
  onlineMembers: string[];
  currentUser: string;
  connection: ConnectionState;
  aiStatus: AIStatus | null;
}

export function MembersPanel({
  room,
  onlineMembers,
  currentUser,
  connection,
  aiStatus,
}: MembersPanelProps) {
  // Presence arrives over the socket; the roster comes from REST. Union the
  // two so a member who joined after our last fetch still appears.
  const roster = [...new Set([...(room?.members ?? []), ...onlineMembers])].sort();
  const online = new Set(onlineMembers);

  return (
    <div className="panel flex h-full flex-col">
      <div className="panel-header">
        <span className="panel-title">Room</span>
        <ConnectionBadge state={connection} />
      </div>

      <div className="border-b border-terminal-border px-4 py-3">
        <p className="truncate text-sm font-semibold text-slate-100" title={room?.name}>
          {room?.name ?? '—'}
        </p>
        <p className="mt-0.5 font-mono text-[11px] text-slate-600">
          {room?.room_id ?? ''}
        </p>
        <dl className="mt-3 grid grid-cols-2 gap-2">
          <div>
            <dt className="text-[10px] uppercase tracking-wider text-slate-500">
              Capacity
            </dt>
            <dd className="font-mono text-sm text-slate-200">
              {roster.length}/{room?.capacity ?? '—'}
            </dd>
          </div>
          <div>
            <dt className="text-[10px] uppercase tracking-wider text-slate-500">
              Starting cash
            </dt>
            <dd className="font-mono text-sm text-slate-200">
              {room ? formatCurrency(room.initial_capital, 0) : '—'}
            </dd>
          </div>
        </dl>
      </div>

      <div className="panel-header">
        <span className="panel-title">Members</span>
        <span className="font-mono text-[11px] text-slate-500">
          {online.size} online
        </span>
      </div>

      <ul className="flex-1 overflow-y-auto p-2">
        {roster.length === 0 && (
          <li className="px-2 py-3 text-xs text-slate-600">
            Nobody has joined yet.
          </li>
        )}
        {roster.map((member) => {
          const isOnline = online.has(member);
          return (
            <li
              key={member}
              className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-slate-800/50"
            >
              <span
                className={`status-dot ${
                  isOnline ? 'bg-terminal-buy' : 'bg-slate-700'
                }`}
                aria-hidden="true"
              />
              <span
                className={`truncate text-sm ${
                  isOnline ? 'text-slate-200' : 'text-slate-500'
                }`}
              >
                {member}
              </span>
              {member === currentUser && (
                <span className="ml-auto text-[10px] uppercase tracking-wider text-slate-600">
                  you
                </span>
              )}
              <span className="sr-only">{isOnline ? 'online' : 'offline'}</span>
            </li>
          );
        })}
      </ul>

      <div className="border-t border-terminal-border px-4 py-3">
        <p className="text-[10px] uppercase tracking-wider text-slate-500">
          Assistant
        </p>
        {aiStatus?.enabled ? (
          <p className="mt-1 text-xs text-slate-400">
            Type{' '}
            <code className="rounded bg-slate-800 px-1 font-mono text-slate-300">
              {aiStatus.trigger}
            </code>{' '}
            in a message to ask. Read-only — it cannot trade.
          </p>
        ) : (
          <p className="mt-1 text-xs text-slate-500">Disabled for this server.</p>
        )}
      </div>
    </div>
  );
}
