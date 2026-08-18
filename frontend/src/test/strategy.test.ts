import { describe, expect, it } from 'vitest';
import type { StrategySignalRow } from '../types/api';
import { formatSignalAction, riskReward, signalLabel } from '../utils/strategy';

function row(partial: Partial<StrategySignalRow>): StrategySignalRow {
  return {
    strategy: 'ema_trend',
    display_name: 'EMA',
    best_timeframe: '1D',
    signal: 'NEUTRAL',
    confidence: 50,
    confidence_label: 'Historical/Model Confidence',
    strength: 'Moderate',
    status: 'OK',
    sample_size: 20,
    evaluation_window: '',
    last_evaluated: null,
    reasons: [],
    warnings: [],
    error: null,
    current_price: 100,
    entry_price: 100,
    stop_loss: 95,
    target: 110,
    recommended_action: 'HOLD',
    ...partial,
  };
}

describe('strategy utils', () => {
  it('labels neutral as HOLD and errors as NO SIGNAL', () => {
    expect(signalLabel(row({ signal: 'NEUTRAL' }))).toBe('HOLD');
    expect(signalLabel(row({ status: 'ERROR', signal: 'NEUTRAL' }))).toBe('NO SIGNAL');
  });

  it('computes risk reward from backend levels', () => {
    expect(riskReward(100, 95, 110)).toBe(2);
    expect(riskReward(null, 95, 110)).toBeNull();
  });

  it('reports no actionable signal for neutral', () => {
    expect(formatSignalAction(row({ signal: 'NEUTRAL' }))).toBe('No actionable signal');
    expect(formatSignalAction(row({ signal: 'BUY', recommended_action: 'BUY' }))).toBe('BUY');
  });
});
