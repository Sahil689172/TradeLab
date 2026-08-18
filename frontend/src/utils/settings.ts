export type AppPage =
  | 'dashboard'
  | 'stocks'
  | 'stock-detail'
  | 'portfolio'
  | 'orders'
  | 'strategies'
  | 'settings';

const KEY = 'tradelab.ui-settings';

export interface UiSettings {
  defaultSymbol: string;
  defaultTimeframe: '1D';
  theme: 'dark';
  paperTrading: true;
  autoRefreshSeconds: number;
}

export function loadUiSettings(): UiSettings {
  const fallback: UiSettings = {
    defaultSymbol: 'RELIANCE',
    defaultTimeframe: '1D',
    theme: 'dark',
    paperTrading: true,
    autoRefreshSeconds: 0,
  };
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return fallback;
    return { ...fallback, ...JSON.parse(raw) };
  } catch {
    return fallback;
  }
}

export function saveUiSettings(settings: UiSettings): void {
  localStorage.setItem(KEY, JSON.stringify(settings));
}

const FAV_KEY = 'tradelab.favorites';
const WATCH_KEY = 'tradelab.watchlist';

export function loadSet(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(key);
    return new Set(raw ? (JSON.parse(raw) as string[]) : []);
  } catch {
    return new Set();
  }
}

export function saveSet(key: string, values: Set<string>): void {
  localStorage.setItem(key, JSON.stringify([...values]));
}

export function loadFavorites(): Set<string> {
  return loadSet(FAV_KEY);
}

export function saveFavorites(values: Set<string>): void {
  saveSet(FAV_KEY, values);
}

export function loadWatchlist(): Set<string> {
  return loadSet(WATCH_KEY);
}

export function saveWatchlist(values: Set<string>): void {
  saveSet(WATCH_KEY, values);
}
