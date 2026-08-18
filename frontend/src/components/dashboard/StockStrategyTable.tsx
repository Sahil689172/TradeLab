import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { formatCurrency, formatTs } from '../../utils/format';
import type { DashboardSignal } from '../../types/api';

interface StockStrategyTableProps {
  symbol: string;
}

function signalClass(signal: DashboardSignal): string {
  if (signal === 'BUY') return 'signal-buy';
  if (signal === 'SELL') return 'signal-sell';
  return 'signal-neutral';
}

export function StockStrategyTable({ symbol }: StockStrategyTableProps) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['strategy-analysis', symbol, '1D'],
    queryFn: () => api.getStrategyAnalysis(symbol, '1D', false),
    retry: false,
  });

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Strategy results · 1D</span>
        {data && <span className="text-[10px] text-slate-500">{data.strategies.length} strategies</span>}
      </div>
      {isLoading && <div className="p-4 text-sm text-slate-500">Evaluating strategies…</div>}
      {isError && (
        <div className="p-4 text-sm text-terminal-sell">
          Strategy data unavailable: {(error as Error).message}
        </div>
      )}
      {data && data.strategies.length === 0 && (
        <div className="p-4 text-sm text-slate-500">
          {data.data_note || 'No strategy results. Bootstrap OHLCV first.'}
        </div>
      )}
      {data && data.strategies.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-terminal-border text-[11px] uppercase tracking-wider text-slate-500">
                <th className="px-3 py-2">Strategy</th>
                <th className="px-3 py-2">Signal</th>
                <th className="px-3 py-2">Action</th>
                <th className="px-3 py-2">Price</th>
                <th className="px-3 py-2">Stop</th>
                <th className="px-3 py-2">Target</th>
                <th className="px-3 py-2">Score</th>
                <th className="px-3 py-2">TF</th>
                <th className="px-3 py-2">Evaluated</th>
              </tr>
            </thead>
            <tbody>
              {data.strategies.map((row) => (
                <tr key={row.strategy} className="border-b border-terminal-border/40">
                  <td className="px-3 py-2 text-slate-200">{row.display_name}</td>
                  <td className={`px-3 py-2 font-mono font-semibold ${signalClass(row.signal)}`}>
                    {row.signal}
                  </td>
                  <td className="px-3 py-2 text-xs text-slate-400">{row.recommended_action}</td>
                  <td className="px-3 py-2 font-mono">{formatCurrency(row.current_price ?? row.entry_price)}</td>
                  <td className="px-3 py-2 font-mono">{formatCurrency(row.stop_loss)}</td>
                  <td className="px-3 py-2 font-mono">{formatCurrency(row.target)}</td>
                  <td className="px-3 py-2 font-mono" title={row.confidence_label}>
                    {row.confidence.toFixed(0)}
                    <span className="ml-1 text-[10px] text-slate-500">score</span>
                  </td>
                  <td className="px-3 py-2 text-xs">{row.best_timeframe}</td>
                  <td className="px-3 py-2 text-[10px] text-slate-500">{formatTs(row.last_evaluated)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data?.data_note && (
        <p className="border-t border-terminal-border px-4 py-2 text-[10px] text-slate-500">{data.data_note}</p>
      )}
    </div>
  );
}
