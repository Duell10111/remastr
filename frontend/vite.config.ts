import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// During development the UI runs on Vite and proxies API calls to the backend.
// Developing on another machine (e.g. a Mac)? Set REMASTR_BACKEND=http://<pc>:8765 in frontend/.env.local
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backend = env.REMASTR_BACKEND || 'http://127.0.0.1:8765'
  return {
    plugins: [react()],
    server: {
      proxy: {
        '/api': { target: backend, changeOrigin: true },
      },
    },
  }
})
