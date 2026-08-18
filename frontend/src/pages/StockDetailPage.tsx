import { StockAnalysisWorkspace } from '../components/stock/StockAnalysisWorkspace';

interface StockDetailPageProps {
  symbol: string;
  onBack: () => void;
}

export function StockDetailPage({ symbol, onBack }: StockDetailPageProps) {
  return (
    <div className="space-y-4">
      <button type="button" className="text-xs text-slate-500 hover:text-slate-300" onClick={onBack}>
        ← Stocks
      </button>
      <StockAnalysisWorkspace symbol={symbol} variant="full" />
    </div>
  );
}
