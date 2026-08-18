import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { HistoricalChart } from '../components/dashboard/HistoricalChart';
import { TradePanel } from '../components/dashboard/TradePanel';
import { StockStrategyTable } from '../components/dashboard/StockStrategyTable';
import { formatCurrency, formatPct, formatTs, pnlClass } from '../utils/format';

interface StockDetailPageProps {
  symbol: string;
  onBack: () => void;
}

export function StockDetailPage({ symbol, onBack }: StockDetailPageProps) {
  const stockQuery = useQuery({
    queryKey: ['stock', symbol],
    queryFn: () => api.getStock(symbol),
    retry: false,
  });
  const analysisQuery = useQuery({
    queryKey: ['strategy-analysis', symbol, '1D'],
    queryFn: () => api.getStrategyAnalysis(symbol, '1D', false),
    retry: false,
  });

  const stock = stockQuery.data;
  const consensus = analysisQuery.data?.assumption.bias;
  const topSignal = analysisQuery.data?.strategies.find((s) => s.signal !== 'NEUTRAL')?.signal;

  return (
    <div className="space-y-4">
      <button type="button" className="text-xs text-slate-500 hover:text-slate-300" onClick={onBack}>
        ← Stocks
      </button>

      {stockQuery.isLoading && <div className="panel p-4 text-sm text-slate-500">Loading {symbol}…</div>}
      {stockQuery.isError && (
        <div className="panel p-4 text-sm text-terminal-sell">
          {(stockQuery.error as Error).message}
        </div>
      )}

      {stock && (
        <div className="panel p-4">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="font-mono text-2xl font-bold text-slate-100">{stock.symbol}</h2>
              <p className="text-sm text-slate-400">{stock.company_name}</p>
              <p className="text-xs text-slate-500">
                {stock.sector ?? 'Sector n/a'} · Last data {formatTs(stock.last_data_date)}
              </p>
            </div>
            <div className="text-right">
              <p className="font-mono text-2xl">{formatCurrency(stock.last_price)}</p>
              <p className={`font-mono text-sm ${pnlClass(stock.daily_change_pct)}`}>
                {formatPct(stock.daily_change_pct, true)}
              </p>
              <p className="text-[10px] uppercase text-slate-500">
                Assumption: {consensus ?? '—'}
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <HistoricalChart symbol={symbol} />
        </div>
        <div className="lg:col-span-4">
          <TradePanel symbol={symbol} currentPrice={stock?.last_price ?? null} signal={topSignal} />
        </div>
      </div>

      <StockStrategyTable symbol={symbol} />
    </div>
  );
}
