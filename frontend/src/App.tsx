import { useState } from 'react';
import { Sidebar } from './components/layout/Sidebar';
import { TopBar } from './components/layout/TopBar';
import { StatusBar } from './components/layout/StatusBar';
import { DashboardPage } from './pages/DashboardPage';
import { StocksPage } from './pages/StocksPage';
import { StockDetailPage } from './pages/StockDetailPage';
import { PortfolioPage } from './pages/PortfolioPage';
import { OrdersPage } from './pages/OrdersPage';
import { StrategiesPage } from './pages/StrategiesPage';
import { SettingsPage } from './pages/SettingsPage';
import { DEFAULT_SYMBOL, type Timeframe } from './types/api';
import { loadUiSettings, type AppPage } from './utils/settings';

const TITLES: Record<AppPage, string> = {
  dashboard: 'Trading Terminal',
  stocks: 'Stocks / Market',
  'stock-detail': 'Stock Detail',
  portfolio: 'Portfolio',
  orders: 'Orders',
  strategies: 'Strategies',
  settings: 'Settings',
};

export default function App() {
  const [page, setPage] = useState<AppPage>('dashboard');
  const [symbol, setSymbol] = useState(() => loadUiSettings().defaultSymbol || DEFAULT_SYMBOL);
  const [timeframe, setTimeframe] = useState<Timeframe>('1D');
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  function openStock(next: string) {
    setSymbol(next);
    setPage('stock-detail');
  }

  return (
    <div className="flex h-screen overflow-hidden bg-terminal-bg">
      <Sidebar active={page} onNavigate={(id) => setPage(id as AppPage)} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          title={page === 'stock-detail' ? `${symbol} · Stock Detail` : TITLES[page]}
          symbol={symbol}
          lastRefresh={lastRefresh}
          onRefreshComplete={setLastRefresh}
        />
        <main className="flex-1 overflow-y-auto p-4" data-page={page}>
          {page === 'dashboard' && (
            <DashboardPage
              symbol={symbol}
              timeframe={timeframe}
              onSymbolChange={setSymbol}
              onTimeframeChange={setTimeframe}
            />
          )}
          {page === 'stocks' && <StocksPage onSelectSymbol={openStock} />}
          {page === 'stock-detail' && (
            <StockDetailPage key={symbol} symbol={symbol} onBack={() => setPage('stocks')} />
          )}
          {page === 'portfolio' && <PortfolioPage />}
          {page === 'orders' && <OrdersPage />}
          {page === 'strategies' && <StrategiesPage symbol={symbol} />}
          {page === 'settings' && <SettingsPage />}
        </main>
        <StatusBar />
      </div>
    </div>
  );
}
