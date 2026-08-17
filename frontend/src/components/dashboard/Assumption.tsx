import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { AssumptionBias } from '../../types/api';

interface AssumptionProps {
  symbol: string;
  timeframe: string;
}

function biasClass(bias: AssumptionBias): string {
  switch (bias) {
    case 'BULLISH':
      return 'text-terminal-buy';
    case 'BEARISH':
      return 'text-terminal-sell';
    default:
      return 'text-slate-400';
  }
}

function biasIcon(bias: AssumptionBias): string {
  switch (bias) {
    case 'BULLISH':
      return '▲';
    case 'BEARISH':
      return '▼';
    default:
      return '●';
  }
}

export function Assumption({ symbol, timeframe }: AssumptionProps) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['strategy-analysis', symbol, timeframe],
    queryFn: () => api.getStrategyAnalysis(symbol, timeframe),
    retry: false,
  });

  const assumption = data?.assumption;

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Current Assumption</span>
        {assumption && (
          <span className="text-[10px] text-slate-500">{timeframe}</span>
        )}
      </div>

      {isLoading && (
        <div className="p-4 text-sm text-slate-500">Loading assumption…</div>
      )}

      {isError && (
        <div className="p-4 text-sm text-terminal-sell">
          Assumption unavailable: {(error as Error).message}
        </div>
      )}

      {!isLoading && !isError && !assumption && (
        <div className="p-4 text-sm text-slate-500">No assumption data</div>
      )}

      {assumption && (
        <div className="p-4">
          <div className="flex items-center gap-2">
            <span className={`text-2xl ${biasClass(assumption.bias)}`}>
              {biasIcon(assumption.bias)}
            </span>
            <div>
              <p className={`text-lg font-semibold ${biasClass(assumption.bias)}`}>
                {assumption.bias}
              </p>
              {assumption.confidence != null && (
                <p className="font-mono text-sm text-slate-400">
                  {assumption.confidence.toFixed(0)}% confidence
                </p>
              )}
            </div>
          </div>

          {assumption.explanation && (
            <p className="mt-3 text-sm leading-relaxed text-slate-400">
              {assumption.explanation}
            </p>
          )}

          {assumption.supporting_strategies.length > 0 && (
            <div className="mt-3">
              <p className="text-[11px] uppercase tracking-wider text-slate-500">
                Supporting Strategies
              </p>
              <div className="mt-1 flex flex-wrap gap-1">
                {assumption.supporting_strategies.map((s) => (
                  <span
                    key={s}
                    className="rounded bg-slate-800 px-2 py-0.5 text-[10px] text-slate-300"
                  >
                    {s}
                  </span>
                ))}
              </div>
            </div>
          )}

          {assumption.supporting_indicators.length > 0 && (
            <div className="mt-2">
              <p className="text-[11px] uppercase tracking-wider text-slate-500">
                Indicators
              </p>
              <div className="mt-1 flex flex-wrap gap-1">
                {assumption.supporting_indicators.map((ind) => (
                  <span
                    key={ind}
                    className="rounded bg-slate-800 px-2 py-0.5 text-[10px] text-slate-400"
                  >
                    {ind}
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className="mt-3 flex gap-4 text-[10px] text-slate-600">
            {assumption.sample_size > 0 && (
              <span>Sample: {assumption.sample_size}</span>
            )}
            {assumption.evaluation_window && (
              <span>Window: {assumption.evaluation_window}</span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
