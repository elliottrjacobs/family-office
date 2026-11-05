// Captures the avatar playground's screenshot set (U21) into docs/explainers/robots/.
//
//   npm run screenshots
//
// Starts the Vite dev server from this app's config with the /api proxy removed (the
// playground makes no API calls), opens each `?shot=` section in Chromium at device scale
// factor 2, waits for `data-ready`, and writes one PNG per capture, cropped to its element.
// Motion is reduced so every robot shows its static state pose and reruns match.

import { mkdir } from "node:fs/promises"
import { resolve } from "node:path"
import { chromium } from "playwright"
import { createServer, loadConfigFromFile } from "vite"

const app = resolve(import.meta.dirname, "..")
const out = resolve(app, "../docs/explainers/robots")

/** file name, section, theme, and the element to crop to inside the section. */
const SHOTS = [
  ["defaults-light.png", "defaults", "light", "[data-panel=light]"],
  ["defaults-dark.png", "defaults", "dark", "[data-panel=dark]"],
  ["states-cio.png", "states", "light", "[data-panel]"],
  ["combinations-light.png", "combinations", "light", "[data-panel]"],
  ["combinations-dark.png", "combinations", "dark", "[data-panel]"],
  ["inspector-mac.png", "customize", "light", "[data-inspector-column]"],
  ["sheet-phone.png", "customize", "light", "[data-phone-frame]"],
]

async function startServer() {
  const loaded = await loadConfigFromFile({ command: "serve", mode: "development" }, undefined, app)
  const config = loaded?.config ?? {}
  const server = await createServer({
    ...config,
    configFile: false,
    root: app,
    logLevel: "warn",
    server: { host: "127.0.0.1", port: 0, strictPort: false },
  })
  await server.listen()
  const address = server.httpServer?.address()
  if (!address || typeof address === "string") throw new Error("The dev server has no port.")
  return { server, origin: `http://127.0.0.1:${address.port}` }
}

const { server, origin } = await startServer()
const browser = await chromium.launch()
try {
  await mkdir(out, { recursive: true })
  for (const [file, shot, theme, target] of SHOTS) {
    const context = await browser.newContext({
      viewport: { width: 1320, height: 1000 },
      deviceScaleFactor: 2,
      colorScheme: theme,
      reducedMotion: "reduce",
    })
    const page = await context.newPage()
    const failed = []
    page.on("pageerror", (error) => failed.push(error.message))
    page.on("request", (request) => {
      if (new URL(request.url()).pathname.startsWith("/api/")) failed.push(`API request ${request.url()}`)
    })
    await page.goto(`${origin}/playground/robots?shot=${shot}&theme=${theme}`)
    await page.locator(`[data-shot=${shot}][data-ready=true]`).waitFor({ timeout: 20_000 })
    // The sheet focuses Cancel on open; a pointer tap would not show that ring.
    await page.evaluate(() => document.activeElement instanceof HTMLElement && document.activeElement.blur())
    const element = page.locator(`[data-shot=${shot}] ${target}`).first()
    await element.screenshot({ path: resolve(out, file), animations: "disabled" })
    await context.close()
    if (failed.length) throw new Error(`${file}: ${failed.join("; ")}`)
    console.log(`wrote docs/explainers/robots/${file}`)
  }
} finally {
  await browser.close()
  await server.close()
}
