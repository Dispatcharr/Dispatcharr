import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';

// https://vite.dev/config/
export default defineConfig({
  // The base URL for the build, adjust this to match your desired path
  plugins: [react()],

  // publicDir: '/data',

  server: {
    port: 9191,
    // Without this, /api/* is served as the React SPA in debug mode and
    // Swagger UI at /api/swagger/ never loads the OpenAPI schema.
    proxy: {
      "/api": {
        target: "http://127.0.0.1:5656",
        changeOrigin: true,
        secure: false,
      },
      "/ws": {
        target: "http://127.0.0.1:8001",
        changeOrigin: true,
        secure: false,
        ws: true,
      },
    },
  },

  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setupTests.js'],
    globals: true,
  },
});
