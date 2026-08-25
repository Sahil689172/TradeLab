/**
 * MonteCarloPanel
 *
 * Sidebar panel shown inside StockAnalysisWorkspace.
 * Lets the user pick a simulation count (1k / 10k / 100k) and launches
 * the dedicated MonteCarloPage workspace for live streaming visualization.
 *
 * The panel itself no longer runs simulations inline — it's a launcher.
 */

import type { StrategySignalRow } from '../../types/api';

interface MonteCarloPanelProps {
  symbol: string;
  strategy: string | null;
  strategyRow: StrategySignalRow | null;
  currentPrice?: number | null;
  onLaunch: (simulations: number) => void;
}

const SIM_OPTIONS = [
  { count: 1_000, label: '1,000', description: 'Fast — ~1 s' },
  { count: 10_000, label: '10,000', description: 'Standard — ~3 s' },
  { count: 100_000, label: '100,000', description: 'Full — ~15 s' },
] as const;

export function MonteCarloPanel({
  symbol,
  strategy,
  strategyRow,
  currentPrice,
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
          <p className="text-slate-500 text-xs">Select a strategy to run Monte Carlo on its completed trades.</p>
        )}

        {strategy && (
          <>
            <p className="text-xs text-slate-400">
              Strategy: <span className="font-mono text-slate-200">{strategy}</span>
            </p>

            <div className="space-y-2">
              <p className="text-[10px] uppercase text-slate-500">Choose simulation count</p>
              {SIM_OPTIONS.map(({ count, label, description }) => (
                <button
                  key={count}
                  type="button"
                  className="w-full rounded border border-terminal-border bg-terminal-bg/60 px-3 py-2 text-left text-xs hover:border-terminal-accent hover:bg-terminal-accent/10 transition-colors"
                  onClick={() => onLaunch(count)}
                >
                  <span className="font-mono font-semibold text-slate-200">Run {label}</span>
                  <span className="ml-2 text-slate-500">{description}</span>
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
