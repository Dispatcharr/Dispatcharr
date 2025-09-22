import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';

// https://vite.dev/config/
export default defineConfig({
  // The base URL for the build, adjust this to match your desired path
  plugins: [react()],

  // publicDir: '/data',

  server: {
    port: 9191,

    // proxy: {
    //   "/api": {
    //     target: "http://localhost:5656", // Backend server
    //     changeOrigin: true,
    //     secure: false, // Set to true if backend uses HTTPS
    //     // rewrite: (path) => path.replace(/^\/api/, ""), // Optional path rewrite
    //   },
    //   "/ws": {
    //     target: "http://localhost:8001", // Backend server
    //     changeOrigin: true,
    //     secure: false, // Set to true if backend uses HTTPS
    //     // rewrite: (path) => path.replace(/^\/api/, ""), // Optional path rewrite
    //   },
    // },
  },

  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setupTests.js'],
    globals: true,
  },
});
