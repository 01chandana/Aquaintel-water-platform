import react from '@vitejs/plugin-react';
import { visualizer } from 'rollup-plugin-visualizer';
import path from 'node:path';
import { defineConfig } from 'vitest/config';

// Ch. 8.2 Vite 5 + Ch. 8.10 bundle analysis (ANALYZE=1 npm run build -> stats.html)
const VENDOR_CHUNKS: [string, string[]][] = [
  ['react', ['react', 'react-dom', 'react-router', 'react-router-dom', 'scheduler']],
  ['mui', ['@mui', '@emotion']],
  ['charts', ['recharts', 'd3-', 'd3', 'victory-vendor']],
  ['state', ['@reduxjs', 'react-redux', 'immer', 'reselect']],
];

export default defineConfig({
  plugins: [react(), ...(process.env.ANALYZE ? [visualizer({ filename: 'stats.html', gzipSize: true })] : [])],
  resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
  server: {
    port: 5173,
    proxy: {
      '/v1': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
  // `vite preview` serves the production build with the same CSP as nginx (security-headers.conf),
  // so a policy violation shows up locally rather than after deployment
  preview: {
    port: 5173,
    proxy: {
      '/v1': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
    headers: {
      'Content-Security-Policy':
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' ws: wss:; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
      'X-Content-Type-Options': 'nosniff',
      'X-Frame-Options': 'DENY',
    },
  },
  build: {
    sourcemap: true,
    chunkSizeWarningLimit: 600, // vendor chunks (MUI, charts) are cached long-term
    rollupOptions: {
      output: {
        // long-lived vendor chunks: app deploys don't invalidate the browser's copy of React / MUI / charts
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined;
          return VENDOR_CHUNKS.find(([, pkgs]) => pkgs.some((p) => id.includes(`/node_modules/${p}/`)))?.[0];
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
    css: false,
    exclude: ['tests/e2e/**', 'node_modules/**'],
  },
});
