import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { DashboardSignal, TimeframeBestStrategy } from '../../types/api';

interface TimeframeMatrixProps {
  symbol: string;
}

function signalClass(signal: DashboardSignal | null): string {
  switch (signal) {
    case 'BUY':
      return 'signal-buy';
    case 'SELL':
      return 'signal-sell';
    default:
      return 'signal-neutral';
  }
}

function MatrixCell({ cell }: { cell: TimeframeBestStrategy }) {
  if (!cell.supported) {
    return (
      <div className="rounded border border-dashed border-terminal-border bg-terminal-bg/50 p-2 text-center">
        <p className="font-mono text-xs text-slate-500">{cell.interval}</p>
        <p className="mt-1 text-[10px] text-terminal-warn">Unsupported</p>
        {cell.message && (
          <p className="mt-1 text-[9px] leading-tight text-slate-600">
            {cell.message}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="rounded border border-terminal-border bg-terminal-bg p-2">
      <p className="font-mono text-xs text-slate-400">{cell.interval}</p>
      <p className={`mt-1 font-mono text-sm font-semibold ${signalClass(cell.signal)}`}>
        {cell.signal ?? '—'}
      </p>
      {cell.best_strategy_display && (
        <p className="mt-0.5 truncate text-[10px] text-slate-500">
          {cell.best_strategy_display}
        </p>
      )}
      {cell.confidence != null && (
        <p className="font-mono text-[10px] text-slate-400">
          {cell.confidence.toFixed(0)}%
        </p>
      )}
    </div>
  );
}

export function TimeframeMatrix({ symbol }: TimeframeMatrixProps) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['strategy-analysis', symbol, '1D'],
    queryFn: () => api.getStrategyAnalysis(symbol, '1D'),
    retry: false,
  });

  const matrix = data?.timeframe_matrix ?? [];

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Timeframe Matrix</span>
      </div>

      {isLoading && (
        <div className="p-4 text-sm text-slate-500">Loading matrix…</div>
      )}

      {isError && (
        <div className="p-4 text-sm text-terminal-sell">
          Matrix unavailable: {(error as Error).message}
        </div>
      )}

      {!isLoading && !isError && matrix.length === 0 && (
        <div className="p-4 text-sm text-slate-500">No timeframe data</div>
      )}

      {!isLoading && !isError && matrix.length > 0 && (
        <div className="grid grid-cols-3 gap-2 p-3 sm:grid-cols-4 lg:grid-cols-7">
          {matrix.map((cell) => (
            <MatrixCell key={cell.interval} cell={cell} />
          ))}
        </div>
      )}
    </div>
  );
}
