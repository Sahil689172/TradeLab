import { useQuery } from '@tanstack/react-query';
import { api } from '../../api/client';

function StatusIndicator({
  label,
  value,
  ok,
}: {
  label: string;
  value: string;
  ok: boolean;
}) {
  return (
    <div className="flex items-center gap-2">
      <span className={`status-dot ${ok ? 'bg-terminal-buy' : 'bg-terminal-sell'}`} />
      <span className="text-slate-500">{label}:</span>
      <span className={ok ? 'text-slate-300' : 'text-terminal-sell'}>{value}</span>
    </div>
  );
}

export function StatusBar() {
  const { data, isLoading, isError } = useQuery({
    queryKey: ['system-status'],
    queryFn: () => api.getSystemStatus(),
    refetchInterval: 30_000,
  });

  return (
    <footer className="flex h-7 flex-shrink-0 items-center justify-between border-t border-terminal-border bg-terminal-panel px-4 text-[11px]">
      <div className="flex items-center gap-4">
        <StatusIndicator
          label="System"
          value={
            isLoading
              ? 'checking…'
              : isError
                ? 'offline'
                : data?.environment ?? 'unknown'
          }
          ok={!isError && (data?.backend_connected ?? false)}
        />
        <StatusIndicator
          label="yfinance"
          value={
            isLoading
              ? 'checking…'
              : isError
                ? 'unavailable'
                : data?.yfinance_status ?? 'unknown'
          }
          ok={!isError && data?.yfinance_status === 'available'}
        />
        <StatusIndicator
          label="Backend"
          value={
            isLoading
              ? 'connecting…'
              : isError
                ? 'disconnected'
                : 'connected'
          }
          ok={!isError && (data?.backend_connected ?? false)}
        />
      </div>
      <div className="hidden text-slate-500 sm:block">
        {data && (
          <>
            Universe: {data.universe_size} symbols
            {data.paper_trading && ' · Paper mode'}
          </>
        )}
      </div>
    </footer>
  );
}
