/**
 * vite.config.js - Vite + React.
 *
 * `/api/*` is proxied to the FastAPI backend (`./start.sh`, port 8000 unless BACKEND_PORT is set), so the browser talks to
 * one origin and the frontend never hardcodes a backend URL. 127.0.0.1 (not "localhost") because
 * uvicorn listens on IPv4 and Node may resolve "localhost" to ::1 first.
 */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Port of the backend. start.sh sets BACKEND_PORT (default 8000); the proxy follows it.
const BACKEND_PORT = process.env.BACKEND_PORT ?? '8000';
const proxy = { '/api': { target: `http://127.0.0.1:${BACKEND_PORT}`, changeOrigin: true } };

export default defineConfig({
  plugins: [react()],
  server: { proxy },
  preview: { proxy },
});
