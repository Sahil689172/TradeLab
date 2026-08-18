import type { ReactElement } from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import { StocksPage } from '../pages/StocksPage';
import { StockDetailPage } from '../pages/StockDetailPage';
import { PortfolioPage } from '../pages/PortfolioPage';
import { OrdersPage } from '../pages/OrdersPage';
import { api } from '../api/client';
import type { OHLCVBar, OrderRow, StockSummary, StrategySignalRow } from '../types/api';

vi.mock('../api/client', () => ({
  api: {
    getStock: vi.fn(),
    refreshMarketData: vi.fn(),
    getSystemStatus: vi.fn(),
    getPortfolio: vi.fn(),
    listStocks: vi.fn(),
    getOHLCV: vi.fn(),
    getStrategyAnalysis: vi.fn(),
    listStrategies: vi.fn(),
    listOrders: vi.fn(),
    buyOrder: vi.fn(),
    sellOrder: vi.fn(),
    runMonteCarlo: vi.fn(),
    listFavorites: vi.fn(),
    addFavorite: vi.fn(),
    removeFavorite: vi.fn(),
  },
}));

function renderWithQuery(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

const stock: StockSummary = {
  symbol: 'RELIANCE',
  yahoo_symbol: 'RELIANCE.NS',
  company_name: 'Reliance Industries Ltd',
  sector: 'Energy',
  industry: 'Oil & Gas',
  last_price: 2500,
  daily_change_pct: 0.012,
  history_available: true,
  last_data_date: '2024-06-28T00:00:00',
  is_watchlist: false,
  is_favorite: false,
  is_holding: false,
};

function makeBars(count: number, start = '2024-01-01'): OHLCVBar[] {
  const origin = new Date(`${start}T00:00:00Z`);
  return Array.from({ length: count }, (_, index) => {
    const date = new Date(origin);
    date.setUTCDate(origin.getUTCDate() + index);
    const close = 100 + index;
    return {
      date: date.toISOString(),
      open: close,
      high: close + 1,
      low: close - 1,
      close,
      volume: 1000 + index,
      adj_close: close,
    };
  });
}

function strategyRow(name: string, index: number): StrategySignalRow {
  return {
    strategy: name,
    display_name: name,
    best_timeframe: '1D',
    signal: 'NEUTRAL',
    confidence: 40 + index,
    confidence_label: 'Historical/Model Confidence',
    strength: 'Weak',
    status: 'OK',
    sample_size: 20,
    evaluation_window: '2024-01-01 → 2024-01-20',
    last_evaluated: '2024-01-20T00:00:00Z',
    reasons: [],
    warnings: [],
    error: null,
    current_price: 2500,
    entry_price: 2500,
    stop_loss: 2400,
    target: 2600,
    recommended_action: 'HOLD',
  };
}

const twelveNames = [
  'ema_trend',
  'supertrend',
  'break_retest',
  'momentum',
  'donchian',
  'vwap',
  'opening_range_breakout',
  'cpr',
  'darvas_box',
  'previous_day_breakout',
  'volume_breakout',
  'relative_strength',
];

beforeEach(() => {
  vi.mocked(api.getStock).mockRejectedValue(new Error('offline'));
  vi.mocked(api.refreshMarketData).mockRejectedValue(new Error('offline'));
  vi.mocked(api.getSystemStatus).mockRejectedValue(new Error('offline'));
  vi.mocked(api.getPortfolio).mockRejectedValue(new Error('offline'));
  vi.mocked(api.listStocks).mockRejectedValue(new Error('offline'));
  vi.mocked(api.getOHLCV).mockRejectedValue(new Error('offline'));
  vi.mocked(api.getStrategyAnalysis).mockRejectedValue(new Error('offline'));
  vi.mocked(api.listStrategies).mockResolvedValue([]);
  vi.mocked(api.listOrders).mockResolvedValue([]);
  vi.mocked(api.buyOrder).mockRejectedValue(new Error('offline'));
  vi.mocked(api.sellOrder).mockRejectedValue(new Error('offline'));
  vi.mocked(api.runMonteCarlo).mockRejectedValue(new Error('offline'));
  vi.mocked(api.listFavorites).mockResolvedValue({ symbols: [] });
  vi.mocked(api.addFavorite).mockResolvedValue({ symbols: ['RELIANCE'] });
  vi.mocked(api.removeFavorite).mockResolvedValue({ symbols: [] });
});

describe('App shell and navigation', () => {
  it('renders the trading terminal shell', () => {
    renderWithQuery(<App />);
    expect(screen.getByText('Trading Terminal')).toBeInTheDocument();
    expect(screen.getByText('TradeLab')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /refresh data/i })).toBeInTheDocument();
  });

  it('shows default symbol RELIANCE', () => {
    renderWithQuery(<App />);
    expect(screen.getByDisplayValue('RELIANCE')).toBeInTheDocument();
  });

  it('navigates sidebar pages and keeps an active state', () => {
    renderWithQuery(<App />);
    fireEvent.click(screen.getByRole('button', { name: /stocks \/ market/i }));
    expect(screen.getByRole('heading', { name: 'Stocks / Market' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /stocks \/ market/i })).toHaveAttribute(
      'aria-current',
      'page',
    );

    fireEvent.click(screen.getByRole('button', { name: /portfolio/i }));
    expect(screen.getByRole('heading', { name: 'Portfolio' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /orders/i }));
    expect(screen.getByRole('heading', { name: 'Orders' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /strategies/i }));
    expect(screen.getByRole('heading', { name: 'Strategies' })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /settings/i }));
    expect(screen.getByRole('heading', { name: 'Settings' })).toBeInTheDocument();
  });
});

describe('Stocks page favorites', () => {
  it('shows empty favorites message and toggles star', async () => {
    vi.mocked(api.listStocks).mockResolvedValue({ total: 501, stocks: [stock] });
    vi.mocked(api.listFavorites).mockResolvedValue({ symbols: [] });
    vi.mocked(api.addFavorite).mockResolvedValue({ symbols: ['RELIANCE'] });
    renderWithQuery(<StocksPage onSelectSymbol={() => undefined} />);
    fireEvent.click(screen.getByRole('button', { name: /favorites/i }));
    expect(await screen.findByText('No favorite stocks yet.')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Add favorite' }));
    await waitFor(() => expect(api.addFavorite).toHaveBeenCalledWith('RELIANCE'));
  });
});

describe('Stocks page', () => {
  it('lists backend universe rows and opens detail on click', async () => {
    vi.mocked(api.listStocks).mockResolvedValue({ total: 501, stocks: [stock] });
    const onSelect = vi.fn();
    renderWithQuery(<StocksPage onSelectSymbol={onSelect} />);
    expect(await screen.findByText('Reliance Industries Ltd')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'RELIANCE' }));
    expect(onSelect).toHaveBeenCalledWith('RELIANCE');
  });
});

describe('Stock detail', () => {
  it('shows quote, 20-day history, strategies, and fetch-older without duplicate candles', async () => {
    const all = makeBars(40);
    vi.mocked(api.getStock).mockResolvedValue(stock);
    vi.mocked(api.getPortfolio).mockResolvedValue({
      kpis: {
        total_invested: 0,
        current_value: 1_000_000,
        unrealized_pnl: 0,
        realized_pnl: 0,
        available_cash: 1_000_000,
        todays_pnl: 0,
        initial_capital: 1_000_000,
        exposure_pct: 0,
        max_drawdown_pct: 0,
      },
      positions: [],
      per_symbol_pnl: {},
    });
    vi.mocked(api.getStrategyAnalysis).mockResolvedValue({
      symbol: 'RELIANCE',
      timeframe: '1D',
      generated_at: '2024-01-20T00:00:00Z',
      strategies: twelveNames.map(strategyRow),
      timeframe_matrix: [],
      assumption: {
        symbol: 'RELIANCE',
        timeframe: '1D',
        bias: 'NEUTRAL',
        confidence: null,
        confidence_label: 'Historical/Model Confidence',
        supporting_strategies: [],
        supporting_indicators: [],
        evaluation_window: '',
        sample_size: 20,
        last_updated: null,
        explanation: '',
      },
      data_note: 'Historical/Model Confidence',
    });
    vi.mocked(api.getOHLCV).mockImplementation(async (_symbol, _interval, limit = 20, before?: string) => {
      const window = before
        ? all.filter((bar) => bar.date < before).slice(-limit)
        : all.slice(-limit);
      return {
        symbol: 'RELIANCE',
        interval: '1D',
        interval_label: '1 Day',
        bars: window,
        source: 'local_parquet',
        delayed: true,
        last_bar_timestamp: window.at(-1)?.date ?? null,
        oldest_bar_timestamp: window[0]?.date ?? null,
        has_more: before ? window[0]?.date !== all[0]?.date : all.length > window.length,
        total_bars: all.length,
        message: '',
      };
    });

    renderWithQuery(<StockDetailPage symbol="RELIANCE" onBack={() => undefined} />);

    expect(await screen.findByText('Reliance Industries Ltd')).toBeInTheDocument();
    expect(await screen.findByText('latest 20 trading days', { exact: false })).toBeInTheDocument();
    expect(screen.getByText('12 strategies')).toBeInTheDocument();
    expect(screen.getByText('ema_trend')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /run monte carlo simulation/i })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /load more history/i }));
    await waitFor(() => expect(vi.mocked(api.getOHLCV).mock.calls.length).toBeGreaterThanOrEqual(2));
    const olderCall = vi.mocked(api.getOHLCV).mock.calls.find((call) => call[3]);
    expect(olderCall?.[3]).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByText(/extended to 40 days/i)).toBeInTheDocument(),
    );
  });
});

describe('Portfolio and orders pages', () => {
  it('renders portfolio KPIs from backend', async () => {
    vi.mocked(api.getPortfolio).mockResolvedValue({
      kpis: {
        total_invested: 10_000,
        current_value: 1_010_000,
        unrealized_pnl: 500,
        realized_pnl: 200,
        available_cash: 990_000,
        todays_pnl: 0,
        initial_capital: 1_000_000,
        exposure_pct: 1,
        max_drawdown_pct: 0,
      },
      positions: [
        {
          symbol: 'RELIANCE',
          quantity: 4,
          average_price: 2500,
          ltp: 2550,
          invested_value: 10_000,
          current_value: 10_200,
          pnl: 200,
          pnl_pct: 0.02,
          stop_loss: 2400,
          target: 2700,
          exposure_pct: 1,
          strategy_name: 'paper_manual',
        },
      ],
      per_symbol_pnl: { RELIANCE: 200 },
    });
    renderWithQuery(<PortfolioPage />);
    expect(await screen.findByText('Total capital')).toBeInTheDocument();
    expect(screen.getAllByText('RELIANCE').length).toBeGreaterThan(0);
  });

  it('renders paper orders with rejection reason', async () => {
    const order: OrderRow = {
      order_id: '1',
      timestamp: '2024-01-01T00:00:00Z',
      symbol: 'RELIANCE',
      side: 'BUY',
      quantity: 1,
      price: 2500,
      order_type: 'MARKET',
      status: 'REJECTED',
      rejection_reason: 'Insufficient cash',
      strategy_name: 'paper_manual',
      requested_price: 2500,
      execution_price: null,
      stop_loss: 2400,
      target: 2600,
    };
    vi.mocked(api.listOrders).mockResolvedValue([order]);
    renderWithQuery(<OrdersPage />);
    expect(await screen.findByText('Insufficient cash')).toBeInTheDocument();
    expect(screen.getByText('REJECTED')).toBeInTheDocument();
  });
});
