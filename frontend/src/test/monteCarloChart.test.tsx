/**
 * MonteCarloPathChart — band provenance and view switching.
 *
 * The chart must never present percentiles derived from the handful of
 * illustrative sample paths as if they described the whole run.  These tests
 * pin that distinction, because getting it wrong would overstate how much
 * evidence a displayed band carries.
 */

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MonteCarloPathChart } from '../components/chart/MonteCarloPathChart';
import type { MonteCarloBands } from '../types/api';

const BANDS: MonteCarloBands = {
  steps: [0, 1, 2],
  paths_used: 100_000,
  p10: [100_000, 99_000, 98_000],
  p25: [100_000, 99_500, 99_000],
  p50: [100_000, 100_000, 100_500],
  p75: [100_000, 100_500, 101_500],
  p90: [100_000, 101_000, 102_500],
};

const SAMPLE_PATHS = [
  [99_000, 98_000],
  [100_500, 101_500],
  [100_000, 100_200],
];

/**
 * JSX interpolation splits a sentence across several text nodes, so match on
 * the element's normalized textContent rather than a single node's text.
 */
function hasText(pattern: RegExp) {
  return (_content: string, element: Element | null) => {
    if (!element) return false;
    const normalized = (element.textContent ?? '').replace(/\s+/g, ' ').trim();
    if (!pattern.test(normalized)) return false;
    // Prefer the innermost matching element so the assertion is unambiguous.
    return !Array.from(element.children).some((child) =>
      pattern.test((child.textContent ?? '').replace(/\s+/g, ' ').trim()),
    );
  };
}

function renderChart(props: Partial<React.ComponentProps<typeof MonteCarloPathChart>> = {}) {
  return render(
    <MonteCarloPathChart
      samplePaths={SAMPLE_PATHS}
      initialCapital={100_000}
      {...props}
    />,
  );
}

describe('MonteCarloPathChart band provenance', () => {
  it('reports the full simulated path count when the backend sent bands', () => {
    renderChart({ bands: BANDS });
    // Digit grouping is locale-dependent (this app runs under en-IN, which
    // renders 100000 as "1,00,000"), so assert on the digits, not the commas.
    expect(
      screen.getByText(hasText(/across [\d,  ]+ simulated paths/i)),
    ).toBeInTheDocument();
  });

  it('does not claim full-run coverage when bands came from sample paths', () => {
    renderChart({ bands: null });
    expect(
      screen.queryByText(hasText(/across [\d,  ]+ simulated paths/i)),
    ).not.toBeInTheDocument();
  });

  it('flags fallback percentiles as derived from the sample only', () => {
    renderChart({ bands: null });
    expect(screen.getByText(hasText(/not the full run/i))).toBeInTheDocument();
  });

  it('names the sample size used for fallback percentiles', () => {
    renderChart({ bands: null });
    expect(
      screen.getByText(hasText(new RegExp(`${SAMPLE_PATHS.length} sample paths`, "i"))),
    ).toBeInTheDocument();
  });

  it('treats an empty bands object from the backend as absent', () => {
    // The stream sends `{}` for bands until the first batch completes.
    renderChart({ bands: {} as MonteCarloBands });
    expect(screen.getByText(hasText(/not the full run/i))).toBeInTheDocument();
  });

  it('prefers backend bands over sample paths when both are present', () => {
    renderChart({ bands: BANDS });
    expect(screen.queryByText(hasText(/not the full run/i))).not.toBeInTheDocument();
  });
});

describe('MonteCarloPathChart views', () => {
  it('shows the percentile legend in fan view', () => {
    renderChart({ bands: BANDS, view: 'fan' });
    expect(screen.getByText(/P25–P75 · P10–P90 bands/i)).toBeInTheDocument();
  });

  it('hides the percentile legend in distribution view', () => {
    renderChart({ bands: BANDS, view: 'distribution' });
    expect(screen.queryByText(/P25–P75/i)).not.toBeInTheDocument();
  });

  it('hides the percentile legend in drawdown view', () => {
    renderChart({ bands: BANDS, view: 'drawdown' });
    expect(screen.queryByText(/P25–P75/i)).not.toBeInTheDocument();
  });

  it('renders with no data at all without throwing', () => {
    expect(() =>
      render(
        <MonteCarloPathChart samplePaths={[]} bands={null} initialCapital={100_000} />,
      ),
    ).not.toThrow();
  });

  it('renders a canvas element for the chart surface', () => {
    const { container } = renderChart({ bands: BANDS });
    expect(container.querySelector('canvas')).not.toBeNull();
  });
});
