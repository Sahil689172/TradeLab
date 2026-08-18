import type { StrategySignalRow } from '../../types/api';
import { formatCurrency, formatTs } from '../../utils/format';
import { riskReward, signalLabel } from '../../utils/strategy';

interface AnalysisPanelProps {
  currentPrice: number | null;
  strategy: StrategySignalRow | null;
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-terminal-border/40 py-1.5 text-xs">
      <span className="text-slate-500">{label}</span>
      <span className="text-right font-mono text-slate-200">{value}</span>
    </div>
  );
}

export function AnalysisPanel({ currentPrice, strategy }: AnalysisPanelProps) {
  const entry = strategy?.entry_price ?? strategy?.current_price ?? currentPrice;
  const rr = strategy ? riskReward(entry, strategy.stop_loss, strategy.target) : null;
  const actionable = strategy && strategy.signal !== 'NEUTRAL' && strategy.status === 'OK';

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Signal analysis</span>
        {strategy && <span className="text-[10px] text-slate-500">{strategy.display_name}</span>}
      </div>
      <div className="space-y-0 p-3">
        {!strategy && (
          <p className="text-sm text-slate-500">Select a strategy to view its analysis.</p>
        )}
        {strategy && strategy.status === 'ERROR' && (
          <p className="text-sm text-terminal-sell">{strategy.error ?? 'Strategy evaluation failed'}</p>
        )}
        {strategy && strategy.status !== 'ERROR' && (
          <>
            <Row label="Current price" value={formatCurrency(currentPrice)} />
            <Row
              label="Signal"
              value={actionable ? signalLabel(strategy) : 'No actionable signal'}
            />
            <Row label="Buy/Entry" value={formatCurrency(entry)} />
            <Row label="Target/Sell" value={formatCurrency(strategy.target)} />
            <Row label="Stop loss" value={formatCurrency(strategy.stop_loss)} />
            <Row label="Risk/Reward" value={rr != null ? rr.toFixed(2) : 'N/A'} />
            <Row label="Strategy" value={strategy.display_name} />
            <Row label="Timeframe" value={strategy.best_timeframe} />
            <Row label="Signal time" value={formatTs(strategy.last_evaluated)} />
            <Row
              label="Score"
              value={
                strategy.confidence > 0
                  ? `${strategy.confidence.toFixed(0)} (${strategy.confidence_label})`
                  : 'N/A'
              }
            />
            {strategy.reasons.length > 0 && (
              <div className="mt-2 border-t border-terminal-border/40 pt-2">
                <p className="text-[10px] uppercase text-slate-500">Configuration / reasons</p>
                <ul className="mt-1 space-y-0.5 text-[10px] text-slate-400">
                  {strategy.reasons.slice(0, 4).map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </div>
            )}
            {!actionable && (
              <p className="mt-2 text-xs text-slate-500">No actionable signal for this strategy.</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
