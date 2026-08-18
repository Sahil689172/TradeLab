import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { MonteCarloDashboardResponse } from '../../types/api';
import { formatCurrency, formatPct } from '../../utils/format';
import { MonteCarloFutureChart } from './MonteCarloFutureChart';

interface MonteCarloPanelProps {
  symbol: string;
  strategy: string | null;
  currentPrice?: number | null;
}

const SIM_OPTIONS = [1_000, 10_000, 100_000] as const;
const DEFAULT_HORIZONS = [1, 2, 5];

function pct(value: number | null | undefined, asFraction = true): string {
  if (value == null || Number.isNaN(value)) return 'N/A';
  return formatPct(value, asFraction);
}

export function MonteCarloPanel({ symbol, strategy, currentPrice }: MonteCarloPanelProps) {
  const [simulations, setSimulations] = useState<number>(1_000);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [result, setResult] = useState<MonteCarloDashboardResponse | null>(null);

  const mutation = useMutation({
    mutationFn: () => {
      if (!strategy) throw new Error('Select a strategy first');
      return api.runMonteCarlo(symbol, {
        strategy,
        simulations,
        timeframe: '1D',
        horizons: DEFAULT_HORIZONS,
      });
    },
    onSuccess: (data) => {
      setResult(data);
      setDialogOpen(false);
    },
  });

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Monte Carlo</span>
        <span className="text-[10px] text-slate-500">Resampling — not a forecast</span>
      </div>
      <div className="space-y-3 p-3 text-sm">
        {!strategy && (
          <p className="text-slate-500">Select a strategy to run Monte Carlo on its completed trades.</p>
        )}
        {strategy && (
          <>
            <p className="text-xs text-slate-400">
              Strategy: <span className="font-mono text-slate-200">{strategy}</span>
            </p>
            <button
              type="button"
              className="btn-primary w-full text-xs"
              onClick={() => setDialogOpen(true)}
            >
              Run Monte Carlo Simulation
            </button>
          </>
        )}

        {dialogOpen && strategy && (
          <div className="rounded border border-terminal-border bg-terminal-bg p-3">
            <p className="mb-2 text-xs font-semibold text-slate-300">Simulation</p>
            <fieldset>
              <legend className="mb-1 text-xs text-slate-500">Simulation count</legend>
              <div className="flex flex-wrap gap-3">
                {SIM_OPTIONS.map((n) => (
                  <label key={n} className="flex items-center gap-1 text-xs text-slate-300">
                    <input
                      type="radio"
                      name="simulations"
                      checked={simulations === n}
                      onChange={() => setSimulations(n)}
                    />
                    {n.toLocaleString()}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                className="btn-primary flex-1 text-xs"
                disabled={mutation.isPending}
                onClick={() => mutation.mutate()}
              >
                {mutation.isPending ? 'Running…' : 'Run'}
              </button>
              <button
                type="button"
                className="rounded border border-terminal-border px-3 text-xs text-slate-400"
                onClick={() => setDialogOpen(false)}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {mutation.isPending && (
          <p className="text-xs text-slate-500">Running Monte Carlo with {simulations.toLocaleString()} simulations…</p>
        )}

        {mutation.isError && (
          <p className="text-xs text-terminal-sell">{(mutation.error as Error).message}</p>
        )}

        {result && (
          <div className="space-y-2 border-t border-terminal-border pt-2 text-xs">
            <p className="text-slate-400">
              Source: <span className="text-slate-200">{result.trade_source}</span>
            </p>
            <p className="font-medium text-slate-300">
              Historical OOS trades:{' '}
              <span className="font-mono">{result.historical_oos_trade_count}</span>
              {' · '}
              Simulations:{' '}
              <span className="font-mono">{result.simulation_count.toLocaleString()}</span>
            </p>
            <p className="text-[10px] text-terminal-warn">
              Simulation count does not increase historical sample size.
            </p>
            {!result.available && (
              <p className="text-terminal-warn">{result.message}</p>
            )}
            {result.available && (
              <>
                <div className="grid grid-cols-2 gap-2">
                  <Stat label="Median return" value={pct(result.median_return_pct, true)} />
                  <Stat label="P(loss)" value={pct(result.probability_of_loss, true)} />
                  <Stat label="P(profit)" value={pct(result.probability_of_profit, true)} />
                  <Stat label="Verdict" value={result.verdict || 'N/A'} />
                  <Stat label="Sample quality" value={result.sample_quality || 'N/A'} />
                  <Stat label="Hist. trades" value={String(result.historical_trades)} />
                </div>
                {result.return_percentiles && (
                  <p className="text-slate-500">
                    Return band (P05–P95): {pct(result.return_percentiles.p05, true)} to{' '}
                    {pct(result.return_percentiles.p95, true)}
                  </p>
                )}
              </>
            )}

            {result.next_day_outlook && (
              <div className="rounded border border-terminal-border bg-terminal-bg/50 p-2">
                <p className="font-semibold text-slate-300">Trade-resampling outlook</p>
                <p className="mt-1 text-[10px] text-terminal-warn">{result.next_day_outlook.disclaimer}</p>
                {!result.next_day_outlook.supported ? (
                  <p className="mt-1 text-slate-500">{result.next_day_outlook.message}</p>
                ) : (
                  <div className="mt-2 space-y-1">
                    <p>
                      Expected return (median resampled):{' '}
                      {pct(result.next_day_outlook.expected_return_pct, true)}
                    </p>
                    <p>
                      Range P05–P95: {pct(result.next_day_outlook.return_range_low_pct, true)} –{' '}
                      {pct(result.next_day_outlook.return_range_high_pct, true)}
                    </p>
                  </div>
                )}
              </div>
            )}

            {result.horizon_outlook.length > 0 && (
              <div className="space-y-2 rounded border border-terminal-border bg-terminal-bg/50 p-2">
                <p className="font-semibold text-slate-300">Monte Carlo Future Outlook</p>
                <p className="text-[10px] text-terminal-warn">{result.horizon_disclaimer}</p>
                {result.horizon_outlook.map((h) => (
                  <div key={h.trading_days} className="border-t border-terminal-border/40 pt-2">
                    <p className="font-medium text-slate-200">{h.label}</p>
                    {!h.supported ? (
                      <p className="text-slate-500">{h.message || 'Not available with current model'}</p>
                    ) : (
                      <>
                        <p className="font-mono text-lg text-slate-100">{formatCurrency(h.median_price)}</p>
                        <p className="text-slate-400">
                          Range: {formatCurrency(h.lower_price)} — {formatCurrency(h.upper_price)}
                        </p>
                        <p>Expected return: {pct(h.expected_return_pct, true)}</p>
                        {h.probability_negative_return != null && (
                          <p className="text-slate-500">
                            P(negative return): {pct(h.probability_negative_return, true)}
                          </p>
                        )}
                      </>
                    )}
                  </div>
                ))}
                <MonteCarloFutureChart
                  currentPrice={result.current_price ?? currentPrice ?? null}
                  horizons={result.horizon_outlook}
                />
              </div>
            )}

            {result.warnings.slice(0, 3).map((w) => (
              <p key={w} className="text-[10px] text-slate-600">
                {w}
              </p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-terminal-bg/60 p-2">
      <p className="text-[10px] uppercase text-slate-500">{label}</p>
      <p className="font-mono text-slate-200">{value}</p>
    </div>
  );
}
