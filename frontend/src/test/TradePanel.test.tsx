import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, expect, it, vi } from 'vitest';
import { TradePanel } from '../components/dashboard/TradePanel';
import { api } from '../api/client';

vi.mock('../api/client', () => ({
  api: {
    getPortfolio: vi.fn().mockResolvedValue({
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
    }),
    buyOrder: vi.fn(),
    sellOrder: vi.fn(),
  },
}));

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <TradePanel symbol="RELIANCE" currentPrice={2500} signal="BUY" />
    </QueryClientProvider>,
  );
}

describe('TradePanel', () => {
  it('submits a paper BUY with stop loss and target through the backend client', async () => {
    vi.mocked(api.buyOrder).mockResolvedValue({
      accepted: true,
      status: 'FILLED',
      message: 'FILLED',
      order: null,
      portfolio: null,
    });
    renderPanel();
    fireEvent.change(screen.getByLabelText(/quantity/i), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText(/stop loss/i), { target: { value: '2400' } });
    fireEvent.change(screen.getByLabelText(/target/i), { target: { value: '2700' } });
    fireEvent.click(screen.getByRole('button', { name: /place buy order/i }));
    await waitFor(() => expect(api.buyOrder).toHaveBeenCalled());
    expect(api.buyOrder).toHaveBeenCalledWith({
      symbol: 'RELIANCE',
      quantity: 2,
      order_type: 'MARKET',
      price: 2500,
      stop_loss: 2400,
      target: 2700,
    });
    expect(await screen.findByText('FILLED')).toBeInTheDocument();
  });

  it('shows rejection reason from the paper broker', async () => {
    vi.mocked(api.buyOrder).mockResolvedValue({
      accepted: false,
      status: 'REJECTED',
      message: 'Stop loss must be below entry price for BUY',
      order: {
        order_id: 'x',
        timestamp: '2024-01-01T00:00:00Z',
        symbol: 'RELIANCE',
        side: 'BUY',
        quantity: 1,
        price: 2500,
        order_type: 'MARKET',
        status: 'REJECTED',
        rejection_reason: 'Stop loss must be below entry price for BUY',
        strategy_name: 'paper_manual',
        requested_price: 2500,
        execution_price: null,
        stop_loss: 2600,
        target: null,
      },
      portfolio: null,
    });
    renderPanel();
    fireEvent.change(screen.getByLabelText(/stop loss/i), { target: { value: '2600' } });
    fireEvent.click(screen.getByRole('button', { name: /place buy order/i }));
    expect(await screen.findByText(/stop loss must be below entry price/i)).toBeInTheDocument();
  });
});
