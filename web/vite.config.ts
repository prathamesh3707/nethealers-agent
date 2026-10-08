import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The game talks to the Python backend (scripts/serve.py, port 8010). In development Vite forwards
// API and WebSocket calls to it; in a build, the backend serves this app itself, so URLs stay relative.
const backend = 'http://127.0.0.1:8010'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/sessions': { target: backend, ws: true, changeOrigin: true },
      '/health': backend,
      '/kb': backend,
      '/gaps': backend,
      '/adviser': backend,
      '/alignment': backend,
    },
  },
  build: { chunkSizeWarningLimit: 2000 },
})
