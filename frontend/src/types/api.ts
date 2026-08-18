export type DashboardSignal = 'BUY' | 'SELL' | 'NEUTRAL';
export type AssumptionBias = 'BULLISH' | 'BEARISH' | 'NEUTRAL';
export type OrderSide = 'BUY' | 'SELL';
export type OrderStatus = 'FILLED' | 'REJECTED' | 'PENDING';

export interface ApiResponse<T> {
  success: boolean;
  data: T;
  message?: string | null;
}

export interface ApiError {
  success: false;
  error?: {
    code: string;
    message: string;
    details?: unknown;
  };
}

export interface StockSummary {
  symbol: string;
  yahoo_symbol: string;
  company_name: string;
  sector: string | null;
  industry: string | null;
  last_price: number | null;
  daily_change_pct: number | null;
  history_available: boolean;
  last_data_date: string | null;
  is_watchlist: boolean;
  is_favorite: boolean;
  is_holding: boolean;
}

export interface StockListResponse {
  total: number;
  stocks: StockSummary[];
}

export interface OHLCVBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  adj_close: number | null;
}

export interface OHLCVResponse {
  symbol: string;
  interval: string;
  interval_label: string;
  bars: OHLCVBar[];
  source: string;
  delayed: boolean;
  last_bar_timestamp: string | null;
  oldest_bar_timestamp: string | null;
  has_more: boolean;
  total_bars: number;
  message: string;
}

export interface StrategyCatalogItem {
  name: string;
  display_name: string;
  description: string;
  supported_timeframes: string[];
}

export interface StrategySignalRow {
  strategy: string;
  display_name: string;
  best_timeframe: string;
  signal: DashboardSignal;
  confidence: number;
  confidence_label: string;
  strength: string;
  status: string;
  sample_size: number;
  evaluation_window: string;
  last_evaluated: string | null;
  reasons: string[];
  warnings: string[];
  error: string | null;
  current_price: number | null;
  entry_price: number | null;
  stop_loss: number | null;
  target: number | null;
  recommended_action: string;
}

export interface TimeframeBestStrategy {
  interval: string;
  interval_label: string;
  supported: boolean;
  best_strategy: string | null;
  best_strategy_display: string | null;
  signal: DashboardSignal | null;
  confidence: number | null;
  confidence_label: string;
  supporting_metric: string;
  sample_size: number;
  last_evaluated: string | null;
  evaluation_window: string;
  message: string;
}

export interface CurrentAssumption {
  symbol: string;
  timeframe: string;
  bias: AssumptionBias;
  confidence: number | null;
  confidence_label: string;
  supporting_strategies: string[];
  supporting_indicators: string[];
  evaluation_window: string;
  sample_size: number;
  last_updated: string | null;
  explanation: string;
}

export interface StrategyAnalysisResponse {
  symbol: string;
  timeframe: string;
  generated_at: string;
  strategies: StrategySignalRow[];
  timeframe_matrix: TimeframeBestStrategy[];
  assumption: CurrentAssumption;
  data_note: string;
}

export interface PortfolioKPIs {
  total_invested: number;
  current_value: number;
  unrealized_pnl: number;
  realized_pnl: number;
  available_cash: number;
  todays_pnl: number;
  initial_capital: number;
  exposure_pct: number;
  max_drawdown_pct: number;
}

export interface PositionRow {
  symbol: string;
  quantity: number;
  average_price: number;
  ltp: number | null;
  invested_value: number;
  current_value: number;
  pnl: number;
  pnl_pct: number;
  stop_loss: number | null;
  target: number | null;
  exposure_pct: number;
  strategy_name: string;
}

export interface PortfolioResponse {
  kpis: PortfolioKPIs;
  positions: PositionRow[];
  per_symbol_pnl: Record<string, number>;
}

export interface OrderRow {
  order_id: string;
  timestamp: string;
  symbol: string;
  side: OrderSide;
  quantity: number;
  price: number;
  order_type: string;
  status: OrderStatus;
  rejection_reason: string | null;
  strategy_name: string;
  requested_price: number | null;
  execution_price: number | null;
  stop_loss: number | null;
  target: number | null;
}

export interface OrderRequest {
  symbol: string;
  quantity: number;
  order_type?: string;
  price?: number | null;
  stop_loss?: number | null;
  target?: number | null;
}

export interface OrderResponse {
  accepted: boolean;
  status: OrderStatus;
  message: string;
  order: OrderRow | null;
  portfolio: PortfolioKPIs | null;
}

export interface RefreshStatus {
  success: boolean;
  in_progress: boolean;
  message: string;
  last_refresh: string | null;
  symbols_updated: number;
  symbols_failed: number;
}

export interface SystemStatus {
  backend_connected: boolean;
  market_data_source: string;
  yfinance_status: string;
  universe_size: number;
  paper_trading: boolean;
  last_refresh: string | null;
  environment: string;
}

export const TIMEFRAMES = ['1m', '5m', '15m', '1h', '1D', '1W', '1M'] as const;
export type Timeframe = (typeof TIMEFRAMES)[number];

export const DEFAULT_SYMBOL = 'RELIANCE';

export interface PercentileBand {
  p05: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
}

export interface NextDayOutlook {
  supported: boolean;
  disclaimer: string;
  message: string;
  expected_return_pct: number | null;
  return_range_low_pct: number | null;
  return_range_high_pct: number | null;
  probability_of_loss: number | null;
  confidence_label: string;
  simulation_count: number;
  historical_sample_count: number;
  timeframe: string;
  trade_source: string;
  symbol: string;
  strategy: string;
}

export interface HorizonOutlook {
  trading_days: number;
  label: string;
  supported: boolean;
  message: string;
  mean_price: number | null;
  median_price: number | null;
  lower_price: number | null;
  upper_price: number | null;
  expected_return_pct: number | null;
  lower_return_pct: number | null;
  upper_return_pct: number | null;
  probability_negative_return: number | null;
  method: string;
  disclaimer: string;
}

export interface FavoritesResponse {
  symbols: string[];
}

export interface MonteCarloRequest {
  strategy: string;
  simulations?: number;
  random_seed?: number;
  initial_capital?: number;
  timeframe?: string;
  horizons?: number[];
}

export interface MonteCarloDashboardResponse {
  symbol: string;
  strategy: string;
  trade_source: string;
  historical_oos_trade_count: number;
  simulation_count: number;
  available: boolean;
  message: string;
  sample_quality: string;
  verdict: string;
  probability_of_loss: number | null;
  probability_of_profit: number | null;
  probability_of_ruin: number | null;
  median_return_pct: number | null;
  return_percentiles: PercentileBand | null;
  max_drawdown_percentiles: PercentileBand | null;
  final_capital_percentiles: PercentileBand | null;
  historical_return_pct: number | null;
  historical_trades: number;
  historical_win_rate: number | null;
  period: string;
  timeframe: string;
  next_day_outlook: NextDayOutlook | null;
  current_price: number | null;
  historical_daily_return_count: number;
  horizon_outlook: HorizonOutlook[];
  horizon_disclaimer: string;
  warnings: string[];
  resampling_limitation: string;
}
