/**
 * MonteCarloPanel
 *
 * Sidebar panel shown inside StockAnalysisWorkspace.
 * Lets the user pick a simulation count and launches
 * the dedicated MonteCarloPage workspace for live streaming visualization.
 *
 * Allowed counts: 10 / 100 / 500 / 1,000
 * (Backend enforces the same list via ALLOWED_SIMULATION_COUNTS in schemas.py)
 */

import type { StrategySignalRow } from '../../types/api';
import { ALLOWED_SIMULATIONS } from '../../types/api';

interface MonteCarloPanelProps {
  symbol: string;
  strategy: string | null;
  strategyRow: StrategySignalRow | null;
  currentPrice?: number | null;
  onLaunch: (simulations: number) => void;
}

// Descriptions shown next to each count.  Keep in sync with ALLOWED_SIMULATIONS.
const SIM_DESCRIPTIONS: Record<number, string> = {
  10:    'Quick test',
  50:    'Light',
  100:   'Fast',
  500:   'Standard',
  1_000: 'Full',
};

export function MonteCarloPanel({
  strategy,
  onLaunch,
}: MonteCarloPanelProps) {
  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Monte Carlo</span>
        <span className="text-[10px] text-slate-500">Resampling — not a forecast</span>
      </div>
      <div className="space-y-3 p-3 text-sm">
        {!strategy && (
          <p className="text-slate-500 text-xs">
            Select a strategy to run Monte Carlo on its completed trades.
          </p>
        )}

        {strategy && (
          <>
            <p className="text-xs text-slate-400">
              Strategy: <span className="font-mono text-slate-200">{strategy}</span>
            </p>

            <div className="space-y-2">
              <p className="text-[10px] uppercase text-slate-500">Choose simulation count</p>
              {ALLOWED_SIMULATIONS.map((count) => (
                <button
                  key={count}
                  type="button"
                  className="w-full rounded border border-terminal-border bg-terminal-bg/60 px-3 py-2 text-left text-xs hover:border-terminal-accent hover:bg-terminal-accent/10 transition-colors"
                  onClick={() => onLaunch(count)}
                >
                  <span className="font-mono font-semibold text-slate-200">
                    Run {count.toLocaleString()}
                  </span>
                  <span className="ml-2 text-slate-500">
                    {SIM_DESCRIPTIONS[count] ?? ''}
                  </span>
                </button>
              ))}
            </div>

            <p className="text-[10px] text-slate-600">
              Opens a dedicated workspace with live path visualization and streaming progress.
            </p>
          </>
        )}

        <div className="border-t border-terminal-border/40 pt-2 text-[10px] text-slate-600">
          Monte Carlo resamples completed historical trades. Simulation count does not
          increase the historical sample size.
        </div>
      </div>
    </div>
  );
}
