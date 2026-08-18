import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api/client';
import { loadFavorites, saveFavorites } from '../utils/settings';

const FAVORITES_KEY = ['favorites'] as const;

export function useFavorites() {
  const queryClient = useQueryClient();

  const query = useQuery({
    queryKey: FAVORITES_KEY,
    queryFn: async () => {
      try {
        const remote = await api.listFavorites();
        const set = new Set(remote.symbols);
        saveFavorites(set);
        return set;
      } catch {
        return loadFavorites();
      }
    },
    staleTime: 30_000,
  });

  const addMutation = useMutation({
    mutationFn: (symbol: string) => api.addFavorite(symbol),
    onSuccess: (data) => {
      const set = new Set(data.symbols);
      saveFavorites(set);
      queryClient.setQueryData(FAVORITES_KEY, set);
    },
  });

  const removeMutation = useMutation({
    mutationFn: (symbol: string) => api.removeFavorite(symbol),
    onSuccess: (data) => {
      const set = new Set(data.symbols);
      saveFavorites(set);
      queryClient.setQueryData(FAVORITES_KEY, set);
    },
  });

  function toggleFavorite(symbol: string) {
    const current = query.data ?? loadFavorites();
    if (current.has(symbol)) removeMutation.mutate(symbol);
    else addMutation.mutate(symbol);
  }

  return {
    favorites: query.data ?? loadFavorites(),
    isLoading: query.isLoading,
    toggleFavorite,
  };
}
