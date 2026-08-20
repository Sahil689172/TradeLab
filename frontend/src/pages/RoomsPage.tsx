/**
 * Lobby: list rooms, create one, and pick the handle you will trade under.
 *
 * The handle is trust-on-assertion — the backend takes the ?user= query
 * parameter at face value. When real auth lands it would replace this form
 * and the socket would read the identity from the session instead.
 */

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { collabApi } from '../api/collab';
import type { RoomSummary } from '../types/collab';
import { formatCurrency, formatTs } from '../utils/format';

interface RoomsPageProps {
  handle: string;
  onHandleChange: (handle: string) => void;
}

function RoomCard({
  room,
  disabled,
  onOpen,
}: {
  room: RoomSummary;
  disabled: boolean;
  onOpen: () => void;
}) {
  const full = room.members.length >= room.capacity;
  return (
    <li className="panel flex flex-col p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-slate-100">
            {room.name}
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">
            by {room.created_by} · {formatTs(room.created_at)}
          </p>
        </div>
        <span className="flex shrink-0 items-center gap-1.5">
          <span
            className={`status-dot ${
              room.online_members.length > 0 ? 'bg-terminal-buy' : 'bg-slate-700'
            }`}
          />
          <span className="font-mono text-[11px] text-slate-400">
            {room.online_members.length} live
          </span>
        </span>
      </div>

      <dl className="mt-3 grid grid-cols-3 gap-2 border-t border-terminal-border pt-3">
        <div>
          <dt className="text-[10px] uppercase tracking-wider text-slate-500">
            Members
          </dt>
          <dd className="font-mono text-sm text-slate-200">
            {room.members.length}/{room.capacity}
          </dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-wider text-slate-500">
            Messages
          </dt>
          <dd className="font-mono text-sm text-slate-200">{room.message_count}</dd>
        </div>
        <div>
          <dt className="text-[10px] uppercase tracking-wider text-slate-500">
            Capital
          </dt>
          <dd className="font-mono text-sm text-slate-200">
            {formatCurrency(room.initial_capital, 0)}
          </dd>
        </div>
      </dl>

      {room.members.length > 0 && (
        <p className="mt-2 truncate text-xs text-slate-500">
          {room.members.join(', ')}
        </p>
      )}

      <button
        type="button"
        onClick={onOpen}
        disabled={disabled}
        className="btn-primary mt-3"
        title={
          full && !room.members.includes('')
            ? 'This room is at capacity'
            : undefined
        }
      >
        {full ? 'Open (at capacity)' : 'Join room'}
      </button>
    </li>
  );
}

export function RoomsPage({ handle, onHandleChange }: RoomsPageProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [name, setName] = useState('');
  const [joinId, setJoinId] = useState('');
  const [formError, setFormError] = useState<string | null>(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['collab', 'rooms'],
    queryFn: () => collabApi.listRooms(),
    refetchInterval: 10_000,
  });

  const createRoom = useMutation({
    mutationFn: () =>
      collabApi.createRoom({ name: name.trim(), created_by: handle.trim() }),
    onSuccess: (room) => {
      queryClient.invalidateQueries({ queryKey: ['collab', 'rooms'] });
      setName('');
      navigate(`/rooms/${room.room_id}`);
    },
    onError: (err: Error) => setFormError(err.message),
  });

  const trimmedHandle = handle.trim();
  const canAct = trimmedHandle.length > 0;

  function open(roomId: string) {
    if (!canAct) {
      setFormError('Pick a handle first — it identifies you in the room.');
      return;
    }
    navigate(`/rooms/${roomId}`);
  }

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <section className="panel p-4">
        <h2 className="text-sm font-semibold text-slate-100">Your handle</h2>
        <p className="mt-0.5 text-xs text-slate-500">
          Shown next to everything you post and every order you place. No
          password — this build trusts the name you give.
        </p>
        <input
          value={handle}
          onChange={(event) => onHandleChange(event.target.value)}
          placeholder="e.g. sahil"
          aria-label="Your handle"
          className="input-field mt-2 max-w-xs"
          maxLength={40}
        />
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="panel p-4">
          <h2 className="text-sm font-semibold text-slate-100">Create a room</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Opens a fresh shared paper book with ₹10,00,000 of simulated cash.
          </p>
          <form
            className="mt-3 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              setFormError(null);
              if (!canAct) {
                setFormError('Pick a handle first.');
                return;
              }
              if (!name.trim()) return;
              createRoom.mutate();
            }}
          >
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="Room name"
              aria-label="Room name"
              className="input-field"
              maxLength={80}
            />
            <button
              type="submit"
              className="btn-primary whitespace-nowrap"
              disabled={createRoom.isPending || !name.trim()}
            >
              {createRoom.isPending ? 'Creating…' : 'Create'}
            </button>
          </form>
        </section>

        <section className="panel p-4">
          <h2 className="text-sm font-semibold text-slate-100">Join by ID</h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Paste a room ID someone shared with you.
          </p>
          <form
            className="mt-3 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              setFormError(null);
              if (joinId.trim()) open(joinId.trim());
            }}
          >
            <input
              value={joinId}
              onChange={(event) => setJoinId(event.target.value)}
              placeholder="Room ID"
              aria-label="Room ID"
              className="input-field font-mono"
            />
            <button
              type="submit"
              className="btn-primary whitespace-nowrap"
              disabled={!joinId.trim()}
            >
              Open
            </button>
          </form>
        </section>
      </div>

      {formError && (
        <p className="panel border-terminal-sell/40 p-3 text-sm text-terminal-sell">
          {formError}
        </p>
      )}

      <section>
        <div className="mb-2 flex items-center justify-between">
          <h2 className="panel-title">Open rooms</h2>
          <span className="text-[11px] text-slate-600">
            {data ? `${data.total} total` : ''}
          </span>
        </div>

        {isLoading && (
          <div className="grid gap-3 sm:grid-cols-2">
            {Array.from({ length: 2 }).map((_, index) => (
              <div key={index} className="panel h-44 animate-pulse bg-slate-800/40" />
            ))}
          </div>
        )}

        {isError && (
          <p className="panel p-4 text-sm text-terminal-sell">
            Could not load rooms: {(error as Error).message}
          </p>
        )}

        {data && data.rooms.length === 0 && (
          <p className="panel p-6 text-center text-sm text-slate-600">
            No rooms yet. Create one above and share its ID.
          </p>
        )}

        {data && data.rooms.length > 0 && (
          <ul className="grid gap-3 sm:grid-cols-2">
            {data.rooms.map((room) => (
              <RoomCard
                key={room.room_id}
                room={room}
                disabled={!canAct}
                onOpen={() => open(room.room_id)}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
