/**
 * MonteCarloPathChart
 *
 * Renders up to 150 simulated equity paths on an HTML canvas for performance.
 * Draws:
 *   - individual faint paths (grey)
 *   - P10/P90 shaded band (amber)
 *   - median path (amber solid)
 *   - reference dashed line at initialCapital / currentPrice (sky blue)
 *   - axis labels
 *
 * Paths update incrementally as the `paths` prop changes.
 */

import { useEffect, useRef } from 'react';

interface MonteCarloPathChartProps {
  paths: number[][];
  initialCapital: number;
  currentPrice?: number | null;
  height?: number;
}

const PATH_ALPHA = 'rgba(148,163,184,0.15)';
const MEDIAN_COLOR = '#f59e0b';
const BAND_FILL = 'rgba(245,158,11,0.10)';
const BAND_EDGE = 'rgba(245,158,11,0.30)';
const REF_COLOR = '#38bdf8';
const AXIS_COLOR = '#475569';
const LABEL_COLOR = '#64748b';

function fmt(v: number): string {
  if (Math.abs(v) >= 1_000_000) return `${(v / 1_000_000).toFixed(1)}M`;
  if (Math.abs(v) >= 1_000) return `${(v / 1_000).toFixed(0)}K`;
  return v.toFixed(0);
}

export function MonteCarloPathChart({
  paths,
  initialCapital,
  currentPrice,
  height = 260,
}: MonteCarloPathChartProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    // Match canvas pixel size to container for crisp rendering.
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

    if (paths.length === 0 || paths[0].length === 0) {
      ctx.fillStyle = LABEL_COLOR;
      ctx.font = '11px monospace';
      ctx.textAlign = 'center';
      ctx.fillText('Waiting for simulation data…', W / 2, H / 2);
      return;
    }

    const steps = paths[0].length;

    // Value range.
    let minV = Infinity;
    let maxV = -Infinity;
    for (const p of paths) {
      for (const v of p) {
        if (v < minV) minV = v;
        if (v > maxV) maxV = v;
      }
    }
    const refVal = (currentPrice != null && currentPrice > 0) ? currentPrice : initialCapital;
    minV = Math.min(minV, refVal) * 0.97;
    maxV = Math.max(maxV, refVal) * 1.03;
    const span = maxV - minV || 1;

    const PAD_L = 48;
    const PAD_R = 8;
    const PAD_T = 10;
    const PAD_B = 20;
    const CW = W - PAD_L - PAD_R;
    const CH = H - PAD_T - PAD_B;

    const xOf = (s: number) => PAD_L + (s / (steps - 1)) * CW;
    const yOf = (v: number) => PAD_T + ((maxV - v) / span) * CH;

    // ── P10/P90 band + median ─────────────────────────────────────────────
    const nPaths = paths.length;
    const p10s: number[] = [];
    const p90s: number[] = [];
    const meds: number[] = [];

    for (let s = 0; s < steps; s++) {
      const col = paths.map((p) => p[s]).sort((a, b) => a - b);
      const lo = col[Math.max(0, Math.floor(nPaths * 0.1))];
      const hi = col[Math.min(nPaths - 1, Math.floor(nPaths * 0.9))];
      const med = col[Math.floor(nPaths * 0.5)];
      p10s.push(lo);
      p90s.push(hi);
      meds.push(med);
    }

    // Band fill.
    ctx.beginPath();
    ctx.moveTo(xOf(0), yOf(p10s[0]));
    for (let s = 1; s < steps; s++) ctx.lineTo(xOf(s), yOf(p10s[s]));
    for (let s = steps - 1; s >= 0; s--) ctx.lineTo(xOf(s), yOf(p90s[s]));
    ctx.closePath();
    ctx.fillStyle = BAND_FILL;
    ctx.fill();

    // Band edges.
    ctx.lineWidth = 0.8;
    ctx.strokeStyle = BAND_EDGE;
    for (const arr of [p10s, p90s]) {
      ctx.beginPath();
      ctx.moveTo(xOf(0), yOf(arr[0]));
      for (let s = 1; s < steps; s++) ctx.lineTo(xOf(s), yOf(arr[s]));
      ctx.stroke();
    }

    // Individual paths.
    ctx.lineWidth = 0.7;
    ctx.strokeStyle = PATH_ALPHA;
    for (const path of paths) {
      ctx.beginPath();
      ctx.moveTo(xOf(0), yOf(path[0]));
      for (let s = 1; s < steps; s++) ctx.lineTo(xOf(s), yOf(path[s]));
      ctx.stroke();
    }

    // Reference line.
    ctx.setLineDash([5, 4]);
    ctx.lineWidth = 1;
    ctx.strokeStyle = REF_COLOR;
    ctx.beginPath();
    ctx.moveTo(PAD_L, yOf(refVal));
    ctx.lineTo(W - PAD_R, yOf(refVal));
    ctx.stroke();
    ctx.setLineDash([]);

    // Median path.
    ctx.lineWidth = 1.8;
    ctx.strokeStyle = MEDIAN_COLOR;
    ctx.beginPath();
    ctx.moveTo(xOf(0), yOf(meds[0]));
    for (let s = 1; s < steps; s++) ctx.lineTo(xOf(s), yOf(meds[s]));
    ctx.stroke();

    // ── Y-axis labels ─────────────────────────────────────────────────────
    ctx.font = '9px monospace';
    ctx.fillStyle = LABEL_COLOR;
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

    // ── X-axis labels ─────────────────────────────────────────────────────
    ctx.textAlign = 'center';
    const xTicks = Math.min(steps, 5);
    for (let i = 0; i <= xTicks; i++) {
      const s = Math.round((i / xTicks) * (steps - 1));
      const x = xOf(s);
      ctx.fillStyle = AXIS_COLOR;
      ctx.fillRect(x, H - PAD_B, 1, 4);
      ctx.fillStyle = LABEL_COLOR;
      ctx.fillText(`T${s + 1}`, x, H - PAD_B + 13);
    }

    // Ref label.
    ctx.textAlign = 'left';
    ctx.fillStyle = REF_COLOR;
    ctx.fillText(fmt(refVal), W - PAD_R - 34, yOf(refVal) - 3);
  }, [paths, initialCapital, currentPrice, height]);

  return (
    <div ref={containerRef} className="w-full">
      <canvas ref={canvasRef} style={{ display: 'block', width: '100%', height }} />
    </div>
  );
}
