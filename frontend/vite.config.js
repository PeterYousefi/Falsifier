import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Build output goes to frontend/dist.
// In production the FastAPI app serves dist/ as static files.
// The dev server proxies /jobs, /provenance, /health to the API.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: false,
    rollupOptions: {
      output: {
        // Deterministic chunk names so CI can diff them
        entryFileNames: 'assets/[name]-[hash].js',
        chunkFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash][extname]',
      },
    },
  },
  server: {
    proxy: {
      '/jobs':       { target: 'http://localhost:8000', changeOrigin: true },
      '/provenance': { target: 'http://localhost:8000', changeOrigin: true },
      '/health':     { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
})
