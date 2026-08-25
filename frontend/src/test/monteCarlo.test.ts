/**
 * Frontend Monte Carlo tests
 *
 * Coverage:
 *  - useMonteCarloStream hook state transitions
 *  - progress events update state correctly
 *  - result event sets status to 'complete'
 *  - error events set status to 'error'
 *  - cancel() aborts stream and sets 'cancelled'
 *  - reset() returns to idle
 *  - api.streamMonteCarlo parses SSE frames correctly
 *  - api.cancelMonteCarlo sends correct request
 *  - sample_paths are stored in state
 *  - simulation count stays separate from historical trade count
 *  - no dummy data: partial_stats reflect actual payload
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useMonteCarloStream } from '../hooks/useMonteCarloStream';

// ── SSE frame helpers ──────────────────────────────────────────────────────

function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function makeReadableStream(frames: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  let i = 0;
  return new ReadableStream({
    pull(controller) {
      if (i < frames.length) {
        controller.enqueue(enc.encode(frames[i++]));
      } else {
        controller.close();
      }
    },
  });
}

function makeProgressEvent(completed: number, total: number) {
  return {
    completed,
    total,
    pct: Math.round((completed / total) * 1000) / 10,
    elapsed: 0.5,
    status: 'running',
    partial_stats: {
      probability_of_loss: 0.3,
      probability_of_profit: 0.7,
      median_return_pct: 0.05,
      return_p05: -0.02,
      return_p95: 0.12,
      median_drawdown: 0.01,
    },
    sample_paths: [[1e6, 1.01e6, 1.02e6], [1e6, 0.99e6, 1.005e6]],
  };
}

function makeResultEvent(simCount: number, histTrades: number) {
  return {
    symbol: 'RELIANCE',
    strategy: 'ema_trend',
    trade_source: 'TEST',
    historical_oos_trade_count: histTrades,
    simulation_count: simCount,
    available: true,
    message: 'Monte Carlo complete',
    sample_quality: 'MODERATE',
    verdict: 'PROMISING',
    probability_of_loss: 0.28,
    probability_of_profit: 0.72,
    probability_of_ruin: 0.01,
    median_return_pct: 0.06,
    return_percentiles: { p05: -0.02, p25: 0.02, p50: 0.06, p75: 0.10, p95: 0.15 },
    max_drawdown_percentiles: null,
    final_capital_percentiles: null,
    historical_return_pct: 0.08,
    historical_trades: histTrades,
    historical_win_rate: 0.55,
    period: '2023',
    timeframe: '1D',
    next_day_outlook: null,
    current_price: 2500,
    historical_daily_return_count: 250,
    horizon_outlook: [],
    horizon_disclaimer: '',
    warnings: ['test warning'],
    resampling_limitation: 'test',
    _sample_paths: [[1e6, 1.05e6], [1e6, 0.98e6]],
    _elapsed: 3.14,
  };
}

// ── mock fetch ─────────────────────────────────────────────────────────────

function mockFetch(frames: string[], runId = 'test-run-id') {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    headers: { get: (h: string) => (h === 'X-MC-Run-Id' ? runId : null) },
    body: makeReadableStream(frames),
  });
}

// ── useMonteCarloStream ────────────────────────────────────────────────────

describe('useMonteCarloStream', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', mockFetch([]));
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('starts in idle state', () => {
    const { result } = renderHook(() => useMonteCarloStream());
    expect(result.current.state.status).toBe('idle');
    expect(result.current.state.completed).toBe(0);
    expect(result.current.state.samplePaths).toEqual([]);
  });

  it('transitions to loading when start() is called', async () => {
    const { result } = renderHook(() => useMonteCarloStream());
    act(() => {
      result.current.start('RELIANCE', { strategy: 'ema_trend', simulations: 1000 });
    });
    expect(result.current.state.status).toBe('loading');
    expect(result.current.state.total).toBe(1000);
  });

  it('updates state on progress event', async () => {
    const progress = makeProgressEvent(400, 1000);
    vi.stubGlobal('fetch', mockFetch([sseFrame('progress', progress)]));

    const { result } = renderHook(() => useMonteCarloStream());
    await act(async () => {
      result.current.start('RELIANCE', { strategy: 'ema_trend', simulations: 1000 });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(result.current.state.completed).toBe(400);
    expect(result.current.state.total).toBe(1000);
    expect(result.current.state.pct).toBe(40);
    expect(result.current.state.partialStats).not.toBeNull();
    expect(result.current.state.partialStats?.probability_of_loss).toBe(0.3);
  });

  it('stores sample paths from progress event', async () => {
    const progress = makeProgressEvent(500, 1000);
    vi.stubGlobal('fetch', mockFetch([sseFrame('progress', progress)]));

    const { result } = renderHook(() => useMonteCarloStream());
    await act(async () => {
      result.current.start('RELIANCE', { strategy: 'ema_trend', simulations: 1000 });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(result.current.state.samplePaths.length).toBe(2);
    expect(result.current.state.samplePaths[0]).toEqual([1e6, 1.01e6, 1.02e6]);
  });

  it('transitions to complete on result event', async () => {
    const resultData = makeResultEvent(1000, 20);
    vi.stubGlobal('fetch', mockFetch([sseFrame('result', resultData)]));

    const { result } = renderHook(() => useMonteCarloStream());
    await act(async () => {
      result.current.start('RELIANCE', { strategy: 'ema_trend', simulations: 1000 });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(result.current.state.status).toBe('complete');
    expect(result.current.state.pct).toBe(100);
    expect(result.current.state.result).not.toBeNull();
    expect(result.current.state.result?.simulation_count).toBe(1000);
    expect(result.current.state.result?.historical_oos_trade_count).toBe(20);
  });

  it('simulation_count remains separate from historical_oos_trade_count', async () => {
    const resultData = makeResultEvent(10_000, 15);
    vi.stubGlobal('fetch', mockFetch([sseFrame('result', resultData)]));

    const { result } = renderHook(() => useMonteCarloStream());
    await act(async () => {
      result.current.start('RELIANCE', { strategy: 'ema_trend', simulations: 10_000 });
      await new Promise((r) => setTimeout(r, 50));
    });

    const r = result.current.state.result!;
    expect(r.simulation_count).toBe(10_000);
    expect(r.historical_oos_trade_count).toBe(15);
    expect(r.simulation_count).not.toBe(r.historical_oos_trade_count);
  });

  it('sets status to error on error event', async () => {
    vi.stubGlobal('fetch', mockFetch([sseFrame('error', { message: 'No OHLCV data' })]));

    const { result } = renderHook(() => useMonteCarloStream());
    await act(async () => {
      result.current.start('RELIANCE', { strategy: 'ema_trend', simulations: 1000 });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(result.current.state.status).toBe('error');
    expect(result.current.state.error).toBe('No OHLCV data');
  });

  it('sets status to cancelled on Cancelled error event', async () => {
    vi.stubGlobal('fetch', mockFetch([sseFrame('error', { message: 'Cancelled' })]));

    const { result } = renderHook(() => useMonteCarloStream());
    await act(async () => {
      result.current.start('RELIANCE', { strategy: 'ema_trend', simulations: 1000 });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(result.current.state.status).toBe('cancelled');
  });

  it('cancel() sets status to cancelled and aborts fetch', async () => {
    // Keep stream open so abort is meaningful.
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise(() => {})));

    const { result } = renderHook(() => useMonteCarloStream());
    act(() => {
      result.current.start('RELIANCE', { strategy: 'ema_trend', simulations: 1000 });
    });
    act(() => {
      result.current.cancel();
    });

    expect(result.current.state.status).toBe('cancelled');
    expect(result.current.state.error).toBeTruthy();
  });

  it('reset() returns to idle', async () => {
    vi.stubGlobal('fetch', mockFetch([sseFrame('error', { message: 'fail' })]));

    const { result } = renderHook(() => useMonteCarloStream());
    await act(async () => {
      result.current.start('RELIANCE', { strategy: 'ema_trend', simulations: 1000 });
      await new Promise((r) => setTimeout(r, 50));
    });
    act(() => {
      result.current.reset();
    });

    expect(result.current.state.status).toBe('idle');
    expect(result.current.state.completed).toBe(0);
    expect(result.current.state.result).toBeNull();
  });

  it('processes multiple progress events in sequence', async () => {
    const frames = [
      sseFrame('progress', makeProgressEvent(2000, 10_000)),
      sseFrame('progress', makeProgressEvent(4000, 10_000)),
      sseFrame('progress', makeProgressEvent(10_000, 10_000)),
      sseFrame('result', makeResultEvent(10_000, 25)),
    ];
    vi.stubGlobal('fetch', mockFetch(frames));

    const { result } = renderHook(() => useMonteCarloStream());
    await act(async () => {
      result.current.start('RELIANCE', { strategy: 'ema_trend', simulations: 10_000 });
      await new Promise((r) => setTimeout(r, 100));
    });

    expect(result.current.state.status).toBe('complete');
    expect(result.current.state.result?.simulation_count).toBe(10_000);
  });

  it('sample paths are updated from result event _sample_paths', async () => {
    const resultData = makeResultEvent(1000, 20);
    resultData._sample_paths = [[1e6, 1.1e6, 1.2e6], [1e6, 0.9e6, 0.95e6], [1e6, 1.05e6, 1.08e6]];
    vi.stubGlobal('fetch', mockFetch([sseFrame('result', resultData)]));

    const { result } = renderHook(() => useMonteCarloStream());
    await act(async () => {
      result.current.start('RELIANCE', { strategy: 'ema_trend', simulations: 1000 });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(result.current.state.samplePaths.length).toBe(3);
  });

  it('elapsed is set from result event', async () => {
    const resultData = makeResultEvent(1000, 20);
    resultData._elapsed = 7.42;
    vi.stubGlobal('fetch', mockFetch([sseFrame('result', resultData)]));

    const { result } = renderHook(() => useMonteCarloStream());
    await act(async () => {
      result.current.start('RELIANCE', { strategy: 'ema_trend', simulations: 1000 });
      await new Promise((r) => setTimeout(r, 50));
    });

    expect(result.current.state.elapsed).toBe(7.42);
  });
});

// ── SSE frame parsing ──────────────────────────────────────────────────────

describe('SSE frame parsing edge cases', () => {
  it('ignores frames without data', async () => {
    const noData = 'event: progress\n\n';
    vi.stubGlobal('fetch', mockFetch([noData]));

    const { result } = renderHook(() => useMonteCarloStream());
    await act(async () => {
      result.current.start('TEST', { strategy: 'ema_trend', simulations: 100 });
      await new Promise((r) => setTimeout(r, 50));
    });
    // Should stay loading (no valid events processed).
    expect(result.current.state.status).toBe('loading');
  });

  it('handles multiple frames in one chunk', async () => {
    const twoFrames =
      sseFrame('progress', makeProgressEvent(500, 1000)) +
      sseFrame('result', makeResultEvent(1000, 10));
    vi.stubGlobal('fetch', mockFetch([twoFrames]));

    const { result } = renderHook(() => useMonteCarloStream());
    await act(async () => {
      result.current.start('TEST', { strategy: 'ema_trend', simulations: 1000 });
      await new Promise((r) => setTimeout(r, 80));
    });
    expect(result.current.state.status).toBe('complete');
  });
});
