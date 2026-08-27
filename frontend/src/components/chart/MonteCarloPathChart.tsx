/**
 * MonteCarloPathChart
 *
 * Canvas chart for a Monte Carlo run, with three views:
 *
 *   fan          P10-P90 and P25-P75 percentile bands plus the median, drawn
 *                from the backend's `bands` payload
 *   distribution histogram of simulated final equity
 *   drawdown     histogram of each simulated path's worst drawdown
 *
 * Percentiles are NOT recomputed here.  The backend computes them across the
 * whole run (up to 100k simulations); the `samplePaths` prop carries only a
 * few dozen illustrative curves, so deriving percentiles from it in the browser
 * would silently report the sample's spread as if it were the run's.  Sample
 * paths are therefore drawn as texture only, behind the real bands, and only
 * when the viewer asks for them.
 *
 * When `bands` is absent (an older backend, or before the first batch lands)
 * the component falls back to percentiles over whatever paths it was given and
 * says so, rather than drawing something that looks authoritative.
 */

import { useEffect, useMemo, useRef } from 'react';
import type { MonteCarloBands } from '../../types/api';

export type MCChartView = 'fan' | 'distribution' | 'drawdown';

interface MonteCarloPathChartProps {
  /** Percentile fan computed server-side over every simulation */
  bands?: MonteCarloBands | null;
  /** Bounded illustrative equity paths; never the full run */
  samplePaths: number[][];
  initialCapital: number;
  currentPrice?: number | null;
  height?: number;
  view?: MCChartView;
  showSamplePaths?: boolean;
}

const PATH_ALPHA = 'rgba(148,163,184,0.13)';
const MEDIAN_COLOR = '#f59e0b';
const OUTER_FILL = 'rgba(245,158,11,0.09)';
const INNER_FILL = 'rgba(245,158,11,0.17)';
const BAND_EDGE = 'rgba(245,158,11,0.30)';
const REF_COLOR = '#38bdf8';
const AXIS_COLOR = '#475569';
const LABEL_COLOR = '#64748b';
const BAR_FILL = 'rgba(56,189,248,0.45)';
const BAR_EDGE = 'rgba(56,189,248,0.85)';
const LOSS_FILL = 'rgba(248,113,113,0.45)';

function fmt(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return v.toFixed(0);
}

/** Percentiles over sample paths — fallback only, when the backend sent none. */
function bandsFromPaths(paths: number[][]): MonteCarloBands | null {
  if (paths.length === 0 || paths[0].length === 0) return null;
  const steps = paths[0].length;
  const pick = (col: number[], q: number) =>
    col[Math.min(col.length - 1, Math.max(0, Math.floor(col.length * q)))];
  const out: MonteCarloBands = {
    steps: Array.from({ length: steps }, (_, i) => i),
    paths_used: paths.length,
    p10: [], p25: [], p50: [], p75: [], p90: [],
  };
  for (let s = 0; s < steps; s++) {
    const col = paths.map((p) => p[s]).sort((a, b) => a - b);
    out.p10.push(pick(col, 0.10));
    out.p25.push(pick(col, 0.25));
    out.p50.push(pick(col, 0.50));
    out.p75.push(pick(col, 0.75));
    out.p90.push(pick(col, 0.90));
  }
  return out;
}

function histogram(values: number[], bins: number): { edges: number[]; counts: number[] } {
  if (values.length === 0) return { edges: [], counts: [] };
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (hi === lo) hi = lo + 1;
  const width = (hi - lo) / bins;
  const counts = new Array<number>(bins).fill(0);
  for (const v of values) {
    const idx = Math.min(bins - 1, Math.max(0, Math.floor((v - lo) / width)));
    counts[idx] += 1;
  }
  const edges = Array.from({ length: bins + 1 }, (_, i) => lo + i * width);
  return { edges, counts };
}

export function MonteCarloPathChart({
  bands,
  samplePaths,
  initialCapital,
  currentPrice,
  height = 260,
  view = 'fan',
  showSamplePaths = false,
}: MonteCarloPathChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const effectiveBands = useMemo(
    () => (bands && bands.p50?.length ? bands : bandsFromPaths(samplePaths)),
    [bands, samplePaths],
  );
  const isFallback = !(bands && bands.p50?.length) && effectiveBands != null;

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const dpr = window.devicePixelRatio || 1;
    const W = container.clientWidth || 500;
    const H = height;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = `${W}px`;
    canvas.style.height = `${H}px`;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, W, H);

    const empty = (msg: string) => {
      ctx.fillStyle = LABEL_COLOR;
      ctx.font = '11px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(msg, W / 2, H / 2);
    };

    const PAD_L = 48;
    const PAD_R = 8;
    const PAD_T = 10;
    const PAD_B = 22;
    const CW = W - PAD_L - PAD_R;
    const CH = H - PAD_T - PAD_B;

    // ── histogram views ───────────────────────────────────────────────────
    if (view === 'distribution' || view === 'drawdown') {
      if (samplePaths.length === 0) {
        empty('Waiting for simulation data…');
        return;
      }
      const values =
        view === 'distribution'
          ? samplePaths.map((p) => p[p.length - 1])
          : samplePaths.map((p) => {
              let peak = -Infinity;
              let worst = 0;
              for (const v of p) {
                if (v > peak) peak = v;
                if (peak > 0) worst = Math.min(worst, v / peak - 1);
              }
              return worst * 100;
            });

      const bins = Math.min(28, Math.max(6, Math.floor(values.length / 2)));
      const { edges, counts } = histogram(values, bins);
      if (counts.length === 0) {
        empty('Not enough data');
        return;
      }
      const maxCount = Math.max(...counts);
      const barW = CW / counts.length;

      for (let i = 0; i < counts.length; i++) {
        const h = (counts[i] / maxCount) * CH;
        const x = PAD_L + i * barW;
        const y = PAD_T + CH - h;
        const negative =
          view === 'drawdown' || edges[i] < (currentPrice ?? initialCapital);
        ctx.fillStyle = negative && view === 'drawdown' ? LOSS_FILL : BAR_FILL;
        ctx.fillRect(x, y, Math.max(1, barW - 1), h);
        ctx.strokeStyle = BAR_EDGE;
        ctx.lineWidth = 0.5;
        ctx.strokeRect(x, y, Math.max(1, barW - 1), h);
      }

      ctx.font = '9px monospace';
      ctx.fillStyle = LABEL_COLOR;
      ctx.textAlign = 'center';
      const xTicks = Math.min(5, counts.length);
      for (let i = 0; i <= xTicks; i++) {
        const idx = Math.round((i / xTicks) * (edges.length - 1));
        const x = PAD_L + (idx / (edges.length - 1)) * CW;
        const label = view === 'drawdown' ? `${edges[idx].toFixed(1)}%` : fmt(edges[idx]);
        ctx.fillText(label, x, H - PAD_B + 13);
      }
      ctx.textAlign = 'left';
      ctx.fillText(
        view === 'drawdown'
          ? `worst drawdown per path (n=${values.length})`
          : `final equity per path (n=${values.length})`,
        PAD_L,
        PAD_T + 10,
      );
      return;
    }

    // ── percentile fan ────────────────────────────────────────────────────
    if (!effectiveBands) {
      empty('Waiting for simulation data…');
      return;
    }

    const { p10, p25, p50, p75, p90 } = effectiveBands;
    const steps = p50.length;
    if (steps === 0) {
      empty('Waiting for simulation data…');
      return;
    }

    let minV = Infinity;
    let maxV = -Infinity;
    for (const arr of [p10, p90]) {
      for (const v of arr) {
        if (v < minV) minV = v;
        if (v > maxV) maxV = v;
      }
    }
    if (showSamplePaths) {
      for (const p of samplePaths) {
        for (const v of p) {
          if (v < minV) minV = v;
          if (v > maxV) maxV = v;
        }
      }
    }
    const refVal = currentPrice != null && currentPrice > 0 ? currentPrice : initialCapital;
    minV = Math.min(minV, refVal) * 0.97;
    maxV = Math.max(maxV, refVal) * 1.03;
    const span = maxV - minV || 1;

    const xOf = (s: number) => (steps === 1 ? PAD_L : PAD_L + (s / (steps - 1)) * CW);
    const yOf = (v: number) => PAD_T + ((maxV - v) / span) * CH;

    const fillBetween = (lo: number[], hi: number[], color: string) => {
      ctx.beginPath();
      ctx.moveTo(xOf(0), yOf(lo[0]));
      for (let s = 1; s < steps; s++) ctx.lineTo(xOf(s), yOf(lo[s]));
      for (let s = steps - 1; s >= 0; s--) ctx.lineTo(xOf(s), yOf(hi[s]));
      ctx.closePath();
      ctx.fillStyle = color;
      ctx.fill();
    };

    // Sample paths sit behind the bands as texture, never as the message.
    if (showSamplePaths) {
      ctx.lineWidth = 0.7;
      ctx.strokeStyle = PATH_ALPHA;
      for (const path of samplePaths) {
        ctx.beginPath();
        ctx.moveTo(xOf(0), yOf(path[0]));
        for (let s = 1; s < path.length && s < steps; s++) ctx.lineTo(xOf(s), yOf(path[s]));
        ctx.stroke();
      }
    }

    fillBetween(p10, p90, OUTER_FILL);
    fillBetween(p25, p75, INNER_FILL);

    ctx.lineWidth = 0.8;
    ctx.strokeStyle = BAND_EDGE;
    for (const arr of [p10, p90]) {
      ctx.beginPath();
      ctx.moveTo(xOf(0), yOf(arr[0]));
      for (let s = 1; s < steps; s++) ctx.lineTo(xOf(s), yOf(arr[s]));
      ctx.stroke();
    }

    ctx.setLineDash([5, 4]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = REF_COLOR;
    ctx.beginPath();
    ctx.moveTo(PAD_L, yOf(refVal));
    ctx.lineTo(W - PAD_R, yOf(refVal));
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.lineWidth = 1.8;
    ctx.strokeStyle = MEDIAN_COLOR;
    ctx.beginPath();
    ctx.moveTo(xOf(0), yOf(p50[0]));
    for (let s = 1; s < steps; s++) ctx.lineTo(xOf(s), yOf(p50[s]));
    ctx.stroke();

    ctx.font = '9px monospace';
    ctx.textAlign = 'right';
    const ticks = 5;
    for (let i = 0; i <= ticks; i++) {
      const v = minV + (span * i) / ticks;
      const y = yOf(v);
      ctx.fillStyle = AXIS_COLOR;
      ctx.fillRect(PAD_L - 4, y, 4, 1);
      ctx.fillStyle = LABEL_COLOR;
      ctx.fillText(fmt(v), PAD_L - 6, y + 3);
    }

    ctx.textAlign = 'center';
    const xTicks = Math.min(steps, 5);
    for (let i = 0; i <= xTicks; i++) {
      const s = Math.round((i / xTicks) * (steps - 1));
      const x = xOf(s);
      ctx.fillStyle = AXIS_COLOR;
      ctx.fillRect(x, H - PAD_B, 1, 4);
      ctx.fillStyle = LABEL_COLOR;
      ctx.fillText(`T${s}`, x, H - PAD_B + 13);
    }

    ctx.textAlign = 'left';
    ctx.fillStyle = REF_COLOR;
    ctx.fillText(fmt(refVal), W - PAD_R - 40, yOf(refVal) - 3);
  }, [
    effectiveBands, samplePaths, initialCapital, currentPrice,
    height, view, showSamplePaths,
  ]);

  return (
    <div ref={containerRef} className="w-full">
      <canvas ref={canvasRef} style={{ display: 'block', width: '100%', height }} />
      {view === 'fan' && effectiveBands ? (
        <div className="mt-1 flex flex-wrap gap-x-3 text-[10px] font-mono text-slate-500">
          <span>
            <span className="text-amber-500">━</span> median (P50)
          </span>
          <span>P25–P75 · P10–P90 bands</span>
          {isFallback ? (
            <span className="text-amber-600">
              percentiles from {effectiveBands.paths_used} sample paths — not the full run
            </span>
          ) : (
            <span>across {effectiveBands.paths_used.toLocaleString()} simulated paths</span>
          )}
        </div>
      ) : null}
    </div>
  );
}
