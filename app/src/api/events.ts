/** Server-sent events from fo serve; the cookie travels with same-origin EventSource. */

export type Unsubscribe = () => void

export function subscribe<T>(
  path: string,
  onEvent: (event: T) => void,
  onError?: () => void
): Unsubscribe {
  const source = new EventSource(path, { withCredentials: true })
  source.onmessage = (message) => {
    try {
      onEvent(JSON.parse(message.data) as T)
    } catch {
      // A malformed event is skipped; the next one still arrives.
    }
  }
  source.onerror = () => {
    onError?.()
  }
  return () => source.close()
}
