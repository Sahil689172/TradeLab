import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { TimeframeMatrix } from '../components/dashboard/TimeframeMatrix';
import { formatTs } from '../utils/format';

interface StrategiesPageProps {
  symbol: string;
}

export function StrategiesPage({ symbol }: StrategiesPageProps) {
  const catalog = useQuery({
    queryKey: ['strategy-catalog'],
    queryFn: () => api.listStrategies(),
  });
  const analysis = useQuery({
    queryKey: ['strategy-analysis-matrix', symbol],
    queryFn: () => api.getStrategyAnalysis(symbol, '1D', true),
    retry: false,
  });

  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-500">
        Results for <span className="font-mono text-slate-300">{symbol}</span> from the backend registry.
        Score is Historical/Model Confidence, not probability of future profit.
      </p>

      <TimeframeMatrix symbol={symbol} includeMatrix />

      {analysis.data && (
        <div className="panel overflow-x-auto">
          <div className="panel-header">
            <span className="panel-title">All strategies · {symbol} · 1D</span>
          </div>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-terminal-border text-[11px] uppercase text-slate-500">
                <th className="px-3 py-2">Name</th>
                <th className="px-3 py-2">Signal</th>
                <th className="px-3 py-2">Score</th>
                <th className="px-3 py-2">Timeframe</th>
                <th className="px-3 py-2">Window</th>
                <th className="px-3 py-2">Samples</th>
                <th className="px-3 py-2">Evaluated</th>
              </tr>
            </thead>
            <tbody>
              {analysis.data.strategies.map((row) => (
                <tr key={row.strategy} className="border-b border-terminal-border/40">
                  <td className="px-3 py-2">{row.display_name}</td>
                  <td className="px-3 py-2 font-mono">{row.signal}</td>
                  <td className="px-3 py-2 font-mono" title={row.confidence_label}>{row.confidence.toFixed(0)}</td>
                  <td className="px-3 py-2">{row.best_timeframe}</td>
                  <td className="px-3 py-2 text-[10px] text-slate-500">{row.evaluation_window || '—'}</td>
                  <td className="px-3 py-2 font-mono">{row.sample_size}</td>
                  <td className="px-3 py-2 text-[10px] text-slate-500">{formatTs(row.last_evaluated)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="panel">
        <div className="panel-header">
          <span className="panel-title">Registry ({catalog.data?.length ?? 0})</span>
        </div>
        <div className="divide-y divide-terminal-border">
          {(catalog.data ?? []).map((item) => (
            <div key={item.name} className="px-4 py-3">
              <p className="text-sm text-slate-200">{item.display_name}</p>
              <p className="font-mono text-[11px] text-slate-500">{item.name}</p>
              <p className="mt-1 text-xs text-slate-400">{item.description || 'Registered strategy. Daily stored OHLCV is the supported evaluation timeframe.'}</p>
              <p className="mt-1 text-[10px] text-slate-500">
                Supported timeframes:{' '}
                {(item.supported_timeframes?.length ? item.supported_timeframes : ['1D', '1W', '1M']).join(', ')}
              </p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
