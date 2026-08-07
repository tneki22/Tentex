import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // В контейнере слушаем на всех интерфейсах, иначе снаружи не достучаться.
    host: true,
    proxy: {
      "/api": {
        target: process.env.TENTEX_API_URL ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
