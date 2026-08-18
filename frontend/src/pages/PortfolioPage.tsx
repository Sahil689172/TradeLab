import { KPICards } from '../components/dashboard/KPICards';
import { Positions } from '../components/dashboard/Positions';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { formatCurrency, formatPct } from '../utils/format';

export function PortfolioPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['portfolio'],
    queryFn: () => api.getPortfolio(),
  });
  const k = data?.kpis;

  return (
    <div className="space-y-4">
      {isLoading && <div className="panel p-4 text-sm text-slate-500">Loading portfolio…</div>}
      {isError && (
        <div className="panel p-4 text-sm text-terminal-sell">{(error as Error).message}</div>
      )}
      {k && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
          <Info label="Total capital" value={formatCurrency(k.initial_capital)} />
          <Info label="Portfolio value" value={formatCurrency(k.current_value)} />
          <Info label="Available cash" value={formatCurrency(k.available_cash)} />
          <Info label="Invested capital" value={formatCurrency(k.total_invested)} />
          <Info label="Realized P&L" value={formatCurrency(k.realized_pnl)} />
          <Info label="Unrealized P&L" value={formatCurrency(k.unrealized_pnl)} />
          <Info label="Today's P&L" value={formatCurrency(k.todays_pnl)} />
          <Info label="Total exposure" value={formatPct(k.exposure_pct)} />
          <Info label="Max drawdown" value={formatPct(k.max_drawdown_pct)} />
        </div>
      )}
      <KPICards />
      <Positions />
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel p-3">
      <p className="text-[11px] uppercase text-slate-500">{label}</p>
      <p className="font-mono text-sm text-slate-200">{value}</p>
    </div>
  );
}
