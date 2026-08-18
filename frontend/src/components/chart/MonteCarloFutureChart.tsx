import type { HorizonOutlook } from '../../types/api';
import { formatCurrency, formatPct } from '../../utils/format';

interface MonteCarloFutureChartProps {
  currentPrice: number | null;
  horizons: HorizonOutlook[];
}

export function MonteCarloFutureChart({ currentPrice, horizons }: MonteCarloFutureChartProps) {
  const supported = horizons.filter((h) => h.supported);
  if (!currentPrice || currentPrice <= 0 || supported.length === 0) return null;

  const maxPrice = Math.max(
    currentPrice,
    ...supported.flatMap((h) => [h.upper_price ?? currentPrice, h.mean_price ?? currentPrice]),
  );
  const minPrice = Math.min(
    currentPrice,
    ...supported.flatMap((h) => [h.lower_price ?? currentPrice, h.mean_price ?? currentPrice]),
  );
  const span = Math.max(maxPrice - minPrice, 1);

  function y(price: number): number {
    return 8 + ((maxPrice - price) / span) * 72;
  }

  const points = supported.map((h, i) => ({
    h,
    x: 20 + ((i + 1) / (supported.length + 1)) * 260,
  }));

  return (
    <div className="rounded border border-dashed border-terminal-warn/40 bg-terminal-bg/40 p-3">
      <p className="text-[10px] uppercase text-terminal-warn">Simulated future bands (not market data)</p>
      <svg viewBox="0 0 300 100" className="mt-2 h-28 w-full" aria-hidden>
        <line x1="10" y1={y(currentPrice)} x2="290" y2={y(currentPrice)} stroke="#64748b" strokeDasharray="4 4" />
        <circle cx="10" cy={y(currentPrice)} r="3" fill="#38bdf8" />
        {points.map(({ h, x }) => {
          const lo = h.lower_price ?? h.median_price ?? currentPrice;
          const hi = h.upper_price ?? h.median_price ?? currentPrice;
          const med = h.median_price ?? h.mean_price ?? currentPrice;
          return (
            <g key={h.trading_days}>
              <line x1={x} y1={y(hi)} x2={x} y2={y(lo)} stroke="#f59e0b" strokeWidth="6" opacity="0.35" />
              <circle cx={x} cy={y(med)} r="3" fill="#f59e0b" />
              <text x={x} y="96" textAnchor="middle" fill="#94a3b8" fontSize="8">
                +{h.trading_days}d
              </text>
            </g>
          );
        })}
      </svg>
      <div className="mt-2 grid gap-2 sm:grid-cols-3">
        {supported.map((h) => (
          <div key={h.trading_days} className="rounded bg-terminal-bg/60 p-2 text-[10px] text-slate-400">
            <p className="font-semibold text-slate-300">{h.label}</p>
            <p>Median {formatCurrency(h.median_price)}</p>
            <p>
              Band {formatCurrency(h.lower_price)} — {formatCurrency(h.upper_price)}
            </p>
            <p>Return {formatPct(h.expected_return_pct, true)}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
