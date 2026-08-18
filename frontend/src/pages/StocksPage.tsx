import { useMemo, useState, type MouseEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { useFavorites } from '../hooks/useFavorites';
import { formatCurrency, formatPct, formatTs, pnlClass } from '../utils/format';
import { loadWatchlist, saveWatchlist } from '../utils/settings';
import type { StockSummary } from '../types/api';

interface StocksPageProps {
  onSelectSymbol: (symbol: string) => void;
}

type SortKey = 'symbol' | 'company_name' | 'last_price' | 'daily_change_pct' | 'sector';

export function StocksPage({ onSelectSymbol }: StocksPageProps) {
  const [query, setQuery] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('symbol');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc');
  const [filter, setFilter] = useState<'all' | 'favorites' | 'watchlist' | 'holdings'>('all');
  const [sector, setSector] = useState('all');
  const [watchlist, setWatchlist] = useState(() => loadWatchlist());
  const { favorites, toggleFavorite } = useFavorites();

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['stocks', ''],
    queryFn: () => api.listStocks('', 501),
    retry: false,
  });

  const stocks = data?.stocks ?? [];
  const sectors = useMemo(() => {
    const names = new Set<string>();
    for (const s of stocks) {
      if (s.sector) names.add(s.sector);
    }
    return [...names].sort();
  }, [stocks]);

  const rows = useMemo(() => {
    const needle = query.trim().toUpperCase();
    let list = stocks.filter((s) => {
      if (needle && !s.symbol.includes(needle) && !s.company_name.toUpperCase().includes(needle)) {
        return false;
      }
      if (sector !== 'all' && s.sector !== sector) return false;
      if (filter === 'favorites') return favorites.has(s.symbol);
      if (filter === 'watchlist') return watchlist.has(s.symbol);
      if (filter === 'holdings') return s.is_holding;
      return true;
    });
    list = [...list].sort((a, b) => compareStock(a, b, sortKey, sortDir));
    return list;
  }, [stocks, query, filter, sector, favorites, watchlist, sortKey, sortDir]);

  function toggleSort(key: SortKey) {
    if (sortKey === key) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else {
      setSortKey(key);
      setSortDir('asc');
    }
  }

  function toggleFav(event: MouseEvent, symbol: string) {
    event.stopPropagation();
    toggleFavorite(symbol);
  }

  function toggleWatch(symbol: string) {
    const next = new Set(watchlist);
    if (next.has(symbol)) next.delete(symbol);
    else next.add(symbol);
    setWatchlist(next);
    saveWatchlist(next);
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <input
          className="input-field max-w-sm"
          placeholder="Search symbol or company"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {(['all', 'favorites', 'watchlist', 'holdings'] as const).map((id) => (
          <button
            key={id}
            type="button"
            className={`rounded px-3 py-1.5 text-xs uppercase ${filter === id ? 'bg-terminal-accent text-white' : 'text-slate-400 hover:bg-slate-800'}`}
            onClick={() => setFilter(id)}
          >
            {id}
          </button>
        ))}
        <select
          className="input-field max-w-[12rem] text-xs"
          value={sector}
          onChange={(e) => setSector(e.target.value)}
        >
          <option value="all">All sectors</option>
          {sectors.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
        <span className="ml-auto text-xs text-slate-500">
          {rows.length} / {data?.total ?? 0} symbols
        </span>
      </div>

      {isLoading && <div className="panel p-4 text-sm text-slate-500">Loading universe…</div>}
      {isError && (
        <div className="panel p-4 text-sm text-terminal-sell">
          Universe unavailable: {(error as Error).message}
        </div>
      )}

      {!isLoading && !isError && filter === 'favorites' && rows.length === 0 && (
        <div className="panel p-4 text-sm text-slate-500">No favorite stocks yet.</div>
      )}

      {!isLoading && !isError && rows.length > 0 && (
        <div className="panel max-h-[calc(100vh-12rem)] overflow-auto">
          <table className="w-full text-left text-sm">
            <thead className="sticky top-0 bg-terminal-panel">
              <tr className="border-b border-terminal-border text-[11px] uppercase text-slate-500">
                <th className="px-3 py-2"> </th>
                <Th label="Symbol" onClick={() => toggleSort('symbol')} />
                <Th label="Company" onClick={() => toggleSort('company_name')} />
                <Th label="Price" onClick={() => toggleSort('last_price')} />
                <Th label="Change %" onClick={() => toggleSort('daily_change_pct')} />
                <Th label="Sector" onClick={() => toggleSort('sector')} />
                <th className="px-3 py-2">History</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.symbol} className="border-b border-terminal-border/40 hover:bg-slate-800/40">
                  <td className="px-2 py-1.5">
                    <button
                      type="button"
                      className="text-xs text-slate-500"
                      aria-label={favorites.has(row.symbol) ? 'Remove favorite' : 'Add favorite'}
                      onClick={(e) => toggleFav(e, row.symbol)}
                    >
                      {favorites.has(row.symbol) ? '★' : '☆'}
                    </button>
                    <button type="button" className="ml-1 text-xs text-slate-500" onClick={() => toggleWatch(row.symbol)}>
                      {watchlist.has(row.symbol) ? '●' : '○'}
                    </button>
                  </td>
                  <td className="px-3 py-1.5">
                    <button
                      type="button"
                      className="font-mono font-semibold text-terminal-accent hover:underline"
                      onClick={() => onSelectSymbol(row.symbol)}
                    >
                      {row.symbol}
                    </button>
                  </td>
                  <td className="px-3 py-1.5 text-slate-300">{row.company_name}</td>
                  <td className="px-3 py-1.5 font-mono">{formatCurrency(row.last_price)}</td>
                  <td className={`px-3 py-1.5 font-mono ${pnlClass(row.daily_change_pct)}`}>
                    {formatPct(row.daily_change_pct, true)}
                  </td>
                  <td className="px-3 py-1.5 text-xs text-slate-500">{row.sector ?? '—'}</td>
                  <td className="px-3 py-1.5 text-[10px] text-slate-500">
                    {row.history_available ? `OK · ${formatTs(row.last_data_date)}` : 'Not bootstrapped'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Th({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <th className="cursor-pointer px-3 py-2 hover:text-slate-300" onClick={onClick}>
      {label}
    </th>
  );
}

function compareStock(a: StockSummary, b: StockSummary, key: SortKey, dir: 'asc' | 'desc'): number {
  const av = a[key];
  const bv = b[key];
  const an = av == null ? '' : av;
  const bn = bv == null ? '' : bv;
  let cmp = 0;
  if (typeof an === 'number' && typeof bn === 'number') cmp = an - bn;
  else cmp = String(an).localeCompare(String(bn));
  return dir === 'asc' ? cmp : -cmp;
}
