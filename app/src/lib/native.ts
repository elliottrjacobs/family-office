/**
 * The bridge to the Mac app. Inside its window, WebKit exposes a message handler named
 * familyOffice; the app then opens its own Settings pane or setup dialog.
 * In a browser, and on the paired phone, there is no handler and callers fall back to
 * words: the menu path on the Mac, or the terminal command.
 */

export type NativeAction = "setup" | "settings:connectors" | "settings:engines" | "settings:devices"

interface Handler {
  postMessage: (message: { action: string }) => void
}

function handler(): Handler | undefined {
  const scope = window as unknown as { webkit?: { messageHandlers?: { familyOffice?: Handler } } }
  return scope.webkit?.messageHandlers?.familyOffice
}

export function hasNative() {
  return handler() !== undefined
}

/** Ask the Mac app to act; false when this page is not inside it. */
export function native(action: NativeAction) {
  const bridge = handler()
  if (!bridge) return false
  try {
    bridge.postMessage({ action })
    return true
  } catch {
    return false
  }
}

/** The native action for a setup step, and what its button says. */
export function stepButton(action: string | null | undefined): { action: NativeAction; label: string } | null {
  if (!action) return null
  if (action === "setup") return { action: "setup", label: "Open setup" }
  if (action === "connect" || action.startsWith("connect:")) {
    return { action: "settings:connectors", label: "Open Connectors" }
  }
  return null
}

/** Where the same step lives in the Mac app, for a page that cannot press it. */
export function stepPlace(action: string | null | undefined) {
  if (!action) return null
  if (action === "setup") return "On your Mac, choose Help > Set Up Family Office…"
  if (action === "sync") return "Use Sync now at the top of the window."
  if (action === "connect" || action.startsWith("connect:")) {
    return "On your Mac, open Family Office > Settings > Connectors."
  }
  return null
}
