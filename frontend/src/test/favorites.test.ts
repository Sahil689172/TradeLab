import { describe, expect, it, vi, beforeEach } from 'vitest';
import { loadFavorites, saveFavorites } from '../utils/settings';

vi.mock('../api/client', () => ({
  api: {
    listFavorites: vi.fn(),
    addFavorite: vi.fn(),
    removeFavorite: vi.fn(),
  },
}));

import { api } from '../api/client';

describe('favorites persistence', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetAllMocks();
  });

  it('deduplicates symbols in local storage', () => {
    saveFavorites(new Set(['RELIANCE', 'RELIANCE', 'TCS']));
    expect([...loadFavorites()].sort()).toEqual(['RELIANCE', 'TCS']);
  });

  it('syncs backend favorites into local storage', async () => {
    vi.mocked(api.listFavorites).mockResolvedValue({ symbols: ['INFY'] });
    const remote = await api.listFavorites();
    saveFavorites(new Set(remote.symbols));
    expect(loadFavorites().has('INFY')).toBe(true);
  });
});
