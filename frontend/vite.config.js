/**
 * vite.config.js — Vite + React.
 *
 * `/api/*` is proxied to the FastAPI backend (`./start.sh`, port 8000), so the browser talks to
 * one origin and the frontend never hardcodes a backend URL. 127.0.0.1 (not "localhost") because
 * uvicorn listens on IPv4 and Node may resolve "localhost" to ::1 first.
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const proxy = { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } };

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { proxy },
});
