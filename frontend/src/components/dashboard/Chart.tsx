import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  ColorType,
} from 'lightweight-charts';
import { api } from '../../api/client';
import { TIMEFRAMES, type Timeframe } from '../../types/api';

function toChartTime(dateStr: string, timeframe: Timeframe): CandlestickData['time'] {
  const d = new Date(dateStr);
  if (timeframe === '1D' || timeframe === '1W' || timeframe === '1M') {
    return d.toISOString().slice(0, 10) as CandlestickData['time'];
  }
  return Math.floor(d.getTime() / 1000) as CandlestickData['time'];
}

interface ChartProps {
  symbol: string;
  timeframe: Timeframe;
  onTimeframeChange: (tf: Timeframe) => void;
}

export function Chart({ symbol, timeframe, onTimeframeChange }: ChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  const ohlcvQuery = useQuery({
    queryKey: ['ohlcv', symbol, timeframe],
    queryFn: () => api.getOHLCV(symbol, timeframe),
    retry: false,
  });

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
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#1e293b' },
      timeScale: { borderColor: '#1e293b' },
      width: containerRef.current.clientWidth,
      height: 360,
    });

    const series = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const observer = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    observer.observe(containerRef.current);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  useEffect(() => {
    const series = seriesRef.current;
    const chart = chartRef.current;
    if (!series || !chart) return;

    const bars = ohlcvQuery.data?.bars ?? [];
    if (bars.length === 0) {
      series.setData([]);
      return;
    }

    const candleData: CandlestickData[] = bars.map((bar) => ({
      time: toChartTime(bar.date, timeframe),
      open: bar.open,
      high: bar.high,
      low: bar.low,
      close: bar.close,
    }));

    series.setData(candleData);
    chart.timeScale().fitContent();
  }, [ohlcvQuery.data]);

  const data = ohlcvQuery.data;
  const hasBars = (data?.bars.length ?? 0) > 0;
  const unsupportedMessage = data?.message;

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">
          {symbol} · {data?.interval_label ?? timeframe}
        </span>
        <div className="flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => onTimeframeChange(tf)}
              className={`rounded px-2 py-0.5 font-mono text-[11px] transition ${
                timeframe === tf
                  ? 'bg-terminal-accent text-white'
                  : 'text-slate-500 hover:bg-slate-800 hover:text-slate-300'
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>

      {ohlcvQuery.isLoading && (
        <div className="flex h-[360px] items-center justify-center text-sm text-slate-500">
          Loading chart data…
        </div>
      )}

      {ohlcvQuery.isError && (
        <div className="flex h-[360px] items-center justify-center text-sm text-terminal-sell">
          Chart unavailable: {(ohlcvQuery.error as Error).message}
        </div>
      )}

      {!ohlcvQuery.isLoading && !ohlcvQuery.isError && !hasBars && (
        <div className="flex h-[360px] flex-col items-center justify-center gap-2 px-4 text-center text-sm text-slate-500">
          <p>No OHLCV data for this interval.</p>
          {unsupportedMessage && (
            <p className="text-xs text-terminal-warn">{unsupportedMessage}</p>
          )}
        </div>
      )}

      <div
        ref={containerRef}
        className={hasBars && !ohlcvQuery.isLoading ? 'block' : 'hidden'}
      />

      {data && hasBars && (
        <div className="flex items-center justify-between border-t border-terminal-border px-4 py-1.5 text-[10px] text-slate-500">
          <span>
            Source: {data.source}
            {data.delayed && ' · Delayed'}
          </span>
          <span>{data.bars.length} bars</span>
        </div>
      )}
    </div>
  );
}
