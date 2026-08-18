import '@testing-library/jest-dom';
import { vi } from 'vitest';

class ResizeObserverMock {
  observe() {}
  unobserve() {}
  disconnect() {}
}

vi.stubGlobal('ResizeObserver', ResizeObserverMock);

function mockSeries() {
  return {
    setData: vi.fn(),
    setMarkers: vi.fn(),
    createPriceLine: vi.fn(() => ({ id: 'line' })),
    removePriceLine: vi.fn(),
  };
}

vi.mock('lightweight-charts', () => ({
  ColorType: { Solid: 'solid' },
  CrosshairMode: { Normal: 0 },
  createChart: () => ({
    addCandlestickSeries: () => mockSeries(),
    addHistogramSeries: () => mockSeries(),
    priceScale: () => ({ applyOptions: vi.fn() }),
    timeScale: () => ({ fitContent: vi.fn() }),
    applyOptions: vi.fn(),
    subscribeCrosshairMove: vi.fn(),
    remove: vi.fn(),
  }),
}));
