import { useQuery } from '@tanstack/react-query';
import { api } from '../api/client';
import { loadUiSettings, saveUiSettings } from '../utils/settings';
import { useState } from 'react';

export function SettingsPage() {
  const status = useQuery({
    queryKey: ['system-status'],
    queryFn: () => api.getSystemStatus(),
  });
  const [settings, setSettings] = useState(() => loadUiSettings());

  function update<K extends keyof typeof settings>(key: K, value: (typeof settings)[K]) {
    const next = { ...settings, [key]: value };
    setSettings(next);
    saveUiSettings(next);
  }

  return (
    <div className="grid max-w-3xl gap-4">
      <div className="panel space-y-2 p-4 text-sm">
        <h2 className="text-sm font-semibold text-slate-200">Connection</h2>
        <Row
          label="Backend"
          value={status.isError ? 'disconnected' : 'http://127.0.0.1:8000/api/v1'}
        />
        <Row label="Market-data provider" value={status.data?.market_data_source ?? 'yfinance'} />
        <Row label="yfinance" value={status.data?.yfinance_status ?? 'unknown'} />
        <Row label="Environment" value={status.data?.environment ?? '—'} />
        <Row label="Universe size" value={String(status.data?.universe_size ?? '—')} />
        <Row
          label="Last backend refresh"
          value={status.data?.last_refresh ? new Date(status.data.last_refresh).toLocaleString() : '—'}
        />
        <Row label="Trading mode" value="PAPER (simulated). Live broker is not connected." />
      </div>

      <div className="panel space-y-3 p-4 text-sm">
        <h2 className="text-sm font-semibold text-slate-200">Display & paper book</h2>
        <label className="block text-xs text-slate-500">
          Default stock
          <input
            className="input-field mt-1 font-mono"
            value={settings.defaultSymbol}
            onChange={(e) => update('defaultSymbol', e.target.value.toUpperCase())}
          />
        </label>
        <label className="block text-xs text-slate-500">
          Status poll interval (seconds, 0 = manual Refresh Data only)
          <input
            className="input-field mt-1 font-mono"
            type="number"
            min="0"
            max="3600"
            value={settings.autoRefreshSeconds}
            onChange={(e) => update('autoRefreshSeconds', Number(e.target.value) || 0)}
          />
        </label>
        <Row label="Default timeframe" value="1D (daily stored history)" />
        <Row label="Theme" value="Dark terminal (fixed)" />
        <Row
          label="Refresh Data"
          value="Top bar calls POST /api/v1/market-data/refresh. Frontend never calls yfinance."
        />
        <Row
          label="Initial capital"
          value="₹10,00,000 paper book (server-side, not editable here)"
        />
        <label className="flex items-center justify-between gap-4 border-b border-terminal-border/40 py-1.5 text-sm">
          <span className="text-slate-500">Paper trading</span>
          <input type="checkbox" checked disabled />
        </label>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 border-b border-terminal-border/40 py-1.5">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200">{value}</span>
    </div>
  );
}
