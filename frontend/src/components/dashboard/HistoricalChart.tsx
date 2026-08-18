import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  createChart,
  ColorType,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
} from 'lightweight-charts';
import { api } from '../../api/client';
import type { OHLCVBar } from '../../types/api';
import { mergeBarsOldestFirst, oldestBarDate } from '../../utils/ohlcv';

interface HistoricalChartProps {
  symbol: string;
}

function toDay(dateStr: string): CandlestickData['time'] {
  return new Date(dateStr).toISOString().slice(0, 10) as CandlestickData['time'];
}

export function HistoricalChart({ symbol }: HistoricalChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const [bars, setBars] = useState<OHLCVBar[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [olderError, setOlderError] = useState<string | null>(null);
  const [fetchingOlder, setFetchingOlder] = useState(false);

  const initial = useQuery({
    queryKey: ['ohlcv', symbol, '1D', 20],
    queryFn: () => api.getOHLCV(symbol, '1D', 20),
    retry: false,
  });

  useEffect(() => {
    setBars([]);
    setHasMore(false);
    setOlderError(null);
  }, [symbol]);

  useEffect(() => {
    if (!initial.data) return;
    setBars(initial.data.bars);
    setHasMore(initial.data.has_more);
    setOlderError(null);
  }, [initial.data, symbol]);

  useEffect(() => {
    if (!containerRef.current) return;
    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#111827' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      rightPriceScale: { borderColor: '#1e293b' },
      timeScale: { borderColor: '#1e293b', timeVisible: false },
      width: containerRef.current.clientWidth,
      height: 380,
    });
    const candles = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });
    const volume = chart.addHistogramSeries({
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    });
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });
    chartRef.current = chart;
    candleRef.current = candles;
    volumeRef.current = volume;
    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) chart.applyOptions({ width: entry.contentRect.width });
    });
    observer.observe(containerRef.current);
    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
    };
  }, [symbol]);

  useEffect(() => {
    if (!candleRef.current || !volumeRef.current || !chartRef.current) return;
    if (bars.length === 0) {
      candleRef.current.setData([]);
      volumeRef.current.setData([]);
      return;
    }
    candleRef.current.setData(
      bars.map((bar) => ({
        time: toDay(bar.date),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    );
    volumeRef.current.setData(
      bars.map((bar) => ({
        time: toDay(bar.date),
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(34,197,94,0.4)' : 'rgba(239,68,68,0.4)',
      })) as HistogramData[],
    );
    chartRef.current.timeScale().fitContent();
  }, [bars]);

  async function fetchOlder() {
    const before = oldestBarDate(bars);
    if (!before) return;
    setFetchingOlder(true);
    setOlderError(null);
    try {
      const older = await api.getOHLCV(symbol, '1D', 20, before);
      setBars((current) => mergeBarsOldestFirst(current, older.bars));
      setHasMore(older.has_more);
      if (older.bars.length === 0) {
        setOlderError(older.message || 'No older daily candles available.');
      }
    } catch (err) {
      setOlderError((err as Error).message);
    } finally {
      setFetchingOlder(false);
    }
  }

  const last = bars[bars.length - 1];
  const hasBars = bars.length > 0;

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">{symbol} · 1 Day OHLCV</span>
        <div className="flex items-center gap-2">
          {last && (
            <span className="font-mono text-xs text-slate-300">
              LTP ₹{last.close.toFixed(2)}
            </span>
          )}
          <button
            type="button"
            className="btn-primary text-xs"
            disabled={fetchingOlder || !hasMore || !hasBars}
            onClick={() => void fetchOlder()}
          >
            {fetchingOlder ? 'Fetching…' : 'Fetch Older Data'}
          </button>
        </div>
      </div>

      {initial.isLoading && (
        <div className="flex h-[380px] items-center justify-center text-sm text-slate-500">
          Loading daily candles…
        </div>
      )}
      {initial.isError && (
        <div className="flex h-[380px] items-center justify-center text-sm text-terminal-sell">
          Chart unavailable: {(initial.error as Error).message}
        </div>
      )}
      {!initial.isLoading && !initial.isError && !hasBars && (
        <div className="flex h-[380px] items-center justify-center px-4 text-center text-sm text-slate-500">
          {initial.data?.message || 'No daily history. Use Refresh Data to bootstrap this symbol.'}
        </div>
      )}

      <div
        ref={containerRef}
        className={hasBars && !initial.isLoading ? 'block' : 'hidden'}
      />

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-terminal-border px-4 py-1.5 text-[10px] text-slate-500">
        <span>
          Default view: latest {Math.min(20, bars.length)} trading days
          {bars.length > 20 ? ` · extended to ${bars.length} days` : ''}
          {initial.data?.delayed ? ' · Delayed EOD' : ''}
        </span>
        <span>
          {hasMore ? 'Older candles available' : 'Start of stored history'}
        </span>
      </div>
      {olderError && (
        <p className="border-t border-terminal-border px-4 py-2 text-xs text-terminal-warn">
          {olderError}
        </p>
      )}
    </div>
  );
}
