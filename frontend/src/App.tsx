import { useState } from 'react';
import { Sidebar } from './components/layout/Sidebar';
import { TopBar } from './components/layout/TopBar';
import { StatusBar } from './components/layout/StatusBar';
import { DashboardPage } from './pages/DashboardPage';
import { DEFAULT_SYMBOL, type Timeframe } from './types/api';

export default function App() {
  const [symbol, setSymbol] = useState(DEFAULT_SYMBOL);
  const [timeframe, setTimeframe] = useState<Timeframe>('1D');
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  return (
    <div className="flex h-screen overflow-hidden bg-terminal-bg">
      <Sidebar active="dashboard" />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          symbol={symbol}
          lastRefresh={lastRefresh}
          onRefreshComplete={setLastRefresh}
        />
        <main className="flex-1 overflow-y-auto p-4">
          <DashboardPage
            symbol={symbol}
            timeframe={timeframe}
            onSymbolChange={setSymbol}
            onTimeframeChange={setTimeframe}
          />
        </main>
        <StatusBar />
      </div>
    </div>
  );
}
