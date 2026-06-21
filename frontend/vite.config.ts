import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/auth': 'http://127.0.0.1:8001',
      '/admin': 'http://127.0.0.1:8001',
      '/voice': 'http://127.0.0.1:8001',
      '/orchestrate': 'http://127.0.0.1:8001',
      '/execute': 'http://127.0.0.1:8001',
      '/vision': 'http://127.0.0.1:8001',
      '/memory': 'http://127.0.0.1:8001',
      '/ws': {
        target: 'ws://127.0.0.1:8001',
        ws: true,
      },
    },
  },
})
