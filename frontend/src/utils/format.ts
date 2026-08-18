export function formatCurrency(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return '—';
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: digits,
  }).format(value);
}

export function formatPct(value: number | null | undefined, alreadyFraction = false): string {
  if (value == null || Number.isNaN(value)) return '—';
  const pct = alreadyFraction ? value * 100 : value;
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}

export function pnlClass(value: number | null | undefined): string {
  if (value == null || value === 0) return 'text-slate-400';
  return value > 0 ? 'text-terminal-buy' : 'text-terminal-sell';
}

export function formatTs(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
