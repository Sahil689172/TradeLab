import type { StrategySignalRow } from '../../types/api';
import { signalLabel, strategyColor } from '../../utils/strategy';

interface StrategyFilterPanelProps {
  strategies: StrategySignalRow[];
  enabled: Set<string>;
  selected: string | null;
  onToggle: (strategy: string) => void;
  onSelect: (strategy: string) => void;
}

export function StrategyFilterPanel({
  strategies,
  enabled,
  selected,
  onToggle,
  onSelect,
}: StrategyFilterPanelProps) {
  if (strategies.length === 0) {
    return (
      <div className="panel p-4 text-sm text-slate-500">
        No strategy results. Bootstrap OHLCV and refresh data first.
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Strategy overlays</span>
        <span className="text-[10px] text-slate-500">{enabled.size} enabled</span>
      </div>
      <div className="max-h-64 space-y-1 overflow-y-auto p-3">
        {strategies.map((row, idx) => {
          const on = enabled.has(row.strategy);
          const isSelected = selected === row.strategy;
          const color = strategyColor(idx);
          return (
            <label
              key={row.strategy}
              className={`flex cursor-pointer items-start gap-2 rounded border px-2 py-1.5 text-xs ${
                isSelected ? 'border-terminal-accent bg-terminal-accent/10' : 'border-terminal-border/50'
              }`}
            >
              <input
                type="checkbox"
                checked={on}
                onChange={() => onToggle(row.strategy)}
                className="mt-0.5"
              />
              <button
                type="button"
                className="flex-1 text-left"
                onClick={() => onSelect(row.strategy)}
              >
                <span className="font-medium text-slate-200" style={{ color: on ? color : undefined }}>
                  {row.display_name}
                </span>
                <span className="ml-2 font-mono text-[10px] text-slate-500">
                  {row.status === 'ERROR' ? 'ERROR' : signalLabel(row)}
                  {row.confidence > 0 ? ` · ${row.confidence.toFixed(0)} score` : ''}
                </span>
                {row.reasons[0] && (
                  <span className="mt-0.5 block truncate text-[10px] text-slate-600">{row.reasons[0]}</span>
                )}
              </button>
            </label>
          );
        })}
      </div>
    </div>
  );
}
