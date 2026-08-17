import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { DashboardSignal, StrategySignalRow } from '../../types/api';

interface StrategiesProps {
  symbol: string;
  timeframe: string;
}

function signalClass(signal: DashboardSignal): string {
  switch (signal) {
    case 'BUY':
      return 'signal-buy';
    case 'SELL':
      return 'signal-sell';
    default:
      return 'signal-neutral';
  }
}

function StrategyRow({ row }: { row: StrategySignalRow }) {
  return (
    <tr className="border-b border-terminal-border/50 hover:bg-slate-800/30">
      <td className="px-3 py-2 text-sm text-slate-200">{row.display_name}</td>
      <td className={`px-3 py-2 font-mono text-sm font-semibold ${signalClass(row.signal)}`}>
        {row.signal}
      </td>
      <td className="px-3 py-2 font-mono text-sm text-slate-300">
        {row.confidence.toFixed(0)}%
      </td>
      <td className="px-3 py-2 text-xs text-slate-500">{row.strength}</td>
      <td className="px-3 py-2 text-xs text-slate-500">{row.status}</td>
    </tr>
  );
}

export function Strategies({ symbol, timeframe }: StrategiesProps) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['strategy-analysis', symbol, timeframe],
    queryFn: () => api.getStrategyAnalysis(symbol, timeframe),
    retry: false,
  });

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Strategy Signals</span>
        {data && (
          <span className="text-[10px] text-slate-500">
            {data.strategies.length} strategies · {timeframe}
          </span>
        )}
      </div>

      {isLoading && (
        <div className="p-4 text-sm text-slate-500">Loading strategies…</div>
      )}

      {isError && (
        <div className="p-4 text-sm text-terminal-sell">
          Strategy data unavailable: {(error as Error).message}
        </div>
      )}

      {!isLoading && !isError && data && data.strategies.length === 0 && (
        <div className="p-4 text-sm text-slate-500">No strategy results</div>
      )}

      {!isLoading && !isError && data && data.strategies.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-terminal-border text-[11px] uppercase tracking-wider text-slate-500">
                <th className="px-3 py-2">Strategy</th>
                <th className="px-3 py-2">Signal</th>
                <th className="px-3 py-2">Confidence</th>
                <th className="px-3 py-2">Strength</th>
                <th className="px-3 py-2">Status</th>
              </tr>
            </thead>
            <tbody>
              {data.strategies.map((row) => (
                <StrategyRow key={row.strategy} row={row} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data?.data_note && (
        <p className="border-t border-terminal-border px-4 py-2 text-[10px] text-slate-500">
          {data.data_note}
        </p>
      )}
    </div>
  );
}
