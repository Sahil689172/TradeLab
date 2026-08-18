import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { DEFAULT_SYMBOL } from '../../types/api';

interface TopBarProps {
  title: string;
  symbol: string;
  lastRefresh: string | null;
  onRefreshComplete: (timestamp: string) => void;
}

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export function TopBar({ title, symbol, lastRefresh, onRefreshComplete }: TopBarProps) {
  const queryClient = useQueryClient();
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const stockQuery = useQuery({
    queryKey: ['stock', symbol],
    queryFn: () => api.getStock(symbol),
    retry: false,
  });

  const statusQuery = useQuery({
    queryKey: ['system-status'],
    queryFn: () => api.getSystemStatus(),
    retry: false,
  });

  useEffect(() => {
    if (!lastRefresh && statusQuery.data?.last_refresh) {
      onRefreshComplete(statusQuery.data.last_refresh);
    }
  }, [lastRefresh, onRefreshComplete, statusQuery.data?.last_refresh]);

  const refreshMutation = useMutation({
    mutationFn: () => api.refreshMarketData(symbol || DEFAULT_SYMBOL),
    onSuccess: (data) => {
      if (!data.success) {
        setRefreshError(data.message || 'Refresh failed. Cached data kept.');
        setRefreshMessage(null);
        return;
      }
      const ts = data.last_refresh ?? new Date().toISOString();
      onRefreshComplete(ts);
      setRefreshError(null);
      setRefreshMessage(data.message || 'Market data updated');
      void queryClient.invalidateQueries();
    },
    onError: (err: Error) => {
      setRefreshError(`${err.message}. Cached data kept.`);
      setRefreshMessage(null);
    },
  });

  const stock = stockQuery.data;
  const marketOpen = stock?.history_available ?? false;

  return (
    <header className="relative flex h-12 flex-shrink-0 items-center justify-between border-b border-terminal-border bg-terminal-panel px-4">
      <div className="flex items-center gap-4">
        <h1 className="text-sm font-semibold text-slate-200">{title}</h1>
        <div className="hidden items-center gap-2 sm:flex">
          <span
            className={`status-dot ${marketOpen ? 'bg-terminal-buy' : 'bg-terminal-warn'}`}
          />
          <span className="text-xs text-slate-400">
            {stockQuery.isLoading
              ? 'Loading market…'
              : stockQuery.isError
                ? 'Market status unavailable'
                : marketOpen
                  ? 'Data available'
                  : 'No history — refresh required'}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-3">
        <div className="hidden text-right text-xs text-slate-500 md:block">
          <span className="block">Last refresh</span>
          <span className="font-mono text-slate-400">
            {formatTimestamp(lastRefresh)}
          </span>
        </div>
        <button
          type="button"
          className="btn-primary"
          disabled={refreshMutation.isPending}
          onClick={() => {
            setRefreshError(null);
            setRefreshMessage(null);
            refreshMutation.mutate();
          }}
        >
          {refreshMutation.isPending ? 'Refreshing…' : 'Refresh Data'}
        </button>
      </div>
      {(refreshMessage || refreshError) && (
        <p
          className={`absolute right-4 top-12 z-10 rounded border border-terminal-border bg-terminal-panel px-3 py-1 text-[11px] ${
            refreshError ? 'text-terminal-sell' : 'text-terminal-buy'
          }`}
        >
          {refreshError ?? refreshMessage}
        </p>
      )}
    </header>
  );
}
