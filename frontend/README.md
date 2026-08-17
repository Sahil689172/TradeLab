# TradeLab Frontend

Dark professional trading terminal UI for the TradeLab paper-trading dashboard. Built with React, TypeScript, Vite, Tailwind CSS, lightweight-charts, and TanStack Query.

## Prerequisites

- Node.js 18+
- TradeLab backend running at `http://127.0.0.1:8000`

## Setup

```bash
cd frontend
npm install
```

## Development

Start the Vite dev server (proxies `/api` → `http://127.0.0.1:8000`):

```bash
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

## Build

```bash
npm run build
```

Production assets are emitted to `dist/`.

## Test

```bash
npm run test
```

Watch mode:

```bash
npm run test:watch
```

## Architecture

| Path | Purpose |
|------|---------|
| `src/api/client.ts` | Typed fetch client for `/api/v1` |
| `src/types/api.ts` | API response types matching backend schemas |
| `src/pages/DashboardPage.tsx` | Main dashboard layout |
| `src/components/layout/` | Sidebar, TopBar, StatusBar |
| `src/components/dashboard/` | KPI, chart, trade, strategy widgets |

## API

All requests go through the Vite proxy to `http://127.0.0.1:8000/api/v1`. Responses use the `{ success, data }` envelope. The UI never fabricates data — loading, empty, and error states are shown when the backend is unavailable.

Default symbol: **RELIANCE**. Supported chart intervals: **1D**, **1W**, **1M** (intraday intervals show an unsupported message from the API).
