import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { PortfolioKPIs } from '../../types/api';

function formatCurrency(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 0,
  }).format(value);
}

function formatPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—';
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function pnlColor(value: number): string {
  if (value > 0) return 'text-terminal-buy';
  if (value < 0) return 'text-terminal-sell';
  return 'text-slate-400';
}

interface KPICardProps {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
}

function KPICard({ label, value, sub, valueClass }: KPICardProps) {
  return (
    <div className="panel p-4">
      <p className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
        {label}
      </p>
      <p className={`kpi-value mt-1 ${valueClass ?? ''}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-slate-500">{sub}</p>}
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-6">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="panel h-20 animate-pulse bg-slate-800/50" />
      ))}
    </div>
  );
}

export function KPICards() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['portfolio'],
    queryFn: () => api.getPortfolio(),
  });

  if (isLoading) return <LoadingSkeleton />;

  if (isError) {
    return (
      <div className="panel p-4 text-sm text-terminal-sell">
        KPI data unavailable: {(error as Error).message}
      </div>
    );
  }

  const kpis: PortfolioKPIs | undefined = data?.kpis;
  if (!kpis) {
    return (
      <div className="panel p-4 text-sm text-slate-500">No portfolio data</div>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-6">
      <KPICard label="Portfolio Value" value={formatCurrency(kpis.current_value)} />
      <KPICard
        label="Unrealized P&L"
        value={formatCurrency(kpis.unrealized_pnl)}
        valueClass={pnlColor(kpis.unrealized_pnl)}
      />
      <KPICard
        label="Today's P&L"
        value={formatCurrency(kpis.todays_pnl)}
        valueClass={pnlColor(kpis.todays_pnl)}
      />
      <KPICard label="Available Cash" value={formatCurrency(kpis.available_cash)} />
      <KPICard
        label="Exposure"
        value={formatPct(kpis.exposure_pct)}
        sub={`Invested ${formatCurrency(kpis.total_invested)}`}
      />
      <KPICard
        label="Max Drawdown"
        value={formatPct(kpis.max_drawdown_pct)}
        valueClass="text-terminal-sell"
      />
    </div>
  );
}
