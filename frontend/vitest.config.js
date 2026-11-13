/** Test-only config (kept out of vite.config.js): jsdom + the same React plugin. */
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: { environment: 'jsdom', include: ['src/**/*.test.{js,jsx}'], restoreMocks: true },
});
