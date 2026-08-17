import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';

interface QuickTradeProps {
  symbol: string;
}

export function QuickTrade({ symbol }: QuickTradeProps) {
  const queryClient = useQueryClient();
  const [quantity, setQuantity] = useState('1');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const buyMutation = useMutation({
    mutationFn: () =>
      api.buyOrder({
        symbol,
        quantity: parseFloat(quantity),
        order_type: 'MARKET',
      }),
    onSuccess: (data) => {
      setMessage(data.message);
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      void queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (err: Error) => {
      setError(err.message);
      setMessage(null);
    },
  });

  const sellMutation = useMutation({
    mutationFn: () =>
      api.sellOrder({
        symbol,
        quantity: parseFloat(quantity),
        order_type: 'MARKET',
      }),
    onSuccess: (data) => {
      setMessage(data.message);
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      void queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (err: Error) => {
      setError(err.message);
      setMessage(null);
    },
  });

  const qty = parseFloat(quantity);
  const qtyValid = !Number.isNaN(qty) && qty > 0;
  const pending = buyMutation.isPending || sellMutation.isPending;

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Quick Trade</span>
        <span className="text-[10px] uppercase text-slate-500">Paper</span>
      </div>
      <div className="space-y-3 p-3">
        <div>
          <label htmlFor="qty" className="mb-1 block text-xs text-slate-500">
            Quantity
          </label>
          <input
            id="qty"
            type="number"
            min="1"
            step="1"
            className="input-field font-mono"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            className="btn-buy"
            disabled={!qtyValid || pending}
            onClick={() => buyMutation.mutate()}
          >
            {buyMutation.isPending ? 'Buying…' : 'Buy'}
          </button>
          <button
            type="button"
            className="btn-sell"
            disabled={!qtyValid || pending}
            onClick={() => sellMutation.mutate()}
          >
            {sellMutation.isPending ? 'Selling…' : 'Sell'}
          </button>
        </div>

        <p className="font-mono text-xs text-slate-500">
          Market order · {symbol}
        </p>

        {message && (
          <p className="rounded bg-terminal-buy/10 px-2 py-1 text-xs text-terminal-buy">
            {message}
          </p>
        )}
        {error && (
          <p className="rounded bg-terminal-sell/10 px-2 py-1 text-xs text-terminal-sell">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
