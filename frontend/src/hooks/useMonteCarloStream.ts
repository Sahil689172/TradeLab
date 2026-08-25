/**
 * useMonteCarloStream
 *
 * Connects to the SSE Monte Carlo endpoint, provides live progress and
 * sample paths, and exposes a cancel function.
 *
 * States:
 *   idle        → not started
 *   loading     → waiting for first byte (trade loading phase)
 *   running     → receiving progress events
 *   complete    → result event received
 *   cancelled   → user cancelled
 *   error       → backend error event or network failure
 */

import { useCallback, useRef, useState } from 'react';
import { api } from '../api/client';
import type {
  MonteCarloDashboardResponse,
  MonteCarloPartialStats,
  MonteCarloProgressEvent,
  MonteCarloRequest,
  MonteCarloStreamResult,
} from '../types/api';

export type MCStreamStatus = 'idle' | 'loading' | 'running' | 'complete' | 'cancelled' | 'error';

export interface MCStreamState {
  status: MCStreamStatus;
  /** Simulations completed so far */
  completed: number;
  /** Total simulations requested */
  total: number;
  /** Percentage complete 0–100 */
  pct: number;
  /** Seconds elapsed */
  elapsed: number;
  /** Partial statistics updated each batch */
  partialStats: MonteCarloPartialStats | null;
  /** Representative equity path arrays for chart rendering */
  samplePaths: number[][];
  /** Final complete result (populated on status === 'complete') */
  result: MonteCarloDashboardResponse | null;
  /** Error message */
  error: string | null;
}

const INITIAL_STATE: MCStreamState = {
  status: 'idle',
  completed: 0,
  total: 0,
  pct: 0,
  elapsed: 0,
  partialStats: null,
  samplePaths: [],
  result: null,
  error: null,
};

export function useMonteCarloStream() {
  const [state, setState] = useState<MCStreamState>(INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);
  const runIdRef = useRef<string>('');

  const start = useCallback(
    (symbol: string, request: MonteCarloRequest) => {
      // Cancel any in-flight stream before starting a new one.
      if (abortRef.current) {
        abortRef.current.abort();
      }

      const controller = new AbortController();
      abortRef.current = controller;
      runIdRef.current = '';

      setState({
        ...INITIAL_STATE,
        status: 'loading',
        total: request.simulations ?? 1_000,
      });

      function handleEvent(eventName: string, data: unknown) {
        if (eventName === 'progress') {
          const ev = data as MonteCarloProgressEvent;
          setState((prev) => ({
            ...prev,
            status: ev.status === 'complete' ? 'running' : 'running',
            completed: ev.completed,
            total: ev.total,
            pct: ev.pct,
            elapsed: ev.elapsed,
            partialStats: ev.partial_stats ?? prev.partialStats,
            // Replace sample paths every update so the chart grows.
            samplePaths: ev.sample_paths?.length ? ev.sample_paths : prev.samplePaths,
          }));
        } else if (eventName === 'result') {
          const res = data as MonteCarloStreamResult;
          setState((prev) => ({
            ...prev,
            status: 'complete',
            pct: 100,
            samplePaths: res._sample_paths?.length ? res._sample_paths : prev.samplePaths,
            elapsed: res._elapsed ?? prev.elapsed,
            result: res,
          }));
        } else if (eventName === 'error') {
          const msg = (data as { message?: string })?.message ?? 'Unknown error';
          if (msg === 'Cancelled') {
            setState((prev) => ({ ...prev, status: 'cancelled', error: 'Cancelled by user' }));
          } else {
            setState((prev) => ({ ...prev, status: 'error', error: msg }));
          }
        }
      }

      api
        .streamMonteCarlo(symbol, request, handleEvent, (id) => { runIdRef.current = id; }, controller.signal)
        .catch((err: Error) => {
          if (err.name === 'AbortError') {
            setState((prev) => ({
              ...prev,
              status: prev.status === 'cancelled' ? 'cancelled' : 'cancelled',
              error: 'Cancelled',
            }));
          } else {
            setState((prev) => ({ ...prev, status: 'error', error: err.message }));
          }
        });
    },
    [],
  );

  const cancel = useCallback(() => {
    setState((prev) => ({ ...prev, status: 'cancelled', error: 'Cancelled by user' }));
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    // Also tell the backend to stop.
    if (runIdRef.current) {
      api.cancelMonteCarlo(runIdRef.current).catch(() => undefined);
      runIdRef.current = '';
    }
  }, []);

  const reset = useCallback(() => {
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setState(INITIAL_STATE);
  }, []);

  return { state, start, cancel, reset };
}
