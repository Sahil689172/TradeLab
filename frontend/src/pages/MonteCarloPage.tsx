/**
 * MonteCarloPage
 *
 * Dedicated full-page Monte Carlo workspace for a stock + strategy.
 *
 * Layout:
 *   ┌──────────────────────────────────────────────────────┐
 *   │ Header: symbol · price · sim count · [Cancel] [Back] │
 *   ├──────────────────────────────────────────────────────┤
 *   │ Progress bar + status card                           │
 *   ├───────────────────────────┬──────────────────────────┤
 *   │ Live path chart (canvas)  │ Stats sidebar            │
 *   │                           │   · partial stats        │
 *   │                           │   · trade plan (from     │
 *   │                           │     strategy engine)     │
 *   ├───────────────────────────┴──────────────────────────┤
 *   │ Results panel (after complete)                       │
 *   │   horizon outlook table · disclaimer                 │
 *   └──────────────────────────────────────────────────────┘
 */

import { useEffect, useRef, useState } from 'react';
import type { StrategySignalRow } from '../types/api';
import { useMonteCarloStream } from '../hooks/useMonteCarloStream';
import type { MCChartView } from '../components/chart/MonteCarloPathChart';
import { MonteCarloPathChart } from '../components/chart/MonteCarloPathChart';
import { formatCurrency, formatPct } from '../utils/format';

interface MonteCarloPageProps {
  symbol: string;
  currentPrice: number | null;
  strategy: string;
  strategyRow: StrategySignalRow | null;
  simulations: number;
  onBack: () => void;
}

const SIM_LABELS: Record<number, string> = {
  1_000: '1,000',
  10_000: '10,000',
  100_000: '100,000',
};

function pct(v: number | null | undefined, asFrac = true): string {
  if (v == null || !isFinite(v)) return 'N/A';
  return formatPct(v, asFrac);
}

function statusColor(s: string): string {
  switch (s) {
    case 'running': return 'text-terminal-warn';
    case 'complete': return 'text-terminal-buy';
    case 'cancelled': return 'text-slate-500';
    case 'error': return 'text-terminal-sell';
    default: return 'text-slate-400';
  }
}

function statusLabel(s: string): string {
  switch (s) {
    case 'idle': return 'Ready';
    case 'loading': return 'Loading trades…';
    case 'running': return 'Simulating…';
    case 'complete': return 'Complete';
    case 'cancelled': return 'Cancelled';
    case 'error': return 'Error';
    default: return s;
  }
}

export function MonteCarloPage({
  symbol,
  currentPrice,
  strategy,
  strategyRow,
  simulations,
  onBack,
}: MonteCarloPageProps) {
  const { state, start, cancel, reset } = useMonteCarloStream();
  const startedRef = useRef(false);

  // Auto-start simulation on mount.
  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    start(symbol, {
      strategy,
      simulations,
      timeframe: '1D',
      horizons: [1, 2, 5],
    });
    return () => {
      // Cancel on unmount if still running.
      cancel();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const {
    status, completed, total, pct: pctDone, elapsed, etaSeconds,
    partialStats, bands, samplePaths, result, error,
  } = state;
  const [chartView, setChartView] = useState<MCChartView>('fan');
  const [showSamplePaths, setShowSamplePaths] = useState(false);
  const isActive = status === 'loading' || status === 'running';
  const isDone = status === 'complete';
  const isFailed = status === 'error' || status === 'cancelled';

  const initialCapital = 1_000_000;

  return (
    <div className="flex flex-col gap-4 p-4">

      {/* ── Header ────────────────────────────────────────────────────── */}
      <div className="panel p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-4">
            <button
              type="button"
              className="text-xs text-slate-500 hover:text-slate-300"
              onClick={onBack}
            >
              ← Back
            </button>
            <div>
              <h2 className="font-mono text-xl font-bold text-slate-100">
                {symbol}
                <span className="ml-2 text-sm font-normal text-slate-400">Monte Carlo</span>
              </h2>
              <p className="text-xs text-slate-500">
                Strategy: <span className="text-slate-300">{strategy}</span>
                {currentPrice != null && (
                  <> · Price: <span className="font-mono text-slate-200">{formatCurrency(currentPrice)}</span></>
                )}
                · Simulations: <span className="font-mono text-slate-200">{SIM_LABELS[simulations] ?? simulations.toLocaleString()}</span>
              </p>
            </div>
          </div>
          <div className="flex gap-2">
            {isActive && (
              <button
                type="button"
                className="rounded border border-terminal-sell px-3 py-1 text-xs text-terminal-sell hover:bg-terminal-sell/10"
                onClick={cancel}
              >
                Cancel
              </button>
            )}
            {(isDone || isFailed) && (
              <button
                type="button"
                className="btn-primary text-xs"
                onClick={() => {
                  reset();
                  startedRef.current = false;
                  setTimeout(() => {
                    startedRef.current = true;
                    start(symbol, { strategy, simulations, timeframe: '1D', horizons: [1, 2, 5] });
                  }, 50);
                }}
              >
                Re-run
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Progress bar ──────────────────────────────────────────────── */}
      <div className="panel p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
          <span className={`font-semibold ${statusColor(status)}`}>
            {statusLabel(status)}
          </span>
          <span className="font-mono text-slate-400">
            {completed.toLocaleString()} / {total.toLocaleString()} &nbsp;·&nbsp;
            {pctDone.toFixed(1)}% &nbsp;·&nbsp;
            {elapsed.toFixed(1)}s elapsed
            {status === 'running' && etaSeconds != null && etaSeconds > 0 && (
              <> &nbsp;·&nbsp; ~{etaSeconds.toFixed(1)}s remaining</>
            )}
          </span>
        </div>
        <div className="h-2 overflow-hidden rounded bg-slate-800">
          <div
            className="h-full rounded transition-all duration-300"
            style={{
              width: `${pctDone}%`,
              background: status === 'error' || status === 'cancelled'
                ? '#ef4444'
                : status === 'complete'
                  ? '#22c55e'
                  : '#f59e0b',
            }}
          />
        </div>
        {error && (
          <p className="mt-1 text-xs text-terminal-sell">{error}</p>
        )}
      </div>

      {/* ── Main content: chart + stats ────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-12">

        {/* Live path chart */}
        <div className="panel p-3 xl:col-span-8">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <p className="text-xs font-semibold text-slate-300">
              Monte Carlo simulation output
              {bands?.paths_used ? (
                <span className="ml-2 font-normal text-slate-500">
                  (percentiles across {bands.paths_used.toLocaleString()} paths)
                </span>
              ) : null}
            </p>
            <p className="text-[10px] uppercase text-terminal-warn">
              Simulated — not future prices
            </p>
          </div>

          {/* View toggles — the fan is the default because rendering every
              simulated path individually is what made this unusable. */}
          <div className="mb-2 flex flex-wrap items-center gap-1">
            {([
              ['fan', 'Percentile bands'],
              ['distribution', 'Distribution'],
              ['drawdown', 'Drawdown'],
            ] as const).map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setChartView(value)}
                className={`rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${
                  chartView === value
                    ? 'bg-amber-500/20 text-amber-300'
                    : 'text-slate-500 hover:text-slate-300'
                }`}
              >
                {label}
              </button>
            ))}
            {chartView === 'fan' && (
              <label className="ml-2 flex cursor-pointer items-center gap-1 text-[10px] text-slate-500">
                <input
                  type="checkbox"
                  checked={showSamplePaths}
                  onChange={(e) => setShowSamplePaths(e.target.checked)}
                  className="h-3 w-3 accent-amber-500"
                />
                Show sample paths ({samplePaths.length})
              </label>
            )}
          </div>

          <MonteCarloPathChart
            bands={bands}
            samplePaths={samplePaths}
            initialCapital={initialCapital}
            currentPrice={currentPrice}
            height={280}
            view={chartView}
            showSamplePaths={showSamplePaths}
          />
          <div className="mt-2 flex flex-wrap gap-4 text-[10px] text-slate-500">
            <span className="flex items-center gap-1">
              <span className="inline-block h-0.5 w-4 bg-amber-400" /> Median path
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-2 w-4 bg-amber-400/20" /> P10–P90 / P25–P75 bands
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-0.5 w-4 border-t border-dashed border-sky-400" /> Reference price
            </span>
          </div>
        </div>

        {/* Stats sidebar */}
        <div className="space-y-3 xl:col-span-4">

          {/* Live stats card */}
          <div className="panel p-3">
            <p className="mb-2 text-[10px] uppercase text-slate-500">
              {isDone ? 'Final statistics' : 'Partial statistics (updating)'}
            </p>
            {partialStats ? (
              <div className="grid grid-cols-2 gap-2 text-xs">
                <StatBox label="P(loss)" value={pct(partialStats.probability_of_loss, true)} />
                <StatBox label="P(profit)" value={pct(partialStats.probability_of_profit, true)} />
                <StatBox label="Median return" value={pct(partialStats.median_return_pct, true)} />
                <StatBox label="P05 return" value={pct(partialStats.return_p05, true)} />
                <StatBox label="P95 return" value={pct(partialStats.return_p95, true)} />
                <StatBox label="Med. drawdown" value={pct(partialStats.median_drawdown, true)} />
              </div>
            ) : (
              <p className="text-xs text-slate-500">
                {status === 'loading' ? 'Loading trades…' : 'Waiting for first batch…'}
              </p>
            )}
          </div>

          {/* Trade plan from strategy engine */}
          <div className="panel p-3">
            <p className="mb-2 text-[10px] uppercase text-slate-500">Trade plan</p>
            {!strategyRow ? (
              <p className="text-xs text-slate-500">No strategy signal available.</p>
            ) : (
              <div className="space-y-1 text-xs">
                <TradePlanRow label="Strategy" value={strategyRow.display_name} />
                <TradePlanRow
                  label="Signal"
                  value={strategyRow.signal === 'NEUTRAL' ? 'NO SIGNAL' : strategyRow.signal}
                  highlight={strategyRow.signal === 'BUY'
                    ? 'text-terminal-buy'
                    : strategyRow.signal === 'SELL'
                      ? 'text-terminal-sell'
                      : 'text-slate-500'}
                />
                <TradePlanRow
                  label="Entry"
                  value={formatCurrency(strategyRow.entry_price ?? strategyRow.current_price)}
                />
                <TradePlanRow
                  label="Target"
                  value={strategyRow.target != null ? formatCurrency(strategyRow.target) : 'N/A'}
                  highlight="text-terminal-buy"
                />
                <TradePlanRow
                  label="Stop loss"
                  value={strategyRow.stop_loss != null ? formatCurrency(strategyRow.stop_loss) : 'N/A'}
                  highlight="text-terminal-sell"
                />
                <TradePlanRow label="Timeframe" value={strategyRow.best_timeframe} />
              </div>
            )}
          </div>

          {/* Source info */}
          {result && (
            <div className="panel p-3 text-xs text-slate-500">
              <p>Source: <span className="text-slate-300">{result.trade_source}</span></p>
              <p className="mt-1">
                Historical OOS trades: <span className="font-mono text-slate-200">{result.historical_oos_trade_count}</span>
                <span className="ml-2 text-[10px] text-terminal-warn">≠ simulation count</span>
              </p>
              <p className="mt-1">
                Simulations: <span className="font-mono text-slate-200">{result.simulation_count.toLocaleString()}</span>
              </p>
              <p className="mt-1 text-[10px] italic">
                Simulation count does not increase historical sample size.
              </p>
            </div>
          )}
        </div>
      </div>

      {/* ── Results (after complete) ────────────────────────────────────── */}
      {isDone && result && result.available && (
        <div className="space-y-3">

          {/* Verdict + probabilities */}
          <div className="panel p-4">
            <p className="mb-3 text-[10px] uppercase text-slate-500">Monte Carlo results</p>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatBox label="Verdict" value={result.verdict || 'N/A'} />
              <StatBox label="Sample quality" value={result.sample_quality || 'N/A'} />
              <StatBox label="P(loss)" value={pct(result.probability_of_loss, true)} />
              <StatBox label="P(profit)" value={pct(result.probability_of_profit, true)} />
              <StatBox label="Median return" value={pct(result.median_return_pct, true)} />
              <StatBox
                label="Return P05–P95"
                value={
                  result.return_percentiles
                    ? `${pct(result.return_percentiles.p05, true)} → ${pct(result.return_percentiles.p95, true)}`
                    : 'N/A'
                }
              />
              <StatBox label="Hist. trades" value={String(result.historical_trades)} />
              <StatBox label="Win rate" value={pct(result.historical_win_rate, true)} />
            </div>
          </div>

          {/* Horizon outlook */}
          {result.horizon_outlook.length > 0 && (
            <div className="panel p-4">
              <div className="mb-2 flex items-center justify-between">
                <p className="text-xs font-semibold text-slate-300">
                  Simulated price outlook
                </p>
                <p className="text-[10px] uppercase text-terminal-warn">
                  Simulated estimate — not a guaranteed price
                </p>
              </div>
              <div className="grid gap-3 sm:grid-cols-3">
                {result.horizon_outlook.map((h) => (
                  <div
                    key={h.trading_days}
                    className="rounded border border-terminal-border bg-terminal-bg/50 p-3"
                  >
                    <p className="text-[10px] uppercase text-slate-500">{h.label}</p>
                    {!h.supported ? (
                      <p className="mt-1 text-xs text-slate-500">{h.message || 'Not available'}</p>
                    ) : (
                      <>
                        <p className="mt-1 font-mono text-lg font-bold text-slate-100">
                          {formatCurrency(h.median_price)}
                        </p>
                        <p className="text-xs text-slate-400">
                          {formatCurrency(h.lower_price)} – {formatCurrency(h.upper_price)}
                        </p>
                        <p className="mt-1 text-xs">
                          Return: {pct(h.expected_return_pct, true)}
                        </p>
                        {h.probability_negative_return != null && (
                          <p className="text-xs text-slate-500">
                            P(loss): {pct(h.probability_negative_return, true)}
                          </p>
                        )}
                      </>
                    )}
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[10px] italic text-slate-600">
                {result.horizon_disclaimer}
              </p>
            </div>
          )}

          {/* Warnings */}
          {result.warnings.length > 0 && (
            <div className="panel p-3">
              <p className="mb-1 text-[10px] uppercase text-slate-500">Warnings</p>
              <ul className="space-y-0.5">
                {result.warnings.slice(0, 6).map((w, i) => (
                  <li key={i} className="text-[10px] text-slate-600">{w}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* Not available */}
      {isDone && result && !result.available && (
        <div className="panel p-4">
          <p className="text-sm text-terminal-warn">{result.message}</p>
        </div>
      )}
    </div>
  );
}

function StatBox({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-terminal-bg/60 p-2">
      <p className="text-[10px] uppercase text-slate-500">{label}</p>
      <p className="font-mono text-sm text-slate-200">{value}</p>
    </div>
  );
}

function TradePlanRow({
  label,
  value,
  highlight,
}: {
  label: string;
  value: string;
  highlight?: string;
}) {
  return (
    <div className="flex justify-between gap-2 border-b border-terminal-border/30 py-1">
      <span className="text-slate-500">{label}</span>
      <span className={`font-mono ${highlight ?? 'text-slate-200'}`}>{value}</span>
    </div>
  );
}
