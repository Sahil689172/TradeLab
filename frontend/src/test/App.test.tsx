import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import App from '../App';

vi.mock('../api/client', () => ({
  api: {
    getStock: vi.fn().mockRejectedValue(new Error('offline')),
    refreshMarketData: vi.fn(),
    getSystemStatus: vi.fn().mockRejectedValue(new Error('offline')),
    getPortfolio: vi.fn().mockRejectedValue(new Error('offline')),
    listStocks: vi.fn().mockRejectedValue(new Error('offline')),
    getOHLCV: vi.fn().mockRejectedValue(new Error('offline')),
    getStrategyAnalysis: vi.fn().mockRejectedValue(new Error('offline')),
    buyOrder: vi.fn(),
    sellOrder: vi.fn(),
  },
}));

function renderApp() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>,
  );
}

describe('App', () => {
  it('renders the trading terminal shell', () => {
    renderApp();
    expect(screen.getByText('Trading Terminal')).toBeInTheDocument();
    expect(screen.getByText('TradeLab')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /refresh data/i })).toBeInTheDocument();
  });

  it('shows default symbol RELIANCE', () => {
    renderApp();
    expect(screen.getByDisplayValue('RELIANCE')).toBeInTheDocument();
  });
});
