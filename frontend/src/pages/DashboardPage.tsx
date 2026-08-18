import { KPICards } from '../components/dashboard/KPICards';
import { StockSelector } from '../components/dashboard/StockSelector';
import { StockAnalysisWorkspace } from '../components/stock/StockAnalysisWorkspace';
import { QuickTrade } from '../components/dashboard/QuickTrade';
import { TimeframeMatrix } from '../components/dashboard/TimeframeMatrix';
import { Assumption } from '../components/dashboard/Assumption';
import { Positions } from '../components/dashboard/Positions';
import type { Timeframe } from '../types/api';

interface DashboardPageProps {
  symbol: string;
  timeframe: Timeframe;
  onSymbolChange: (symbol: string) => void;
  onTimeframeChange: (tf: Timeframe) => void;
}

export function DashboardPage({
  symbol,
  timeframe,
  onSymbolChange,
}: DashboardPageProps) {
  return (
    <div className="space-y-4">
      <KPICards />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <div className="lg:col-span-3">
          <StockSelector symbol={symbol} onSymbolChange={onSymbolChange} />
        </div>
        <div className="lg:col-span-9">
          <StockAnalysisWorkspace symbol={symbol} variant="embedded" showTradePanel={false} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
        <QuickTrade symbol={symbol} />
        <Assumption symbol={symbol} timeframe={timeframe} />
        <TimeframeMatrix symbol={symbol} />
      </div>

      <Positions />
    </div>
  );
}
