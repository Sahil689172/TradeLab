import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { PositionRow } from '../../types/api';

function formatCurrency(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(value);
}

function pnlClass(value: number): string {
  if (value > 0) return 'text-terminal-buy';
  if (value < 0) return 'text-terminal-sell';
  return 'text-slate-400';
}

function PositionTableRow({ row }: { row: PositionRow }) {
  return (
    <tr className="border-b border-terminal-border/50 hover:bg-slate-800/30">
      <td className="px-3 py-2 font-mono text-sm font-medium">{row.symbol}</td>
      <td className="px-3 py-2 font-mono text-sm">{row.quantity}</td>
      <td className="px-3 py-2 font-mono text-sm">
        {formatCurrency(row.average_price)}
      </td>
      <td className="px-3 py-2 font-mono text-sm">
        {formatCurrency(row.ltp)}
      </td>
      <td className="px-3 py-2 font-mono text-sm">
        {formatCurrency(row.current_value)}
      </td>
      <td className={`px-3 py-2 font-mono text-sm ${pnlClass(row.pnl)}`}>
        {formatCurrency(row.pnl)}
        <span className="ml-1 text-xs">({row.pnl_pct.toFixed(1)}%)</span>
      </td>
      <td className="px-3 py-2 text-xs text-slate-500">
        {row.strategy_name || '—'}
      </td>
    </tr>
  );
}

export function Positions() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['portfolio'],
    queryFn: () => api.getPortfolio(),
  });

  const positions = data?.positions ?? [];

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Open Positions</span>
        <span className="text-[10px] text-slate-500">
          {positions.length} position{positions.length !== 1 ? 's' : ''}
        </span>
      </div>

      {isLoading && (
        <div className="p-4 text-sm text-slate-500">Loading positions…</div>
      )}

      {isError && (
        <div className="p-4 text-sm text-terminal-sell">
          Positions unavailable: {(error as Error).message}
        </div>
      )}

      {!isLoading && !isError && positions.length === 0 && (
        <div className="p-4 text-sm text-slate-500">No open positions</div>
      )}

      {!isLoading && !isError && positions.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-terminal-border text-[11px] uppercase tracking-wider text-slate-500">
                <th className="px-3 py-2">Symbol</th>
                <th className="px-3 py-2">Qty</th>
                <th className="px-3 py-2">Avg Price</th>
                <th className="px-3 py-2">LTP</th>
                <th className="px-3 py-2">Value</th>
                <th className="px-3 py-2">P&L</th>
                <th className="px-3 py-2">Strategy</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((row) => (
                <PositionTableRow key={row.symbol} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
