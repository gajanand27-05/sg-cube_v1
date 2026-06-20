import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/auth': 'http://127.0.0.1:8000',
      '/admin': 'http://127.0.0.1:8000',
      '/voice': 'http://127.0.0.1:8000',
      '/orchestrate': 'http://127.0.0.1:8000',
      '/execute': 'http://127.0.0.1:8000',
      '/vision': 'http://127.0.0.1:8000',
      '/memory': 'http://127.0.0.1:8000',
      '/ws': {
        target: 'ws://127.0.0.1:8000',
        ws: true,
      },
    },
  },
})
