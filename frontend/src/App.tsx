import { useState } from 'react';
import { Route, Routes, useLocation, useNavigate } from 'react-router-dom';
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
import { RoomsPage } from './pages/RoomsPage';
import { RoomPage } from './pages/RoomPage';
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

/**
 * The terminal pages predate routing and drive themselves from local state.
 * They stay that way; only /rooms is routed, so a room has a shareable URL —
 * which is the whole point of opening the same room in two tabs.
 */
function TerminalPages() {
  const [page, setPage] = useState<AppPage>('dashboard');
  const [symbol, setSymbol] = useState(() => loadUiSettings().defaultSymbol || DEFAULT_SYMBOL);
  const [timeframe, setTimeframe] = useState<Timeframe>('1D');
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const navigate = useNavigate();

  function openStock(next: string) {
    setSymbol(next);
    setPage('stock-detail');
  }

  return (
    <>
      <Sidebar
        active={page}
        onNavigate={(id) => {
          if (id === 'rooms') {
            navigate('/rooms');
            return;
          }
          setPage(id as AppPage);
        }}
      />
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
    </>
  );
}

function RoomsShell({
  handle,
  onHandleChange,
}: {
  handle: string;
  onHandleChange: (next: string) => void;
}) {
  const navigate = useNavigate();
  const location = useLocation();
  const inRoom = location.pathname !== '/rooms';
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);
  const roomSymbol = loadUiSettings().defaultSymbol || DEFAULT_SYMBOL;

  return (
    <>
      <Sidebar active="rooms" onNavigate={(id) => navigate(id === 'rooms' ? '/rooms' : '/')} />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          title={inRoom ? 'Room' : 'Rooms'}
          symbol={roomSymbol}
          lastRefresh={lastRefresh}
          onRefreshComplete={setLastRefresh}
        />
        <main className="flex min-h-0 flex-1 flex-col overflow-y-auto p-4" data-page="rooms">
          <Routes>
            <Route
              path="/"
              element={<RoomsPage handle={handle} onHandleChange={onHandleChange} />}
            />
            <Route path=":roomId" element={<RoomPage handle={handle} />} />
          </Routes>
        </main>
        <StatusBar />
      </div>
    </>
  );
}

export default function App() {
  // Held in React state, not storage, so two tabs can be two different
  // people on one machine — which is how the room demo is meant to be run.
  const [handle, setHandle] = useState('');

  return (
    <div className="flex h-screen overflow-hidden bg-terminal-bg">
      <Routes>
        <Route
          path="/rooms/*"
          element={<RoomsShell handle={handle} onHandleChange={setHandle} />}
        />
        <Route path="*" element={<TerminalPages />} />
      </Routes>
    </div>
  );
}
