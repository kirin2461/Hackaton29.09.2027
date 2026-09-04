import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Прокси /api -> FastAPI (порт 8000): фронтенд ходит на свой же origin,
// а Vite пересылает запросы бэкенду — так обходим CORS в dev-режиме.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
