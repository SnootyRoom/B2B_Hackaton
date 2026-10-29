import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// В dev-режиме /api проксируется на бэкенд, как nginx в контейнере.
export default defineConfig({
  plugins: [react()],
  server: { port: 3000, proxy: { "/api": "http://localhost:8000" } },
});
