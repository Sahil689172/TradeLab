import { useEffect, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import { ChartWorkspace } from '../chart/ChartWorkspace';
import { StrategyFilterPanel } from '../chart/StrategyFilterPanel';
import { AnalysisPanel } from '../chart/AnalysisPanel';
import { MonteCarloPanel } from '../chart/MonteCarloPanel';
import { MonteCarloPage } from '../../pages/MonteCarloPage';
import { TradePanel } from '../dashboard/TradePanel';
import { StockStrategyTable } from '../dashboard/StockStrategyTable';
import { formatCurrency, formatPct, formatTs, pnlClass } from '../../utils/format';

type ChartInterval = '1D' | '1W' | '1M';

export interface StockAnalysisWorkspaceProps {
  symbol: string;
  variant?: 'full' | 'embedded';
  showTradePanel?: boolean;
  lastRefresh?: string | null;
  onRefreshComplete?: (ts: string) => void;
}

export function StockAnalysisWorkspace({
  symbol,
  variant = 'full',
  showTradePanel = true,
  lastRefresh: externalRefresh,
  onRefreshComplete,
}: StockAnalysisWorkspaceProps) {
  const [timeframe, setTimeframe] = useState<ChartInterval>('1D');
  const [lastRefresh, setLastRefresh] = useState<string | null>(externalRefresh ?? null);
  const [enabledStrategies, setEnabledStrategies] = useState<Set<string>>(new Set());
  const [selectedStrategy, setSelectedStrategy] = useState<string | null>(null);
  const [mcSimulations, setMcSimulations] = useState<number | null>(null);

  const stockQuery = useQuery({
    queryKey: ['stock', symbol],
    queryFn: () => api.getStock(symbol),
    retry: false,
  });
  const analysisQuery = useQuery({
    queryKey: ['strategy-analysis', symbol, timeframe],
    queryFn: () => api.getStrategyAnalysis(symbol, timeframe, false),
    retry: false,
  });

  const strategies = analysisQuery.data?.strategies ?? [];
  const strategyKey = strategies.map((s) => s.strategy).join(',');

  useEffect(() => {
    if (externalRefresh) setLastRefresh(externalRefresh);
  }, [externalRefresh]);

  useEffect(() => {
    if (strategies.length === 0) return;
    setEnabledStrategies(new Set(strategies.map((s) => s.strategy)));
    setSelectedStrategy((prev) => {
      if (prev && strategies.some((s) => s.strategy === prev)) return prev;
      const first = strategies.find((s) => s.signal !== 'NEUTRAL') ?? strategies[0];
      return first.strategy;
    });
  }, [symbol, timeframe, strategyKey]);

  const selectedRow = useMemo(
    () => strategies.find((s) => s.strategy === selectedStrategy) ?? null,
    [strategies, selectedStrategy],
  );

  const stock = stockQuery.data;
  const consensus = analysisQuery.data?.assumption.bias;
  const topSignal = selectedRow?.signal ?? strategies.find((s) => s.signal !== 'NEUTRAL')?.signal;

  function toggleStrategy(name: string) {
    setEnabledStrategies((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function handleRefreshComplete(ts: string) {
    setLastRefresh(ts);
    onRefreshComplete?.(ts);
  }

  const expanded = variant === 'full';
  const gridMain = expanded ? 'xl:col-span-9 space-y-4' : 'lg:col-span-9 space-y-4';
  const gridSide = expanded ? 'xl:col-span-3 space-y-4' : 'lg:col-span-3 space-y-4';

  // If a Monte Carlo run is launched, show the full-page workspace instead.
  if (mcSimulations !== null && selectedStrategy) {
    return (
      <MonteCarloPage
        symbol={symbol}
        currentPrice={stock?.last_price ?? null}
        strategy={selectedStrategy}
        strategyRow={selectedRow}
        simulations={mcSimulations}
        onBack={() => setMcSimulations(null)}
      />
    );
  }

  return (
    <div className="space-y-4">
      {stockQuery.isLoading && (
        <div className="panel p-4 text-sm text-slate-500">Loading {symbol}…</div>
      )}
      {stockQuery.isError && (
        <div className="panel p-4 text-sm text-terminal-sell">{(stockQuery.error as Error).message}</div>
      )}

      {stock && variant === 'full' && (
        <div className="panel p-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="font-mono text-2xl font-bold text-slate-100">{stock.symbol}</h2>
              <p className="text-sm text-slate-400">{stock.company_name}</p>
              <p className="text-xs text-slate-500">
                {stock.sector ?? 'Sector n/a'} · Last data {formatTs(stock.last_data_date)}
                {lastRefresh ? ` · Refreshed ${formatTs(lastRefresh)}` : ''}
              </p>
            </div>
            <div className="text-right">
              <p className="font-mono text-2xl">{formatCurrency(stock.last_price)}</p>
              <p className={`font-mono text-sm ${pnlClass(stock.daily_change_pct)}`}>
                {formatPct(stock.daily_change_pct, true)}
              </p>
              <p className="text-[10px] uppercase text-slate-500">Assumption: {consensus ?? '—'}</p>
            </div>
          </div>
        </div>
      )}

      {analysisQuery.isError && (
        <div className="panel p-4 text-sm text-terminal-sell">
          Strategy engine: {(analysisQuery.error as Error).message}
        </div>
      )}

      <div className={`grid grid-cols-1 gap-4 xl:grid-cols-12`}>
        <div className={gridMain}>
          <ChartWorkspace
            symbol={symbol}
            timeframe={timeframe}
            onTimeframeChange={setTimeframe}
            strategies={strategies}
            enabledStrategies={enabledStrategies}
            selectedStrategy={selectedStrategy}
            expanded={expanded}
            lastRefresh={lastRefresh}
            onRefreshComplete={handleRefreshComplete}
          />
          <StrategyFilterPanel
            strategies={strategies}
            enabled={enabledStrategies}
            selected={selectedStrategy}
            onToggle={toggleStrategy}
            onSelect={setSelectedStrategy}
          />
          <StockStrategyTable
            symbol={symbol}
            timeframe={timeframe}
            onSelect={setSelectedStrategy}
            selected={selectedStrategy}
          />
        </div>
        <div className={gridSide}>
          <AnalysisPanel currentPrice={stock?.last_price ?? null} strategy={selectedRow} />
          {showTradePanel && (
            <TradePanel
              symbol={symbol}
              currentPrice={stock?.last_price ?? null}
              signal={topSignal}
              strategyRow={selectedRow}
            />
          )}
          <MonteCarloPanel
                symbol={symbol}
                strategy={selectedStrategy}
                strategyRow={selectedRow}
                currentPrice={stock?.last_price ?? null}
                onLaunch={(sims) => setMcSimulations(sims)}
              />
        </div>
      </div>
    </div>
  );
}
