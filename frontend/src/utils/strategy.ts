import type { StrategySignalRow } from '../types/api';

export const STRATEGY_COLORS = [
  '#3b82f6',
  '#22c55e',
  '#f59e0b',
  '#ef4444',
  '#a855f7',
  '#06b6d4',
  '#ec4899',
  '#84cc16',
  '#f97316',
  '#6366f1',
  '#14b8a6',
  '#eab308',
];

export function strategyColor(index: number): string {
  return STRATEGY_COLORS[index % STRATEGY_COLORS.length];
}

export function signalLabel(row: StrategySignalRow): string {
  if (row.status === 'ERROR') return 'NO SIGNAL';
  if (row.signal === 'NEUTRAL') return 'HOLD';
  return row.signal;
}

export function riskReward(
  entry: number | null | undefined,
  stop: number | null | undefined,
  target: number | null | undefined,
): number | null {
  if (entry == null || stop == null || target == null) return null;
  const risk = Math.abs(entry - stop);
  const reward = Math.abs(target - entry);
  if (risk <= 0) return null;
  return reward / risk;
}

export function formatSignalAction(row: StrategySignalRow | null): string {
  if (!row || row.status === 'ERROR') return 'No actionable signal';
  if (row.signal === 'NEUTRAL') return 'No actionable signal';
  return row.recommended_action;
}
