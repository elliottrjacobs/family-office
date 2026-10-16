/** Fetch client for fo serve. Errors arrive as the CLI's {reason, message} envelope. */

export class ApiError extends Error {
  readonly reason: string
  readonly status: number

  constructor(status: number, reason: string, message: string) {
    super(message)
    this.status = status
    this.reason = reason
  }

  /** The per-launch cookie is missing or stale; only the printed URL fixes it. */
  get signedOut() {
    return this.status === 401
  }
}

async function read(response: Response): Promise<unknown> {
  const text = await response.text()
  try {
    return text ? JSON.parse(text) : null
  } catch {
    throw new ApiError(response.status, "invalid_response", "The server sent an unreadable response.")
  }
}

export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, { credentials: "same-origin", ...init })
  } catch {
    throw new ApiError(0, "server_unreachable", "fo serve is not running. Start it again in a terminal.")
  }
  const body = await read(response)
  if (!response.ok) {
    const envelope = (body ?? {}) as { reason?: string; message?: string }
    throw new ApiError(
      response.status,
      envelope.reason ?? "operation_failed",
      envelope.message ?? "The request failed."
    )
  }
  return body as T
}

export function get<T>(path: string): Promise<T> {
  return request<T>(path)
}

export function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
}

/** Decimal strings become numbers here and nowhere else; null stays unknown, never zero. */
export function num(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null
  const parsed = typeof value === "number" ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function nums<K extends string>(values: Record<K, unknown>): Record<K, number | null> {
  return Object.fromEntries(Object.entries(values).map(([k, v]) => [k, num(v)])) as Record<
    K,
    number | null
  >
}
