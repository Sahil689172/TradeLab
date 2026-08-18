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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
};
