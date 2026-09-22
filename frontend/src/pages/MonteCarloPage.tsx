/**
 * MonteCarloPage
 *
 * Dedicated full-page Monte Carlo workspace.
 *
 * Layout:
 *   ┌──────────────────────────────────────────────────────┐
 *   │ Header: symbol · price · sim count · [Cancel] [Back] │
 *   ├──────────────────────────────────────────────────────┤
 *   │ Progress bar + live status message                   │
 *   ├──────────────────────────────────────────────────────┤
 *   │ Strategy Trade Plan                                  │
 *   │   Strategy / Signal / Entry / Target / Stop / TF     │
 *   └──────────────────────────────────────────────────────┘
 */

import { useEffect, useRef } from 'react';
import type { StrategySignalRow } from '../types/api';
import { useMonteCarloStream } from '../hooks/useMonteCarloStream';
import { formatCurrency } from '../utils/format';

interface MonteCarloPageProps {
  symbol: string;
  currentPrice: number | null;
  strategy: string;
  strategyRow: StrategySignalRow | null;
  simulations: number;
  onBack: () => void;
}

// Allowed simulation counts — must mirror ALLOWED_SIMULATIONS in types/api.ts
const SIM_LABELS: Record<number, string> = {
  10:    '10',
  50:    '50',
  100:   '100',
  500:   '500',
  1_000: '1,000',
};

function statusColor(s: string): string {
  switch (s) {
    case 'simulating':
    case 'running':
      return 'text-terminal-warn';
    case 'complete':
      return 'text-terminal-buy';
    case 'cancelled':
      return 'text-slate-500';
    case 'error':
      return 'text-terminal-sell';
    case 'loading_trades':
    case 'loading':
      return 'text-sky-400';
    default:
      return 'text-slate-400';
  }
}

function statusLabel(s: string): string {
  switch (s) {
    case 'idle':           return 'Ready';
    case 'loading_trades':
    case 'loading':        return 'Loading trades…';
    case 'simulating':
    case 'running':        return 'Running simulations…';
    case 'complete':       return 'Completed';
    case 'cancelled':      return 'Cancelled';
    case 'error':          return 'Error';
    default:               return s;
  }
}

/** True while the backend is actively doing work. */
function isActive(s: string): boolean {
  return (
    s === 'loading_trades' ||
    s === 'loading' ||
    s === 'simulating' ||
    s === 'running'
  );
}

export function MonteCarloPage({
  symbol,
  currentPrice,
  strategy,
  strategyRow,
  simulations,
  onBack,
}: MonteCarloPageProps) {
  const { state, start, cancel, abortStream, reset } = useMonteCarloStream();
  const startedRef = useRef(false);
  const abortOnUnmountRef = useRef<(() => void) | null>(null);

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
      // Silently abort — do NOT call cancel() here or StrictMode will
      // show "Cancelled by user" on the remount.
      if (abortOnUnmountRef.current) {
        abortOnUnmountRef.current();
      }
      startedRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep the ref pointing at abortStream (stable) so cleanup always works.
  useEffect(() => {
    abortOnUnmountRef.current = abortStream;
  }, [abortStream]);

  const {
    status, completed, total, pct: pctDone, elapsed, etaSeconds,
    statusMessage, tradeCount, result, error,
  } = state;

  const active          = isActive(status);
  const isDone          = status === 'complete';
  const isFailed        = status === 'error' || status === 'cancelled';
  const isLoadingTrades = status === 'loading_trades' || status === 'loading';

  const referencePrice = result?.current_price ?? currentPrice;

  // Progress bar display.
  const progressWidth = isLoadingTrades ? 100 : pctDone;
  const progressPulse = isLoadingTrades;

  return (
    <div className="flex flex-col gap-4 p-4">

      {/* ── Header ──────────────────────────────────────────────────────── */}
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
                {referencePrice != null && (
                  <>
                    {' '}· Reference:{' '}
                    <span className="font-mono text-slate-200">
                      {formatCurrency(referencePrice)}
                    </span>
                  </>
                )}
                {' '}·{' '}
                <span className="font-mono text-slate-200">
                  {SIM_LABELS[simulations] ?? simulations.toLocaleString()}
                </span>
                {' '}simulated outcome paths
              </p>
            </div>
          </div>

          <div className="flex gap-2">
            {active && (
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
                    start(symbol, {
                      strategy,
                      simulations,
                      timeframe: '1D',
                      horizons: [1, 2, 5],
                    });
                  }, 50);
                }}
              >
                Re-run
              </button>
            )}
          </div>
        </div>
      </div>

      {/* ── Progress bar ────────────────────────────────────────────────── */}
      <div className="panel p-3">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex flex-col gap-0.5">
            <span className={`font-semibold ${statusColor(status)}`}>
              {statusLabel(status)}
            </span>
            {statusMessage && !isDone && (
              <span className="text-[10px] text-slate-500">{statusMessage}</span>
            )}
          </div>

          <span className="font-mono text-slate-400">
            {isLoadingTrades ? (
              <>
                {total.toLocaleString()} paths queued
                {elapsed > 0 && <> &nbsp;·&nbsp; {elapsed.toFixed(1)}s elapsed</>}
              </>
            ) : isDone && result ? (
              <>
                {(result.available ? result.simulation_count : completed).toLocaleString()}
                {' / '}
                {(result.available ? result.simulation_count : total).toLocaleString()}
                &nbsp;·&nbsp; 100.0%
                &nbsp;·&nbsp; {elapsed.toFixed(1)}s elapsed
              </>
            ) : (
              <>
                {completed.toLocaleString()} / {total.toLocaleString()}
                &nbsp;·&nbsp;
                {pctDone.toFixed(1)}%
                &nbsp;·&nbsp;
                {elapsed.toFixed(1)}s elapsed
                {status === 'simulating' && etaSeconds != null && etaSeconds > 0 && (
                  <> &nbsp;·&nbsp; ~{etaSeconds.toFixed(1)}s remaining</>
                )}
              </>
            )}
          </span>
        </div>

        <div className="h-2 overflow-hidden rounded bg-slate-800">
          <div
            className={`h-full rounded transition-all duration-300 ${progressPulse ? 'animate-pulse' : ''}`}
            style={{
              width: `${progressWidth}%`,
              background:
                status === 'error' || status === 'cancelled'
                  ? '#ef4444'
                  : status === 'complete'
                    ? '#22c55e'
                    : isLoadingTrades
                      ? '#38bdf8'
                      : '#f59e0b',
            }}
          />
        </div>

        {isLoadingTrades && (
          <p className="mt-1 text-[10px] text-slate-500">
            Building out-of-sample trade history via historical replay — one-time step per symbol.
          </p>
        )}
        {tradeCount != null && !isLoadingTrades && (
          <p className="mt-1 text-[10px] text-slate-500">
            {tradeCount} historical trades loaded as simulation input
          </p>
        )}
        {error && (
          <p className="mt-1 text-xs text-terminal-sell">{error}</p>
        )}
      </div>

      {/* ── Strategy Trade Plan ──────────────────────────────────────────── */}
      <div className="panel p-3">
        <p className="mb-2 text-[10px] uppercase text-slate-500">Strategy trade plan</p>
        {!strategyRow ? (
          <p className="text-xs text-slate-500">No strategy signal available.</p>
        ) : (
          <div className="space-y-1 text-xs">
            <TradePlanRow label="Strategy"  value={strategyRow.display_name} />
            <TradePlanRow
              label="Signal"
              value={strategyRow.signal === 'NEUTRAL' ? 'NO SIGNAL' : strategyRow.signal}
              highlight={
                strategyRow.signal === 'BUY'
                  ? 'text-terminal-buy'
                  : strategyRow.signal === 'SELL'
                    ? 'text-terminal-sell'
                    : 'text-slate-500'
              }
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
              label="Stop Loss"
              value={strategyRow.stop_loss != null ? formatCurrency(strategyRow.stop_loss) : 'N/A'}
              highlight="text-terminal-sell"
            />
            <TradePlanRow label="Timeframe" value={strategyRow.best_timeframe} />
          </div>
        )}
      </div>

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
