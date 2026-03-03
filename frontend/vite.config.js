import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true,
        secure: false,
      }
    }
  },
  build: {
    // Strip all console.* calls from production builds
    // logForwarder.js intercepts console at runtime for structured logging;
    // raw console.log debug statements are not needed in production bundles.
    minify: 'esbuild',
    target: 'es2015',
  },
  esbuild: {
    drop: ['debugger'],
    pure: ['console.log', 'console.debug'],
  }
})
