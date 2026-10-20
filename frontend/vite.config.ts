import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/users": { target: "http://localhost:8000", changeOrigin: true },
      "/evaluate": { target: "http://localhost:8000", changeOrigin: true },
      "/trust": { target: "http://localhost:8000", changeOrigin: true },
      "/audit": { target: "http://localhost:8000", changeOrigin: true },
      "/report": { target: "http://localhost:8000", changeOrigin: true },
      "/health": { target: "http://localhost:8000", changeOrigin: true },
      '/chart': 'http://localhost:8000',
      '/collabs': 'http://localhost:8000',       
      '/communities': 'http://localhost:8000',
      '/opportunities': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true }
    },
  },
});   