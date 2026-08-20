/**
 * One room: members, transcript, and the shared paper book.
 *
 * Three panes side by side on a wide screen; they stack on narrow ones with
 * the transcript first, since that is what a phone-sized reader came for.
 */

import { useQuery } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { collabApi } from '../api/collab';
import { ChatStream } from '../components/room/ChatStream';
import { MembersPanel } from '../components/room/MembersPanel';
import { PortfolioPanel } from '../components/room/PortfolioPanel';
import { useRoomSocket } from '../hooks/useRoomSocket';

interface RoomPageProps {
  handle: string;
}

export function RoomPage({ handle }: RoomPageProps) {
  const { roomId } = useParams<{ roomId: string }>();
  const navigate = useNavigate();

  const { data: room } = useQuery({
    queryKey: ['collab', 'room', roomId],
    queryFn: () => collabApi.getRoom(roomId as string),
    enabled: Boolean(roomId),
    refetchInterval: 15_000,
  });

  const { data: aiStatus, refetch: refetchAiStatus } = useQuery({
    queryKey: ['collab', 'ai-status'],
    queryFn: () => collabApi.aiStatus(),
    staleTime: 30_000,
  });

  // Seeds the right pane before the first `portfolio` frame arrives; after
  // that the socket is the source of truth.
  const { data: seedPortfolio } = useQuery({
    queryKey: ['collab', 'portfolio', roomId],
    queryFn: () => collabApi.getPortfolio(roomId as string),
    enabled: Boolean(roomId),
  });

  const socket = useRoomSocket(roomId, handle);
  const live = socket.connection === 'open';
  const portfolio = socket.portfolio ?? seedPortfolio ?? null;

  if (!handle.trim()) {
    return (
      <div className="panel mx-auto max-w-md p-6 text-center">
        <p className="text-sm text-slate-300">
          Pick a handle before joining a room.
        </p>
        <Link to="/rooms" className="btn-primary mt-3 inline-block">
          Back to rooms
        </Link>
      </div>
    );
  }

  if (socket.connection === 'refused') {
    return (
      <div className="panel mx-auto max-w-md p-6 text-center">
        <p className="text-xs uppercase tracking-wider text-terminal-sell">
          Could not join
        </p>
        <p className="mt-2 text-sm text-slate-300">{socket.error}</p>
        <button
          type="button"
          onClick={() => navigate('/rooms')}
          className="btn-primary mt-4"
        >
          Back to rooms
        </button>
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          to="/rooms"
          className="text-xs text-slate-500 transition hover:text-slate-200"
        >
          ← Rooms
        </Link>
        <span className="text-sm font-semibold text-slate-100">
          {room?.name ?? 'Loading…'}
        </span>
        <span className="font-mono text-[11px] text-slate-600">{roomId}</span>
        <span className="ml-auto text-xs text-slate-500">
          trading as{' '}
          <span className="font-semibold text-slate-300">{handle}</span>
        </span>
      </div>

      {socket.error && (
        <p className="panel flex items-start gap-3 border-terminal-sell/40 p-2.5 text-xs text-terminal-sell">
          <span className="flex-1">{socket.error}</span>
          <button
            type="button"
            onClick={socket.clearError}
            className="text-slate-500 hover:text-slate-300"
            aria-label="Dismiss error"
          >
            ✕
          </button>
        </p>
      )}

      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[15rem_minmax(0,1fr)_19rem]">
        <div className="order-2 min-h-0 lg:order-1 lg:h-full">
          <MembersPanel
            room={room ?? null}
            onlineMembers={socket.onlineMembers}
            currentUser={handle}
            connection={socket.connection}
            aiStatus={aiStatus ?? null}
          />
        </div>

        <div className="order-1 min-h-[24rem] lg:order-2 lg:h-full lg:min-h-0">
          <ChatStream
            messages={socket.messages}
            aiThinkingFor={socket.aiThinkingFor}
            aiStatus={aiStatus ?? null}
            canSend={live}
            onSend={socket.sendChat}
            onShowStatus={() => void refetchAiStatus()}
          />
        </div>

        <div className="order-3 min-h-0 lg:h-full">
          <PortfolioPanel
            portfolio={portfolio}
            canTrade={live}
            onOrder={socket.sendOrder}
            onTradeIdea={socket.sendTradeIdea}
          />
        </div>
      </div>
    </div>
  );
}
