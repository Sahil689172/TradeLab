/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // ws:true carries the room socket through.
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
        // Monte Carlo streaming can take several minutes for the historical
        // replay phase.  The default proxy timeout (60 s) kills the SSE
        // connection before the backend finishes loading trades, which makes
        // the browser report "Cancelled".  Set to 20 minutes to outlast any
        // realistic run.
        proxyTimeout: 20 * 60 * 1000,
        timeout: 20 * 60 * 1000,
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
});
