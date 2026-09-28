import { defineConfig } from 'vite';

export default defineConfig({
  base: '/dashboard/',
  server: {
    proxy: {
      '/api': {target: 'http://127.0.0.1:8765', changeOrigin: false},
      '/diagnostic': {target: 'http://127.0.0.1:8765', changeOrigin: false},
      '/assets': {target: 'http://127.0.0.1:8765', changeOrigin: false},
    },
  },
});
