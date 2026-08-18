import { useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type HistogramData,
  type SeriesMarker,
  type IPriceLine,
} from 'lightweight-charts';
import { api } from '../../api/client';
import type { OHLCVBar, StrategySignalRow } from '../../types/api';
import { mergeBarsOldestFirst, oldestBarDate } from '../../utils/ohlcv';
import { strategyColor } from '../../utils/strategy';

type ChartInterval = '1D' | '1W' | '1M';

interface ChartWorkspaceProps {
  symbol: string;
  timeframe: ChartInterval;
  onTimeframeChange: (tf: ChartInterval) => void;
  strategies: StrategySignalRow[];
  enabledStrategies: Set<string>;
  selectedStrategy: string | null;
  expanded?: boolean;
  lastRefresh?: string | null;
  onRefreshComplete?: (ts: string) => void;
}

function toDay(dateStr: string): CandlestickData['time'] {
  return new Date(dateStr).toISOString().slice(0, 10) as CandlestickData['time'];
}

function formatBarDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString();
}

export function ChartWorkspace({
  symbol,
  timeframe,
  onTimeframeChange,
  strategies,
  enabledStrategies,
  selectedStrategy,
  expanded = false,
  lastRefresh,
  onRefreshComplete,
}: ChartWorkspaceProps) {
  const queryClient = useQueryClient();
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const priceLinesRef = useRef<IPriceLine[]>([]);
  const [bars, setBars] = useState<OHLCVBar[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [olderError, setOlderError] = useState<string | null>(null);
  const [fetchingOlder, setFetchingOlder] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState<string | null>(null);
  const [hoverBar, setHoverBar] = useState<OHLCVBar | null>(null);

  const limit = timeframe === '1D' ? 20 : 120;

  const initial = useQuery({
    queryKey: ['ohlcv', symbol, timeframe, limit],
    queryFn: () => api.getOHLCV(symbol, timeframe, limit),
    retry: false,
  });

  useEffect(() => {
    setBars([]);
    setHasMore(false);
    setOlderError(null);
  }, [symbol, timeframe]);

  useEffect(() => {
    if (!initial.data) return;
    setBars(initial.data.bars);
    setHasMore(timeframe === '1D' ? initial.data.has_more : false);
    setOlderError(null);
  }, [initial.data, symbol, timeframe]);

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
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#1e293b' },
      timeScale: { borderColor: '#1e293b', timeVisible: true, secondsVisible: false },
      width: containerRef.current.clientWidth,
      height: expanded ? 520 : 400,
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
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    chart.subscribeCrosshairMove((param) => {
      if (!param.time || !candleRef.current) {
        setHoverBar(null);
        return;
      }
      const key = String(param.time);
      const match = bars.find((b) => toDay(b.date) === key);
      setHoverBar(match ?? null);
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
      priceLinesRef.current = [];
    };
  }, [symbol, expanded]);

  const overlayStrategies = useMemo(() => {
    const list = strategies.filter((s) => enabledStrategies.has(s.strategy));
    if (selectedStrategy) {
      const sel = list.find((s) => s.strategy === selectedStrategy);
      return sel ? [sel] : list.slice(0, 1);
    }
    return list.slice(0, 3);
  }, [strategies, enabledStrategies, selectedStrategy]);

  useEffect(() => {
    const series = candleRef.current;
    const chart = chartRef.current;
    if (!series || !chart) return;

    for (const line of priceLinesRef.current) {
      series.removePriceLine(line);
    }
    priceLinesRef.current = [];

    if (bars.length === 0) {
      series.setData([]);
      volumeRef.current?.setData([]);
      series.setMarkers([]);
      return;
    }

    series.setData(
      bars.map((bar) => ({
        time: toDay(bar.date),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      })),
    );
    volumeRef.current?.setData(
      bars.map((bar) => ({
        time: toDay(bar.date),
        value: bar.volume,
        color: bar.close >= bar.open ? 'rgba(34,197,94,0.4)' : 'rgba(239,68,68,0.4)',
      })) as HistogramData[],
    );

    const markers: SeriesMarker<Time>[] = [];
    overlayStrategies.forEach((row, idx) => {
      const color = strategyColor(strategies.indexOf(row));
      const lastBar = bars[bars.length - 1];
      if (!lastBar || row.status === 'ERROR') return;
      const t = toDay(lastBar.date);
      if (row.signal === 'BUY') {
        markers.push({
          time: t,
          position: 'belowBar',
          color,
          shape: 'arrowUp',
          text: row.display_name.slice(0, 8),
        });
      } else if (row.signal === 'SELL') {
        markers.push({
          time: t,
          position: 'aboveBar',
          color,
          shape: 'arrowDown',
          text: row.display_name.slice(0, 8),
        });
      }
      const entry = row.entry_price ?? row.current_price;
      if (entry != null) {
        priceLinesRef.current.push(
          series.createPriceLine({
            price: entry,
            color,
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: `${row.display_name} entry`,
          }),
        );
      }
      if (row.stop_loss != null) {
        priceLinesRef.current.push(
          series.createPriceLine({
            price: row.stop_loss,
            color: '#ef4444',
            lineWidth: 1,
            lineStyle: 0,
            axisLabelVisible: true,
            title: `${row.display_name} SL`,
          }),
        );
      }
      if (row.target != null) {
        priceLinesRef.current.push(
          series.createPriceLine({
            price: row.target,
            color: '#22c55e',
            lineWidth: 1,
            lineStyle: 0,
            axisLabelVisible: true,
            title: `${row.display_name} target`,
          }),
        );
      }
    });
    series.setMarkers(markers);
    chart.timeScale().fitContent();
  }, [bars, overlayStrategies, strategies]);

  async function loadMore() {
    if (timeframe !== '1D') return;
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

  async function refresh() {
    setRefreshing(true);
    setRefreshMsg(null);
    try {
      const status = await api.refreshMarketData(symbol);
      if (!status.success) {
        setRefreshMsg(status.message || 'Refresh failed — cached data kept.');
        return;
      }
      const ts = status.last_refresh ?? new Date().toISOString();
      onRefreshComplete?.(ts);
      setRefreshMsg('Data refreshed');
      await queryClient.invalidateQueries({ queryKey: ['ohlcv', symbol] });
      await queryClient.invalidateQueries({ queryKey: ['stock', symbol] });
      await queryClient.invalidateQueries({ queryKey: ['strategy-analysis', symbol] });
    } catch (err) {
      setRefreshMsg(`${(err as Error).message} — cached data kept.`);
    } finally {
      setRefreshing(false);
    }
  }

  const last = bars[bars.length - 1];
  const hasBars = bars.length > 0;
  const intervals: ChartInterval[] = ['1D', '1W', '1M'];

  return (
    <div className="panel">
      <div className="panel-header flex-wrap gap-2">
        <span className="panel-title">
          {symbol} · {initial.data?.interval_label ?? timeframe}
        </span>
        <div className="flex flex-wrap items-center gap-2">
          {intervals.map((tf) => (
            <button
              key={tf}
              type="button"
              className={`rounded px-2 py-0.5 font-mono text-[11px] ${
                timeframe === tf ? 'bg-terminal-accent text-white' : 'text-slate-500 hover:bg-slate-800'
              }`}
              onClick={() => onTimeframeChange(tf)}
            >
              {tf}
            </button>
          ))}
          {last && (
            <span className="font-mono text-xs text-slate-300">LTP ₹{last.close.toFixed(2)}</span>
          )}
          <button
            type="button"
            className="btn-primary text-xs"
            disabled={refreshing}
            onClick={() => void refresh()}
          >
            {refreshing ? 'Refreshing…' : 'Refresh Data'}
          </button>
          {timeframe === '1D' && (
            <button
              type="button"
              className="rounded border border-terminal-border px-2 py-0.5 text-xs text-slate-300"
              disabled={fetchingOlder || !hasMore || !hasBars}
              onClick={() => void loadMore()}
            >
              {fetchingOlder ? 'Loading…' : 'Load More History'}
            </button>
          )}
        </div>
      </div>

      {initial.isLoading && (
        <div className={`flex ${expanded ? 'h-[520px]' : 'h-[400px]'} items-center justify-center text-sm text-slate-500`}>
          Loading OHLCV…
        </div>
      )}
      {initial.isError && (
        <div className={`flex ${expanded ? 'h-[520px]' : 'h-[400px]'} items-center justify-center text-sm text-terminal-sell`}>
          Chart unavailable: {(initial.error as Error).message}
        </div>
      )}
      {!initial.isLoading && !initial.isError && !hasBars && (
        <div className={`flex ${expanded ? 'h-[520px]' : 'h-[400px]'} items-center justify-center px-4 text-center text-sm text-slate-500`}>
          {initial.data?.message || 'No OHLCV history. Refresh Data to bootstrap this symbol.'}
        </div>
      )}

      <div ref={containerRef} className={hasBars && !initial.isLoading ? 'block' : 'hidden'} />

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-terminal-border px-4 py-1.5 text-[10px] text-slate-500">
        <span>
          {hoverBar
            ? `${formatBarDate(hoverBar.date)} · O ${hoverBar.open.toFixed(2)} H ${hoverBar.high.toFixed(2)} L ${hoverBar.low.toFixed(2)} C ${hoverBar.close.toFixed(2)}`
            : last
              ? `Latest: ${formatBarDate(last.date)} · ${bars.length} bars`
              : '—'}
          {timeframe === '1D' && bars.length > 0 ? ` · showing latest ${Math.min(20, bars.length)}+ days` : ''}
          {initial.data?.delayed ? ' · Delayed EOD' : ''}
        </span>
        <span>
          {lastRefresh ? `Refreshed ${new Date(lastRefresh).toLocaleString()}` : 'Not refreshed this session'}
          {timeframe === '1D' && (hasMore ? ' · older data available' : ' · start of history')}
        </span>
      </div>

      {overlayStrategies.length > 0 && (
        <div className="flex flex-wrap gap-2 border-t border-terminal-border px-4 py-2">
          {overlayStrategies.map((row) => (
            <span
              key={row.strategy}
              className="rounded px-2 py-0.5 text-[10px]"
              style={{
                backgroundColor: `${strategyColor(strategies.indexOf(row))}22`,
                color: strategyColor(strategies.indexOf(row)),
              }}
            >
              {row.display_name}: {row.signal}
            </span>
          ))}
        </div>
      )}

      {refreshMsg && (
        <p className="border-t border-terminal-border px-4 py-2 text-xs text-terminal-warn">{refreshMsg}</p>
      )}
      {olderError && (
        <p className="border-t border-terminal-border px-4 py-2 text-xs text-terminal-warn">{olderError}</p>
      )}
    </div>
  );
}

// lightweight-charts Time type alias for markers
type Time = CandlestickData['time'];
