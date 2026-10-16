import * as React from "react"

/** A small history router; fo serve returns the app shell for any client path. */

const listeners = new Set<() => void>()

function current() {
  return window.location.pathname + window.location.search
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  window.addEventListener("popstate", listener)
  return () => {
    listeners.delete(listener)
    window.removeEventListener("popstate", listener)
  }
}

export function navigate(to: string) {
  if (to === current()) return
  window.history.pushState(null, "", to)
  listeners.forEach((listener) => listener())
  window.scrollTo?.({ top: 0 })
}

export function useLocation() {
  const href = React.useSyncExternalStore(subscribe, current, () => "/")
  return React.useMemo(() => {
    const url = new URL(href, "http://app.local")
    return { path: url.pathname, query: url.searchParams }
  }, [href])
}

type LinkProps = Omit<React.ComponentProps<"a">, "href"> & { to: string }

export function Link({ to, onClick, ...props }: LinkProps) {
  return (
    <a
      href={to}
      {...props}
      onClick={(event) => {
        onClick?.(event)
        if (
          event.defaultPrevented ||
          event.button !== 0 ||
          event.metaKey ||
          event.ctrlKey ||
          event.shiftKey ||
          event.altKey
        ) {
          return
        }
        event.preventDefault()
        navigate(to)
      }}
    />
  )
}

export const reportHref = (path: string) => `/reports/view?path=${encodeURIComponent(path)}`
