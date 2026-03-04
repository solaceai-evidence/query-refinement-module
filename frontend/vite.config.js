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
    rollupOptions: {
      output: {
        // Include a build epoch in filenames to guarantee cache-busting
        // across deployments, even when source content is identical.
        entryFileNames: 'assets/[name]-v3-[hash].js',
        chunkFileNames: 'assets/[name]-v3-[hash].js',
        assetFileNames: 'assets/[name]-v3-[hash].[ext]',
      },
    },
  },
  esbuild: {
    drop: ['debugger'],
    pure: ['console.log', 'console.debug'],
  }
})
