import * as React from "react"

import { ApiError } from "@/api/client"

export interface Loaded<T> {
  data: T | undefined
  error: ApiError | undefined
  loading: boolean
  reload: () => void
}

interface Result<T> {
  key: string
  data?: T
  error?: ApiError
}

function asError(reason: unknown) {
  return reason instanceof ApiError
    ? reason
    : new ApiError(0, "operation_failed", "The request failed.")
}

/**
 * The last answer for each key, kept for the life of the page. A view that mounts again,
 * such as a tab or a page revisited, shows it at once instead of a loading skeleton, and
 * asks again only when it is older than FRESH.
 */
const answers = new Map<string, { data: unknown; at: number }>()
// Requests under way, so two views that ask for the same key at once share one.
const asking = new Map<string, Promise<unknown>>()
const FRESH = 2_000

// Every mounted useApi, so new office data can be asked for everywhere at once.
const mounted = new Set<() => void>()

/** Forget every remembered answer; tests call this between cases. */
export function resetApiCache() {
  answers.clear()
  asking.clear()
}

/** Ask again for everything on screen, such as after a sync brought new data. */
export function refreshAll() {
  answers.clear()
  for (const reload of mounted) reload()
}

function ask<T>(key: string, load: () => Promise<T>): Promise<T> {
  const under = asking.get(key)
  if (under) return under as Promise<T>
  const request = load().then(
    (data) => {
      answers.set(key, { data, at: Date.now() })
      return data
    }
  )
  const settled = () => {
    if (asking.get(key) === request) asking.delete(key)
  }
  request.then(settled, settled)
  asking.set(key, request)
  return request
}

/**
 * Load `key` once, and again every `interval` ms while the page is visible. A refresh
 * keeps the previous data on screen; `loading` is true only before the first answer this
 * page has seen for the key.
 */
export function useApi<T>(key: string, load: () => Promise<T>, interval?: number): Loaded<T> {
  const [result, setResult] = React.useState<Result<T>>(() => {
    const known = answers.get(key)
    return known ? { key, data: known.data as T } : { key: "" }
  })
  const [tick, setTick] = React.useState(0)
  const loader = React.useRef(load)
  const loaded = React.useRef<{ key: string; tick: number } | null>(null)

  React.useEffect(() => {
    loader.current = load
  })

  React.useEffect(() => {
    let live = true
    const known = answers.get(key)
    // A mount or a new key reuses a fresh answer; a tick (poll or reload) always asks.
    const asked = loaded.current?.key === key && loaded.current.tick !== tick
    loaded.current = { key, tick }
    if (known && !asked && Date.now() - known.at < FRESH) {
      setResult({ key, data: known.data as T })
      return
    }
    ask(key, loader.current).then(
      (data) => live && setResult({ key, data }),
      (reason: unknown) =>
        live &&
        setResult((previous) => ({
          key,
          data: previous.key === key ? previous.data : (answers.get(key)?.data as T | undefined),
          error: asError(reason),
        }))
    )
    return () => {
      live = false
    }
  }, [key, tick])

  React.useEffect(() => {
    if (!interval) return
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") setTick((t) => t + 1)
    }, interval)
    return () => window.clearInterval(timer)
  }, [interval])

  const reload = React.useCallback(() => setTick((t) => t + 1), [])
  React.useEffect(() => {
    mounted.add(reload)
    return () => {
      mounted.delete(reload)
    }
  }, [reload])
  const current = result.key === key
  // Between a key change and its effect, the remembered answer stands in.
  const known = current ? undefined : answers.get(key)
  return {
    data: current ? result.data : (known?.data as T | undefined),
    error: current ? result.error : undefined,
    loading: !current && !known,
    reload,
  }
}
