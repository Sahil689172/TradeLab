import '@testing-library/jest-dom';
import { vi } from 'vitest';

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal('ResizeObserver', ResizeObserverMock);

vi.mock('lightweight-charts', () => ({
  ColorType: { Solid: 'solid' },
  createChart: () => ({
    addCandlestickSeries: () => ({ setData: vi.fn() }),
    addHistogramSeries: () => ({ setData: vi.fn() }),
    priceScale: () => ({ applyOptions: vi.fn() }),
    timeScale: () => ({ fitContent: vi.fn() }),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  }),
}));
