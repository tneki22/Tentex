import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

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
  test: {
    // globals нужен не ради describe/it, а ради автоочистки Testing Library:
    // без него DOM копится между тестами и запросы находят по два заголовка.
    globals: true,
    environment: "jsdom",
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
  },
});
