/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// В режиме разработки запросы /api пересылаются на бэкенд (FastAPI на :8000).
// Другой адрес: BACKEND_URL=http://host:port npm run dev
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      '/api': process.env.BACKEND_URL ?? 'http://localhost:8000',
    },
  },
  test: {
    environment: 'node',
  },
});
