/** Display helpers. A null value is unknown and says so; it is never shown as zero. */

export const UNKNOWN = "unknown"

const dollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
})
const compactDollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 2,
})

export function money(value: number | null, compact = false) {
  if (value === null) return UNKNOWN
  return (compact && Math.abs(value) >= 10_000 ? compactDollars : dollars).format(value)
}

export function percent(value: number | null, digits = 1) {
  if (value === null) return UNKNOWN
  return `${(value * 100).toFixed(digits)}%`
}

export function quantity(value: number | null) {
  if (value === null) return UNKNOWN
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(value)
}

function parse(value: string) {
  // A bare date is a calendar day, not midnight UTC.
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T12:00:00`) : new Date(value)
}

export function day(value: string | null | undefined) {
  if (!value) return UNKNOWN
  const date = parse(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
}

export function moment(value: string | null | undefined) {
  if (!value) return UNKNOWN
  const date = parse(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
}

export function age(value: string | null | undefined, now = Date.now()) {
  if (!value) return UNKNOWN
  const hours = (now - parse(value).getTime()) / 3_600_000
  if (Number.isNaN(hours)) return UNKNOWN
  if (hours < 1) return "under an hour ago"
  if (hours < 48) return `${Math.round(hours)} hours ago`
  return `${Math.round(hours / 24)} days ago`
}

export function monthLabel(value: string) {
  const date = parse(`${value}-01`)
  return date.toLocaleDateString("en-US", { month: "long", year: "numeric" })
}

export function titleCase(value: string) {
  return value
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((word) => word[0].toUpperCase() + word.slice(1))
    .join(" ")
}

/** Journal actions are entered in capitals (HOLD, TRIM); show them as words. */
export function action(value: string) {
  return value === value.toUpperCase() ? value[0] + value.slice(1).toLowerCase() : value
}
