import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // reachable from outside the container
    port: 5173,
    watch: {
      // Bind-mounted source on Windows does not emit inotify events.
      usePolling: true,
    },
    proxy: {
      // Same-origin in the browser, so no CORS round-trip in development.
      '/api': { target: 'http://api:8000', changeOrigin: true },
    },
  },
});
