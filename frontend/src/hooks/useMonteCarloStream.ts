/**
 * useMonteCarloStream
 *
 * Connects to the SSE Monte Carlo endpoint, provides live progress and
 * sample paths, and exposes a cancel function.
 *
 * States:
 *   idle             → not started
 *   loading_trades   → SSE connection open, backend loading historical trades
 *   simulating       → trades loaded, simulation batches running
 *   complete         → result event received
 *   cancelled        → user cancelled (or backend sent "Cancelled" error)
 *   error            → backend error event or network failure
 *
 * The legacy 'loading' / 'running' aliases are preserved as type aliases so
 * callers that still pattern-match on them continue to work.
 *
 * IMPORTANT — abort vs cancel:
 *   cancel()      → user-initiated; shows "Cancelled by user" in the UI.
 *   abortStream() → internal only; silently aborts the fetch without changing
 *                   the displayed status.  Use this in useEffect cleanup so
 *                   that React StrictMode's mount→unmount→remount cycle and
 *                   ordinary component unmounts never show a false cancellation.
 */

import { useCallback, useRef, useState } from 'react';
import { api } from '../api/client';
import type {
  MonteCarloBands,
  MonteCarloDashboardResponse,
  MonteCarloPartialStats,
  MonteCarloProgressEvent,
  MonteCarloRequest,
  MonteCarloStartedEvent,
  MonteCarloStreamResult,
} from '../types/api';

/** The backend sends `{}` for bands until at least one batch has completed. */
function asBands(value: unknown): MonteCarloBands | null {
  const candidate = value as MonteCarloBands | undefined;
  return candidate && Array.isArray(candidate.p50) && candidate.p50.length > 0
    ? candidate
    : null;
}

export type MCStreamStatus =
  | 'idle'
  | 'loading_trades'   // SSE open, historical replay running
  | 'simulating'       // trades loaded, MC batches in flight
  | 'complete'
  | 'cancelled'
  | 'error'
  // Legacy aliases kept for backward-compat with callers
  | 'loading'          // = loading_trades
  | 'running';         // = simulating

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
  /** Backend-estimated seconds remaining; null until throughput is known */
  etaSeconds: number | null;
  /** Human-readable status message from the backend */
  statusMessage: string;
  /** Number of historical trades loaded (available after loading_trades phase) */
  tradeCount: number | null;
  /** Partial statistics updated each batch */
  partialStats: MonteCarloPartialStats | null;
  /** Percentile fan over the whole run — the primary chart input */
  bands: MonteCarloBands | null;
  /** A small bounded set of illustrative equity paths (not the full run) */
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
  etaSeconds: null,
  statusMessage: '',
  tradeCount: null,
  partialStats: null,
  bands: null,
  samplePaths: [],
  result: null,
  error: null,
};

export function useMonteCarloStream() {
  const [state, setState] = useState<MCStreamState>(INITIAL_STATE);
  const abortRef = useRef<AbortController | null>(null);
  const runIdRef = useRef<string>('');
  // Set to true ONLY when the user explicitly clicks Cancel.
  // Never set from effect cleanup / component unmount.
  const userCancelledRef = useRef(false);

  const start = useCallback(
    (symbol: string, request: MonteCarloRequest) => {
      // Cancel any in-flight stream before starting a new one.
      if (abortRef.current) {
        abortRef.current.abort();
      }

      userCancelledRef.current = false;
      const controller = new AbortController();
      abortRef.current = controller;
      runIdRef.current = '';

      setState({
        ...INITIAL_STATE,
        status: 'loading_trades',
        statusMessage: 'Connecting to simulation service…',
        total: request.simulations ?? 1_000,
      });

      function handleEvent(eventName: string, data: unknown) {
        if (eventName === 'started') {
          const ev = data as MonteCarloStartedEvent;
          const nextStatus: MCStreamStatus =
            ev.status === 'simulating' ? 'simulating' : 'loading_trades';
          setState((prev) => ({
            ...prev,
            status: nextStatus,
            statusMessage: ev.message,
            total: ev.total ?? prev.total,
            tradeCount: ev.trade_count ?? prev.tradeCount,
            elapsed: ev.elapsed ?? prev.elapsed,
          }));
        } else if (eventName === 'progress') {
          const ev = data as MonteCarloProgressEvent;
          setState((prev) => ({
            ...prev,
            status: 'simulating',
            statusMessage: `Simulating… ${ev.completed.toLocaleString()} / ${ev.total.toLocaleString()}`,
            completed: ev.completed,
            total: ev.total,
            pct: ev.pct,
            elapsed: ev.elapsed,
            etaSeconds: ev.eta_seconds ?? prev.etaSeconds,
            partialStats: ev.partial_stats ?? prev.partialStats,
            bands: asBands(ev.bands) ?? prev.bands,
            samplePaths: ev.sample_paths?.length ? ev.sample_paths : prev.samplePaths,
          }));
        } else if (eventName === 'result') {
          const res = data as MonteCarloStreamResult;
          setState((prev) => ({
            ...prev,
            status: 'complete',
            statusMessage: res.available ? 'Simulation complete' : res.message,
            // Pin completed/total to the authoritative simulation count from
            // the result.  When available=true the final progress event already
            // set these correctly, but we set them here too so the display is
            // correct even if the final progress event was dropped.
            completed: res.available ? (res.simulation_count || prev.completed) : prev.completed,
            total:     res.available ? (res.simulation_count || prev.total)     : prev.total,
            pct: res.available ? 100 : prev.pct,
            etaSeconds: 0,
            bands: asBands(res._bands) ?? prev.bands,
            samplePaths: res._sample_paths?.length ? res._sample_paths : prev.samplePaths,
            elapsed: res._elapsed ?? prev.elapsed,
            result: res,
          }));
        } else if (eventName === 'error') {
          const msg = (data as { message?: string })?.message ?? 'Unknown error';
          if (msg === 'Cancelled') {
            setState((prev) => ({
              ...prev,
              status: 'cancelled',
              statusMessage: 'Cancelled',
              error: 'Cancelled by user',
            }));
          } else {
            setState((prev) => ({
              ...prev,
              status: 'error',
              statusMessage: `Error: ${msg}`,
              error: msg,
            }));
          }
        }
      }

      api
        .streamMonteCarlo(symbol, request, handleEvent, (id) => { runIdRef.current = id; }, controller.signal)
        .catch((err: Error) => {
          if (err.name === 'AbortError') {
            // AbortError fires on both user-cancel and silent abortStream().
            // Only transition to 'cancelled' when the user explicitly triggered it.
            if (userCancelledRef.current) {
              setState((prev) => ({
                ...prev,
                status: 'cancelled',
                statusMessage: 'Cancelled',
                error: 'Cancelled by user',
              }));
            }
            // Otherwise (unmount / StrictMode cleanup / abortStream) — leave
            // the state exactly as-is so the UI does not flash to "Cancelled".
            return;
          }
          setState((prev) => ({
            ...prev,
            status: 'error',
            statusMessage: `Connection error: ${err.message}`,
            error: err.message,
          }));
        });
    },
    [],
  );

  const cancel = useCallback(() => {
    userCancelledRef.current = true;
    setState((prev) => ({
      ...prev,
      status: 'cancelled',
      statusMessage: 'Cancelled',
      error: 'Cancelled by user',
    }));
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

  /**
   * Silently abort the in-flight fetch WITHOUT marking the run as cancelled.
   *
   * Use this in useEffect cleanup / component unmount so React StrictMode's
   * mount→unmount→remount cycle never shows a false "Cancelled by user".
   *
   * DO NOT call cancel() from cleanup — cancel() sets userCancelledRef which
   * causes the AbortError handler to show "Cancelled by user" on the remount.
   */
  const abortStream = useCallback(() => {
    // userCancelledRef intentionally NOT set here.
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    // No backend cancel signal — the backend will complete or time out on its
    // own.  The client simply disconnects.
  }, []);

  const reset = useCallback(() => {
    userCancelledRef.current = false;
    if (abortRef.current) {
      abortRef.current.abort();
      abortRef.current = null;
    }
    setState(INITIAL_STATE);
  }, []);

  return { state, start, cancel, abortStream, reset };
}
