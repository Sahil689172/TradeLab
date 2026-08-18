import { describe, expect, it } from 'vitest';
import type { OHLCVBar } from '../types/api';
import { barDateKey, mergeBarsOldestFirst, oldestBarDate } from '../utils/ohlcv';

function bar(date: string, close = 100): OHLCVBar {
  return {
    date,
    open: close,
    high: close,
    low: close,
    close,
    volume: 1,
    adj_close: close,
  };
}

describe('mergeBarsOldestFirst', () => {
  it('appends older candles without duplicating dates', () => {
    const current = [bar('2024-02-01'), bar('2024-02-02')];
    const older = [bar('2024-01-31'), bar('2024-02-01', 99), bar('2024-01-30')];
    const merged = mergeBarsOldestFirst(current, older);
    const keys = merged.map((row) => barDateKey(row.date));
    expect(keys).toEqual(['2024-01-30', '2024-01-31', '2024-02-01', '2024-02-02']);
    expect(merged.find((row) => barDateKey(row.date) === '2024-02-01')?.close).toBe(100);
  });

  it('keeps chronological order when fetching older history twice', () => {
    let bars = [bar('2024-03-10'), bar('2024-03-11')];
    bars = mergeBarsOldestFirst(bars, [bar('2024-03-09')]);
    bars = mergeBarsOldestFirst(bars, [bar('2024-03-08'), bar('2024-03-09')]);
    expect(bars.map((row) => barDateKey(row.date))).toEqual([
      '2024-03-08',
      '2024-03-09',
      '2024-03-10',
      '2024-03-11',
    ]);
  });

  it('returns the oldest bar date', () => {
    expect(oldestBarDate([bar('2024-02-02'), bar('2024-02-01')])).toBe('2024-02-01');
    expect(oldestBarDate([])).toBeNull();
  });
});
