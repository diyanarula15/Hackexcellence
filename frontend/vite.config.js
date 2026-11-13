/** vite.config.js — Vite + React. No custom config needed for the shell. */
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
});
