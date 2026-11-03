import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    // Calls to /api/... are forwarded to the FastAPI backend, so there are no CORS errors.
    // Example: fetch('/api/counterparties') goes to http://127.0.0.1:8000/counterparties
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
