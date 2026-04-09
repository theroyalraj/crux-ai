import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/voice': {
        target: 'http://127.0.0.1:9090',
        changeOrigin: true,
        ws: true,
      },
      '/speak': { target: 'http://127.0.0.1:9090', changeOrigin: true },
      '/speak-async': { target: 'http://127.0.0.1:9090', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:9090', changeOrigin: true },
    },
  },
})
