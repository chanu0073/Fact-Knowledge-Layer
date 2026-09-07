import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
  },
  // During local dev, proxy /api to the FastAPI backend so the UI
  // can use relative URLs. In Docker, the API_BASE env is injected.
})
