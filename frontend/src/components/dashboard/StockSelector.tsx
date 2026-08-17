import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';
import type { StockSummary } from '../../types/api';

interface StockSelectorProps {
  symbol: string;
  onSymbolChange: (symbol: string) => void;
}

function formatPrice(stock: StockSummary | undefined): string {
  if (!stock?.last_price) return '—';
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    maximumFractionDigits: 2,
  }).format(stock.last_price);
}

function formatChange(pct: number | null | undefined): string {
  if (pct == null) return '';
  const sign = pct >= 0 ? '+' : '';
  return `${sign}${pct.toFixed(2)}%`;
}

export function StockSelector({ symbol, onSymbolChange }: StockSelectorProps) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const stocksQuery = useQuery({
    queryKey: ['stocks', query],
    queryFn: () => api.listStocks(query, 50),
    enabled: open || query.length > 0,
  });

  const selectedQuery = useQuery({
    queryKey: ['stock', symbol],
    queryFn: () => api.getStock(symbol),
  });

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const selected = selectedQuery.data;
  const stocks = stocksQuery.data?.stocks ?? [];

  return (
    <div ref={containerRef} className="panel relative">
      <div className="panel-header">
        <span className="panel-title">Symbol</span>
        {selected && (
          <span
            className={`text-xs font-mono ${
              (selected.daily_change_pct ?? 0) >= 0
                ? 'text-terminal-buy'
                : 'text-terminal-sell'
            }`}
          >
            {formatChange(selected.daily_change_pct)}
          </span>
        )}
      </div>
      <div className="p-3">
        <input
          type="text"
          className="input-field font-mono uppercase"
          placeholder="Search symbol…"
          value={open ? query : symbol}
          onChange={(e) => {
            setQuery(e.target.value.toUpperCase());
            setOpen(true);
          }}
          onFocus={() => {
            setQuery('');
            setOpen(true);
          }}
        />
        {selectedQuery.isLoading ? (
          <p className="mt-2 text-xs text-slate-500">Loading quote…</p>
        ) : selectedQuery.isError ? (
          <p className="mt-2 text-xs text-terminal-sell">Quote unavailable</p>
        ) : selected ? (
          <div className="mt-2">
            <p className="text-sm font-medium text-slate-200">
              {selected.company_name}
            </p>
            <p className="font-mono text-lg text-slate-100">
              {formatPrice(selected)}
            </p>
            {selected.sector && (
              <p className="text-xs text-slate-500">{selected.sector}</p>
            )}
          </div>
        ) : null}

        {open && (
          <ul className="absolute left-0 right-0 top-full z-20 mt-1 max-h-60 overflow-y-auto rounded border border-terminal-border bg-terminal-panel shadow-xl">
            {stocksQuery.isLoading && (
              <li className="px-3 py-2 text-xs text-slate-500">Searching…</li>
            )}
            {stocksQuery.isError && (
              <li className="px-3 py-2 text-xs text-terminal-sell">
                Search failed
              </li>
            )}
            {!stocksQuery.isLoading && stocks.length === 0 && (
              <li className="px-3 py-2 text-xs text-slate-500">No matches</li>
            )}
            {stocks.map((stock) => (
              <li key={stock.symbol}>
                <button
                  type="button"
                  className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-slate-800"
                  onClick={() => {
                    onSymbolChange(stock.symbol);
                    setQuery('');
                    setOpen(false);
                  }}
                >
                  <span>
                    <span className="font-mono font-medium">{stock.symbol}</span>
                    <span className="ml-2 text-xs text-slate-500">
                      {stock.company_name}
                    </span>
                  </span>
                  {stock.is_holding && (
                    <span className="text-[10px] uppercase text-terminal-accent">
                      Held
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
