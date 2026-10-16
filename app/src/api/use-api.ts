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
 * Load `key` once, and again every `interval` ms while the page is visible. A refresh
 * keeps the previous data on screen; `loading` is true only before the first answer.
 */
export function useApi<T>(key: string, load: () => Promise<T>, interval?: number): Loaded<T> {
  const [result, setResult] = React.useState<Result<T>>({ key: "" })
  const [tick, setTick] = React.useState(0)
  const loader = React.useRef(load)

  React.useEffect(() => {
    loader.current = load
  })

  React.useEffect(() => {
    let live = true
    loader.current().then(
      (data) => live && setResult({ key, data }),
      (reason: unknown) =>
        live &&
        setResult((previous) => ({
          key,
          data: previous.key === key ? previous.data : undefined,
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
  const current = result.key === key
  return {
    data: current ? result.data : undefined,
    error: current ? result.error : undefined,
    loading: !current,
    reload,
  }
}
