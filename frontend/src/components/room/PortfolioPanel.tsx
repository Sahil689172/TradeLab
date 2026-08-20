/**
 * Right pane: the room's shared paper book.
 *
 * Values come from the `portfolio` websocket frame so the panel moves when
 * the *other* member trades — that live shared book is the whole point of a
 * room. The REST fetch only seeds the panel before the first frame arrives.
 */

import { useState } from 'react';
import type { PortfolioResponse } from '../../types/api';
import type { RoomOrderRequest, TradeDirection } from '../../types/collab';
import { formatCurrency, formatPct, pnlClass } from '../../utils/format';

type OrderDraft = Omit<RoomOrderRequest, 'author'>;

interface PortfolioPanelProps {
  portfolio: PortfolioResponse | null;
  canTrade: boolean;
  onOrder: (order: OrderDraft) => boolean;
  onTradeIdea: (idea: {
    symbol: string;
    direction: TradeDirection;
    thesis: string;
    entry: number | null;
    stop_loss: number | null;
    target: number | null;
  }) => boolean;
}

function Kpi({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`font-mono text-sm font-semibold ${tone ?? 'text-slate-100'}`}>
        {value}
      </p>
    </div>
  );
}

/** Optional numeric input — blank means "let the server decide". */
function optionalNumber(raw: string): number | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

function OrderForm({
  canTrade,
  onOrder,
}: {
  canTrade: boolean;
  onOrder: (order: OrderDraft) => boolean;
}) {
  const [symbol, setSymbol] = useState('');
  const [quantity, setQuantity] = useState('');
  const [price, setPrice] = useState('');

  function place(side: 'BUY' | 'SELL') {
    const qty = Number(quantity);
    if (!symbol.trim() || !Number.isFinite(qty) || qty <= 0) return;
    const sent = onOrder({
      side,
      symbol: symbol.trim().toUpperCase(),
      quantity: qty,
      price: optionalNumber(price),
    });
    if (sent) {
      setQuantity('');
      setPrice('');
    }
  }

  return (
    <div className="border-t border-terminal-border px-3 py-3">
      <p className="mb-2 text-[10px] uppercase tracking-wider text-slate-500">
        Place a simulated order
      </p>
      <div className="grid grid-cols-3 gap-2">
        <input
          value={symbol}
          onChange={(event) => setSymbol(event.target.value)}
          placeholder="SYMBOL"
          aria-label="Order symbol"
          className="input-field col-span-3 font-mono uppercase"
        />
        <input
          value={quantity}
          onChange={(event) => setQuantity(event.target.value)}
          placeholder="Qty"
          inputMode="decimal"
          aria-label="Order quantity"
          className="input-field font-mono"
        />
        <input
          value={price}
          onChange={(event) => setPrice(event.target.value)}
          placeholder="Price (opt)"
          inputMode="decimal"
          aria-label="Order price, optional"
          className="input-field col-span-2 font-mono"
        />
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        <button
          type="button"
          className="btn-buy"
          disabled={!canTrade}
          onClick={() => place('BUY')}
        >
          Buy
        </button>
        <button
          type="button"
          className="btn-sell"
          disabled={!canTrade}
          onClick={() => place('SELL')}
        >
          Sell
        </button>
      </div>
      <p className="mt-1.5 text-[10px] text-slate-600">
        Leave price blank to fill at the last stored close.
      </p>
    </div>
  );
}

function TradeIdeaForm({
  canTrade,
  onTradeIdea,
}: {
  canTrade: boolean;
  onTradeIdea: PortfolioPanelProps['onTradeIdea'];
}) {
  const [open, setOpen] = useState(false);
  const [symbol, setSymbol] = useState('');
  const [direction, setDirection] = useState<TradeDirection>('LONG');
  const [thesis, setThesis] = useState('');
  const [entry, setEntry] = useState('');
  const [stop, setStop] = useState('');
  const [target, setTarget] = useState('');

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!symbol.trim()) return;
    const sent = onTradeIdea({
      symbol: symbol.trim().toUpperCase(),
      direction,
      thesis: thesis.trim(),
      entry: optionalNumber(entry),
      stop_loss: optionalNumber(stop),
      target: optionalNumber(target),
    });
    if (!sent) return;
    setSymbol('');
    setThesis('');
    setEntry('');
    setStop('');
    setTarget('');
    setOpen(false);
  }

  if (!open) {
    return (
      <div className="border-t border-terminal-border px-3 py-2.5">
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="w-full rounded border border-terminal-border px-3 py-1.5 text-sm text-slate-300 transition hover:border-terminal-accent hover:text-terminal-accent"
        >
          Post a trade idea
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="border-t border-terminal-border px-3 py-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[10px] uppercase tracking-wider text-slate-500">
          Trade idea
        </p>
        <button
          type="button"
          onClick={() => setOpen(false)}
          className="text-xs text-slate-500 hover:text-slate-300"
        >
          Cancel
        </button>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <input
          value={symbol}
          onChange={(event) => setSymbol(event.target.value)}
          placeholder="SYMBOL"
          aria-label="Idea symbol"
          className="input-field font-mono uppercase"
        />
        <div className="grid grid-cols-2 gap-1">
          {(['LONG', 'SHORT'] as const).map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => setDirection(option)}
              className={`rounded px-2 py-1.5 text-xs font-semibold transition ${
                direction === option
                  ? option === 'LONG'
                    ? 'bg-terminal-buy/20 text-terminal-buy'
                    : 'bg-terminal-sell/20 text-terminal-sell'
                  : 'border border-terminal-border text-slate-500 hover:text-slate-300'
              }`}
              aria-pressed={direction === option}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      <textarea
        value={thesis}
        onChange={(event) => setThesis(event.target.value)}
        placeholder="Why this trade?"
        rows={2}
        aria-label="Thesis"
        className="input-field mt-2 resize-none"
      />

      <div className="mt-2 grid grid-cols-3 gap-2">
        <input
          value={entry}
          onChange={(event) => setEntry(event.target.value)}
          placeholder="Entry"
          inputMode="decimal"
          aria-label="Entry"
          className="input-field font-mono"
        />
        <input
          value={stop}
          onChange={(event) => setStop(event.target.value)}
          placeholder="Stop"
          inputMode="decimal"
          aria-label="Stop loss"
          className="input-field font-mono"
        />
        <input
          value={target}
          onChange={(event) => setTarget(event.target.value)}
          placeholder="Target"
          inputMode="decimal"
          aria-label="Target"
          className="input-field font-mono"
        />
      </div>

      <button type="submit" className="btn-primary mt-2 w-full" disabled={!canTrade}>
        Post idea
      </button>
      <p className="mt-1.5 text-[10px] text-slate-600">
        The current price is stamped on the idea so the call can be scored later.
      </p>
    </form>
  );
}

export function PortfolioPanel({
  portfolio,
  canTrade,
  onOrder,
  onTradeIdea,
}: PortfolioPanelProps) {
  const kpis = portfolio?.kpis;
  const positions = portfolio?.positions ?? [];

  return (
    <div className="panel flex h-full min-h-0 flex-col">
      <div className="panel-header">
        <span className="panel-title">Shared book</span>
        <span
          className="rounded bg-terminal-warn/15 px-1.5 py-0.5 text-[10px] uppercase tracking-wider text-terminal-warn"
          title="No real money is involved. Orders fill against stored end-of-day prices."
        >
          Simulated
        </span>
      </div>

      <dl className="grid grid-cols-2 divide-x divide-y divide-terminal-border border-b border-terminal-border">
        <Kpi
          label="Current value"
          value={kpis ? formatCurrency(kpis.current_value, 0) : '—'}
        />
        <Kpi label="Cash" value={kpis ? formatCurrency(kpis.available_cash, 0) : '—'} />
        <Kpi
          label="Invested"
          value={kpis ? formatCurrency(kpis.total_invested, 0) : '—'}
        />
        <Kpi
          label="Exposure"
          value={kpis ? formatPct(kpis.exposure_pct) : '—'}
        />
        <Kpi
          label="Unrealised P&L"
          value={kpis ? formatCurrency(kpis.unrealized_pnl, 0) : '—'}
          tone={kpis ? pnlClass(kpis.unrealized_pnl) : undefined}
        />
        <Kpi
          label="Realised P&L"
          value={kpis ? formatCurrency(kpis.realized_pnl, 0) : '—'}
          tone={kpis ? pnlClass(kpis.realized_pnl) : undefined}
        />
      </dl>

      <div className="panel-header">
        <span className="panel-title">Open positions</span>
        <span className="font-mono text-[11px] text-slate-500">
          {positions.length}
        </span>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {positions.length === 0 ? (
          <p className="px-4 py-6 text-center text-xs text-slate-600">
            No open positions in this room.
          </p>
        ) : (
          <table className="w-full text-left">
            <thead className="sticky top-0 bg-terminal-panel">
              <tr className="text-[10px] uppercase tracking-wider text-slate-500">
                <th className="px-3 py-1.5 font-medium">Symbol</th>
                <th className="px-2 py-1.5 text-right font-medium">Qty</th>
                <th className="px-2 py-1.5 text-right font-medium">Avg</th>
                <th className="px-3 py-1.5 text-right font-medium">P&L</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => (
                <tr
                  key={position.symbol}
                  className="border-t border-terminal-border/60 hover:bg-slate-800/40"
                >
                  <td className="px-3 py-1.5 font-mono text-xs text-slate-200">
                    {position.symbol}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-xs text-slate-300">
                    {position.quantity}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono text-xs text-slate-400">
                    {formatCurrency(position.average_price)}
                  </td>
                  <td
                    className={`px-3 py-1.5 text-right font-mono text-xs ${pnlClass(
                      position.pnl,
                    )}`}
                  >
                    {formatCurrency(position.pnl, 0)}
                    <span className="ml-1 text-[10px] opacity-70">
                      {formatPct(position.pnl_pct)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <OrderForm canTrade={canTrade} onOrder={onOrder} />
      <TradeIdeaForm canTrade={canTrade} onTradeIdea={onTradeIdea} />
    </div>
  );
}
