// Per-advisor appearance persistence in localStorage. The server is never written to.
// Every storage access is guarded: blocked or full storage yields the default look.

import { useCallback, useSyncExternalStore } from "react"

import {
  type AdvisorId,
  type Appearance,
  defaultAppearance,
  parseAppearance,
  serializeAppearance,
} from "@/avatars/appearance"

export const STORAGE_PREFIX = "fo.avatar.v1."

export function storageKey(advisorId: AdvisorId): string {
  return `${STORAGE_PREFIX}${advisorId}`
}

type Listener = () => void
const listeners = new Map<AdvisorId, Set<Listener>>()
// The last parsed value per advisor, keyed by its raw text, so snapshots stay stable.
const cache = new Map<AdvisorId, { raw: string | null; value: Appearance }>()

function readRaw(advisorId: AdvisorId): string | null {
  try {
    return window.localStorage.getItem(storageKey(advisorId))
  } catch {
    return null
  }
}

export function loadAppearance(advisorId: AdvisorId): Appearance {
  const raw = readRaw(advisorId)
  const cached = cache.get(advisorId)
  if (cached && cached.raw === raw) return cached.value
  const value = raw === null ? defaultAppearance(advisorId) : parseAppearance(raw, advisorId)
  cache.set(advisorId, { raw, value })
  return value
}

/** Stores the look and notifies every subscriber; returns false when storage refused it. */
export function saveAppearance(advisorId: AdvisorId, appearance: Appearance): boolean {
  let saved = true
  try {
    window.localStorage.setItem(storageKey(advisorId), serializeAppearance(appearance))
  } catch {
    saved = false
  }
  notify(advisorId)
  return saved
}

/** Forgets the stored look so the advisor's default applies; returns false when storage refused it. */
export function resetAppearance(advisorId: AdvisorId): boolean {
  let reset = true
  try {
    window.localStorage.removeItem(storageKey(advisorId))
  } catch {
    reset = false
  }
  notify(advisorId)
  return reset
}

export function subscribe(advisorId: AdvisorId, listener: Listener): () => void {
  let set = listeners.get(advisorId)
  if (!set) {
    set = new Set()
    listeners.set(advisorId, set)
  }
  set.add(listener)
  return () => {
    set.delete(listener)
  }
}

function notify(advisorId: AdvisorId) {
  for (const listener of listeners.get(advisorId) ?? []) listener()
}

// Another tab saving a look updates this one too.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (event) => {
    if (!event.key?.startsWith(STORAGE_PREFIX)) return
    const id = event.key.slice(STORAGE_PREFIX.length) as AdvisorId
    notify(id)
  })
}

const defaults = new Map<AdvisorId, Appearance>()

function stableDefault(advisorId: AdvisorId): Appearance {
  let value = defaults.get(advisorId)
  if (!value) {
    value = defaultAppearance(advisorId)
    defaults.set(advisorId, value)
  }
  return value
}

/** The stored look of an advisor, re-rendering whenever it is saved or reset. */
export function useAppearance(advisorId: AdvisorId): Appearance {
  const subscribeToAdvisor = useCallback((listener: Listener) => subscribe(advisorId, listener), [advisorId])
  const snapshot = useCallback(() => loadAppearance(advisorId), [advisorId])
  const serverSnapshot = useCallback(() => stableDefault(advisorId), [advisorId])
  return useSyncExternalStore(subscribeToAdvisor, snapshot, serverSnapshot)
}
