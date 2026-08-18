import { useEffect, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api/client';
import { formatCurrency } from '../../utils/format';
import type { DashboardSignal, StrategySignalRow } from '../../types/api';

interface TradePanelProps {
  symbol: string;
  currentPrice: number | null;
  signal?: DashboardSignal;
  strategyRow?: StrategySignalRow | null;
}

export function TradePanel({ symbol, currentPrice, signal, strategyRow }: TradePanelProps) {
  const queryClient = useQueryClient();
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY');
  const [quantity, setQuantity] = useState('1');
  const [orderType, setOrderType] = useState('MARKET');
  const [price, setPrice] = useState('');
  const [stopLoss, setStopLoss] = useState('');
  const [target, setTarget] = useState('');
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!strategyRow) return;
    if (strategyRow.stop_loss != null) setStopLoss(String(strategyRow.stop_loss));
    if (strategyRow.target != null) setTarget(String(strategyRow.target));
    if (strategyRow.entry_price != null) setPrice(String(strategyRow.entry_price));
    if (strategyRow.signal === 'SELL') setSide('SELL');
    else if (strategyRow.signal === 'BUY') setSide('BUY');
  }, [strategyRow]);

  const portfolio = useQuery({
    queryKey: ['portfolio'],
    queryFn: () => api.getPortfolio(),
  });

  const qty = parseFloat(quantity);
  const px = price ? parseFloat(price) : currentPrice;
  const estimated = qty > 0 && px ? qty * px : null;
  const cash = portfolio.data?.kpis.available_cash ?? null;
  const exposure = portfolio.data?.kpis.exposure_pct ?? null;
  const displaySignal = strategyRow?.signal ?? signal;

  const mutation = useMutation({
    mutationFn: () => {
      const body = {
        symbol,
        quantity: qty,
        order_type: orderType,
        price: price ? parseFloat(price) : currentPrice,
        stop_loss: stopLoss ? parseFloat(stopLoss) : null,
        target: target ? parseFloat(target) : null,
      };
      return side === 'BUY' ? api.buyOrder(body) : api.sellOrder(body);
    },
    onSuccess: (data) => {
      if (data.accepted) {
        setMessage(data.message);
        setError(null);
      } else {
        setError(data.message || data.order?.rejection_reason || 'Rejected');
        setMessage(null);
      }
      void queryClient.invalidateQueries({ queryKey: ['portfolio'] });
      void queryClient.invalidateQueries({ queryKey: ['orders'] });
    },
    onError: (err: Error) => {
      setError(err.message);
      setMessage(null);
    },
  });

  const qtyValid = !Number.isNaN(qty) && qty > 0;
  const priceReady = px != null && px > 0;

  return (
    <div className="panel">
      <div className="panel-header">
        <span className="panel-title">Paper Trade</span>
        <span className="text-[10px] uppercase text-slate-500">Simulated only</span>
      </div>
      <div className="space-y-3 p-3">
        <p className="font-mono text-sm text-slate-200">
          Current Price:{' '}
          <span className="text-terminal-accent">
            {currentPrice != null ? formatCurrency(currentPrice) : 'unavailable'}
          </span>
        </p>

        <div className="grid grid-cols-2 gap-2">
          <button
            type="button"
            className={side === 'BUY' ? 'btn-buy' : 'rounded border border-terminal-border py-1.5 text-sm text-slate-400'}
            onClick={() => setSide('BUY')}
          >
            BUY
          </button>
          <button
            type="button"
            className={side === 'SELL' ? 'btn-sell' : 'rounded border border-terminal-border py-1.5 text-sm text-slate-400'}
            onClick={() => setSide('SELL')}
          >
            SELL
          </button>
        </div>

        <label className="block text-xs text-slate-500" htmlFor="trade-qty">
          Quantity
          <input id="trade-qty" className="input-field mt-1 font-mono" type="number" min="1" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </label>
        <label className="block text-xs text-slate-500" htmlFor="trade-type">
          Order type
          <select id="trade-type" className="input-field mt-1" value={orderType} onChange={(e) => setOrderType(e.target.value)}>
            <option value="MARKET">MARKET</option>
            <option value="LIMIT">LIMIT (paper fill at requested price)</option>
          </select>
        </label>
        <label className="block text-xs text-slate-500" htmlFor="trade-price">
          Price (optional override)
          <input id="trade-price" className="input-field mt-1 font-mono" type="number" value={price} onChange={(e) => setPrice(e.target.value)} placeholder={currentPrice?.toString() ?? ''} />
        </label>
        <label className="block text-xs text-slate-500" htmlFor="trade-sl">
          Stop loss
          <input id="trade-sl" className="input-field mt-1 font-mono" type="number" value={stopLoss} onChange={(e) => setStopLoss(e.target.value)} />
        </label>
        <label className="block text-xs text-slate-500" htmlFor="trade-target">
          Target
          <input id="trade-target" className="input-field mt-1 font-mono" type="number" value={target} onChange={(e) => setTarget(e.target.value)} />
        </label>

        <div className="space-y-1 text-xs text-slate-400">
          <p>Estimated investment: {formatCurrency(estimated)}</p>
          <p>Available cash: {formatCurrency(cash)}</p>
          <p>Exposure: {exposure != null ? `${exposure.toFixed(2)}%` : '—'}</p>
          <p>
            Risk (qty × |price − stop|):{' '}
            {qtyValid && px && stopLoss
              ? formatCurrency(qty * Math.abs(px - parseFloat(stopLoss)))
              : '—'}
          </p>
          <p>
            Strategy signal:{' '}
            <span className={displaySignal === 'BUY' ? 'signal-buy' : displaySignal === 'SELL' ? 'signal-sell' : 'signal-neutral'}>
              {displaySignal ?? '—'}
            </span>
          </p>
        </div>

        <button
          type="button"
          className={side === 'BUY' ? 'btn-buy w-full' : 'btn-sell w-full'}
          disabled={!qtyValid || !priceReady || mutation.isPending}
          onClick={() => mutation.mutate()}
        >
          {mutation.isPending ? 'Submitting…' : side === 'BUY' ? 'Place Buy Order' : 'Place Sell Order'}
        </button>

        {message && <p className="rounded bg-terminal-buy/10 px-2 py-1 text-xs text-terminal-buy">{message}</p>}
        {error && <p className="rounded bg-terminal-sell/10 px-2 py-1 text-xs text-terminal-sell">{error}</p>}
      </div>
    </div>
  );
}
