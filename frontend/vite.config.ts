import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'

// Race Center - frontend
// Solo escucha en loopback por defecto (uso personal).
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    watch: {
      // El proyecto vive en un disco de Windows montado en WSL (/mnt/c).
      // Ahi el watcher de eventos del sistema de archivos no dispara, asi que
      // el hot-reload queda muerto. Sondear con polling lo resuelve.
      usePolling: true,
      interval: 1000,
    },
    proxy: {
      // El frontend habla solo con nuestra API interna a traves del proxy.
      // Asi ninguna credencial ni URL externa llega al navegador.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
  },
})
