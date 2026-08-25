import type {
  ApiResponse,
  OHLCVResponse,
  OrderRequest,
  OrderResponse,
  OrderRow,
  PortfolioResponse,
  RefreshStatus,
  StockListResponse,
  StockSummary,
  StrategyAnalysisResponse,
  StrategyCatalogItem,
  SystemStatus,
  MonteCarloRequest,
  MonteCarloDashboardResponse,
  FavoritesResponse,
} from '../types/api';

const BASE_URL = '/api/v1';

export class ApiClientError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = 'ApiClientError';
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, {
    headers: {
      Accept: 'application/json',
      ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
      ...init?.headers,
    },
    ...init,
  });

  const payload = (await response.json().catch(() => null)) as
    | ApiResponse<T>
    | { detail?: string; error?: { message?: string } }
    | null;

  if (!response.ok) {
    const message =
      (payload && 'error' in payload && payload.error?.message) ||
      (payload && 'detail' in payload && payload.detail) ||
      `Request failed (${response.status})`;
    throw new ApiClientError(String(message), response.status);
  }

  if (!payload || !('success' in payload) || !payload.success) {
    throw new ApiClientError('Unexpected API response', response.status);
  }

  return payload.data;
}

export const api = {
  listStocks(q = '', limit = 501) {
    const params = new URLSearchParams({ q, limit: String(limit) });
    return request<StockListResponse>(`/stocks?${params}`);
  },

  getStock(symbol: string) {
    return request<StockSummary>(`/stocks/${encodeURIComponent(symbol)}`);
  },

  getOHLCV(symbol: string, interval: string, limit = 20, before?: string) {
    const params = new URLSearchParams({ interval, limit: String(limit) });
    if (before) params.set('before', before);
    return request<OHLCVResponse>(
      `/stocks/${encodeURIComponent(symbol)}/ohlcv?${params}`,
    );
  },

  refreshMarketData(symbol?: string) {
    const params = symbol ? `?symbol=${encodeURIComponent(symbol)}` : '';
    return request<RefreshStatus>(`/market-data/refresh${params}`, {
      method: 'POST',
    });
  },

  listStrategies() {
    return request<StrategyCatalogItem[]>('/strategies');
  },

  getStrategyAnalysis(symbol: string, timeframe: string, includeMatrix = false) {
    const params = new URLSearchParams({ timeframe });
    if (includeMatrix) params.set('include_matrix', 'true');
    return request<StrategyAnalysisResponse>(
      `/strategies/${encodeURIComponent(symbol)}/analysis?${params}`,
    );
  },

  getPortfolio() {
    return request<PortfolioResponse>('/portfolio');
  },

  listOrders() {
    return request<OrderRow[]>('/orders');
  },

  buyOrder(body: OrderRequest) {
    return request<OrderResponse>('/orders/buy', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  sellOrder(body: OrderRequest) {
    return request<OrderResponse>('/orders/sell', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  getSystemStatus() {
    return request<SystemStatus>('/system/status');
  },

  runMonteCarlo(symbol: string, body: MonteCarloRequest) {
    return request<MonteCarloDashboardResponse>(
      `/stocks/${encodeURIComponent(symbol)}/monte-carlo`,
      { method: 'POST', body: JSON.stringify(body) },
    );
  },

  /**
   * Returns an AbortController you can call .abort() on to cancel,
   * and a run_id string extracted from the X-MC-Run-Id response header
   * (available after the first chunk arrives via the header callback).
   */
  streamMonteCarlo(
    symbol: string,
    body: MonteCarloRequest,
    onEvent: (event: string, data: unknown) => void,
    onRunId: (runId: string) => void,
    signal: AbortSignal,
  ): Promise<void> {
    return (async () => {
      const response = await fetch(`${BASE_URL}/stocks/${encodeURIComponent(symbol)}/monte-carlo/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(body),
        signal,
      });
      const runId = response.headers.get('X-MC-Run-Id') ?? '';
      if (runId) onRunId(runId);

      if (!response.ok || !response.body) {
        throw new ApiClientError(`Stream failed (${response.status})`, response.status);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        // SSE frames are separated by double newlines.
        const frames = buf.split('\n\n');
        buf = frames.pop() ?? '';

        for (const frame of frames) {
          if (!frame.trim()) continue;
          let eventName = 'message';
          let dataLine = '';
          for (const line of frame.split('\n')) {
            if (line.startsWith('event: ')) eventName = line.slice(7).trim();
            else if (line.startsWith('data: ')) dataLine = line.slice(6);
          }
          if (dataLine) {
            try {
              onEvent(eventName, JSON.parse(dataLine));
            } catch {
              // ignore malformed frames
            }
          }
        }
      }
    })();
  },

  cancelMonteCarlo(runId: string) {
    return request<{ run_id: string; cancelled: boolean }>(
      `/monte-carlo/${encodeURIComponent(runId)}/cancel`,
      { method: 'POST' },
    );
  },

  listFavorites() {
    return request<FavoritesResponse>('/favorites');
  },

  addFavorite(symbol: string) {
    return request<FavoritesResponse>(`/favorites/${encodeURIComponent(symbol)}`, {
      method: 'POST',
    });
  },

  removeFavorite(symbol: string) {
    return request<FavoritesResponse>(`/favorites/${encodeURIComponent(symbol)}`, {
      method: 'DELETE',
    });
  },
};
