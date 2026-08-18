import type { OHLCVBar } from '../types/api';

/** Merge older bars in front of current bars. Dedupes by date, oldest first. */
export function mergeBarsOldestFirst(
  existing: OHLCVBar[],
  incoming: OHLCVBar[],
): OHLCVBar[] {
  const byDate = new Map<string, OHLCVBar>();
  for (const bar of existing) {
    byDate.set(barDateKey(bar.date), bar);
  }
  for (const bar of incoming) {
    const key = barDateKey(bar.date);
    if (!byDate.has(key)) {
      byDate.set(key, bar);
    }
  }
  return Array.from(byDate.values()).sort(
    (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime(),
  );
}

export function barDateKey(date: string): string {
  return new Date(date).toISOString().slice(0, 10);
}

export function oldestBarDate(bars: OHLCVBar[]): string | null {
  if (bars.length === 0) return null;
  return bars.reduce((oldest, bar) =>
    new Date(bar.date) < new Date(oldest) ? bar.date : oldest,
  bars[0].date);
}
