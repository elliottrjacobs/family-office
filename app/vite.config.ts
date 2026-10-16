/// <reference types="vitest/config" />
import { resolve } from "node:path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// The build is committed inside the Python package so a plain git install serves the UI
// without Node. It must not go to a dist/ folder, which the repository ignores.
const output = resolve(import.meta.dirname, "../src/fo/data/app")
// `fo serve` checks Host and Origin, so the dev proxy presents itself as the server.
const server = process.env.FO_SERVE_URL ?? "http://127.0.0.1:4790"

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": resolve(import.meta.dirname, "./src"),
    },
  },
  build: {
    outDir: output,
    emptyOutDir: true,
    assetsInlineLimit: 0,
    sourcemap: false,
  },
  test: {
    environment: "jsdom",
  },
  server: {
    host: "127.0.0.1",
    proxy: {
      "/api": {
        target: server,
        changeOrigin: true,
        configure: (proxy) => {
          proxy.on("proxyReq", (request) => {
            if (request.getHeader("origin")) request.setHeader("origin", server)
          })
        },
      },
    },
  },
})
