import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Прокси в dev-режиме:
//   /api/jobs  → Java-оболочка ДИТ (порт 8080)
//   /api/*     → FastAPI-движок прототипа (порт 8000)
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api/jobs': {
        target: 'http://localhost:8080',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
});
