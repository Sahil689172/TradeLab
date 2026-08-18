import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { formatCurrency, formatTs } from '../utils/format';
import type { OrderRow, OrderSide, OrderStatus } from '../types/api';

export function OrdersPage() {
  const [side, setSide] = useState<'ALL' | OrderSide>('ALL');
  const [status, setStatus] = useState<'ALL' | OrderStatus>('ALL');
  const [sortAsc, setSortAsc] = useState(false);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['orders'],
    queryFn: () => api.listOrders(),
    retry: false,
  });

  const rows = useMemo(() => {
    let list = data ?? [];
    if (side !== 'ALL') list = list.filter((r) => r.side === side);
    if (status !== 'ALL') list = list.filter((r) => r.status === status);
    return [...list].sort((a, b) => {
      const cmp = new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
      return sortAsc ? cmp : -cmp;
    });
  }, [data, side, status, sortAsc]);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {(['ALL', 'BUY', 'SELL'] as const).map((id) => (
          <button key={id} type="button" className={`rounded px-3 py-1 text-xs ${side === id ? 'bg-terminal-accent text-white' : 'text-slate-400'}`} onClick={() => setSide(id)}>
            {id}
          </button>
        ))}
        {(['ALL', 'FILLED', 'REJECTED', 'PENDING'] as const).map((id) => (
          <button key={id} type="button" className={`rounded px-3 py-1 text-xs ${status === id ? 'bg-slate-700 text-white' : 'text-slate-400'}`} onClick={() => setStatus(id)}>
            {id}
          </button>
        ))}
        <button type="button" className="ml-auto text-xs text-slate-400" onClick={() => setSortAsc((v) => !v)}>
          Time {sortAsc ? '↑' : '↓'}
        </button>
      </div>

      {isLoading && <div className="panel p-4 text-sm text-slate-500">Loading orders…</div>}
      {isError && <div className="panel p-4 text-sm text-terminal-sell">{(error as Error).message}</div>}
      {!isLoading && rows.length === 0 && <div className="panel p-4 text-sm text-slate-500">No paper orders yet.</div>}

      {rows.length > 0 && (
        <div className="panel overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-terminal-border text-[11px] uppercase text-slate-500">
                <th className="px-3 py-2">Time</th>
                <th className="px-3 py-2">Symbol</th>
                <th className="px-3 py-2">Side</th>
                <th className="px-3 py-2">Qty</th>
                <th className="px-3 py-2">Type</th>
                <th className="px-3 py-2">Requested</th>
                <th className="px-3 py-2">Fill</th>
                <th className="px-3 py-2">Stop</th>
                <th className="px-3 py-2">Target</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Reason</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row: OrderRow) => (
                <tr key={row.order_id} className="border-b border-terminal-border/40">
                  <td className="px-3 py-2 text-[11px] text-slate-500">{formatTs(row.timestamp)}</td>
                  <td className="px-3 py-2 font-mono">{row.symbol}</td>
                  <td className={`px-3 py-2 font-semibold ${row.side === 'BUY' ? 'signal-buy' : 'signal-sell'}`}>{row.side}</td>
                  <td className="px-3 py-2 font-mono">{row.quantity}</td>
                  <td className="px-3 py-2 text-xs">{row.order_type}</td>
                  <td className="px-3 py-2 font-mono">{formatCurrency(row.requested_price ?? row.price)}</td>
                  <td className="px-3 py-2 font-mono">{formatCurrency(row.execution_price)}</td>
                  <td className="px-3 py-2 font-mono">{formatCurrency(row.stop_loss)}</td>
                  <td className="px-3 py-2 font-mono">{formatCurrency(row.target)}</td>
                  <td className="px-3 py-2 text-xs">{row.status}</td>
                  <td className="px-3 py-2 text-xs text-terminal-warn">{row.rejection_reason ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
