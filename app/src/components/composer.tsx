/** The message box of a conversation: type, Enter to send, with web access beside it. */

import * as React from "react"
import { ArrowUp, Globe, Loader2, Square } from "lucide-react"
import { cn } from "cn"

import { Button } from "@/components/ui/button"

const MAX_HEIGHT = 240

export interface WebSwitch {
  /** Web search and fetch will be offered on the next message. */
  on: boolean
  /** False when the office policy, the context level, or the engine rules it out. */
  available: boolean
  /** Why it is unavailable, shown on hover and to screen readers. */
  reason?: string
  onChange: (on: boolean) => void
}

/** Whether web search and fetch are on for the next message; a pressed button means on. */
export function WebToggle({ web }: { web: WebSwitch }) {
  const label = !web.available ? "Web off" : web.on ? "Web on" : "Web off"
  const title = !web.available
    ? web.reason
    : web.on
      ? "The advisor can search and read the web. Every search and site is listed in the chat."
      : "The advisor answers without the web. Turn on to let it look things up."
  return (
    <button
      type="button"
      aria-pressed={web.available && web.on}
      aria-label="Web search"
      disabled={!web.available}
      title={title}
      onClick={() => web.onChange(!web.on)}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[0.8rem] font-medium transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
        web.available && web.on
          ? "bg-info/12 text-info-foreground hover:bg-info/20"
          : "text-muted-foreground hover:bg-accent hover:text-foreground"
      )}
    >
      <Globe className="size-3.5" />
      {label}
    </button>
  )
}

export function Composer({
  placeholder,
  value,
  onValueChange,
  onSend,
  onStop,
  working,
  disabled,
  notice,
  web,
  options,
  autoFocus,
  focusSignal,
}: {
  placeholder: string
  value: string
  onValueChange: (value: string) => void
  /** Sends the trimmed text; a rejection leaves the text in the box. */
  onSend: (text: string) => Promise<void>
  onStop?: () => void
  /** The advisor is answering: the send button becomes Stop. */
  working: boolean
  /** Nothing can be sent; `notice` says why. */
  disabled?: boolean
  notice?: React.ReactNode
  web?: WebSwitch
  /** Controls beside the web switch, such as the options for a new conversation. */
  options?: React.ReactNode
  autoFocus?: boolean
  /** Change it to move focus into the box, such as after a suggestion fills it. */
  focusSignal?: number
}) {
  const [sending, setSending] = React.useState(false)
  const field = React.useRef<HTMLTextAreaElement>(null)
  const text = value.trim()
  const blocked = Boolean(disabled) || working || sending

  // Grow with the text up to a limit, then scroll inside the box.
  React.useLayoutEffect(() => {
    const element = field.current
    if (!element) return
    element.style.height = "auto"
    element.style.height = `${Math.min(element.scrollHeight, MAX_HEIGHT)}px`
  }, [value])

  React.useEffect(() => {
    if (focusSignal) field.current?.focus()
  }, [focusSignal])

  const send = async () => {
    if (!text || blocked) return
    setSending(true)
    try {
      await onSend(text)
    } finally {
      setSending(false)
      field.current?.focus()
    }
  }

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        void send()
      }}
      className="rounded-2xl border bg-card shadow-sm transition-shadow focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/30"
    >
      <textarea
        ref={field}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
        onKeyDown={(event) => {
          // Enter sends; Shift+Enter breaks the line; an input method's Enter is its own.
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            void send()
          }
        }}
        placeholder={placeholder}
        aria-label="Message"
        rows={1}
        autoFocus={autoFocus}
        disabled={Boolean(disabled)}
        className="block max-h-60 min-h-11 w-full resize-none bg-transparent px-4 pt-3 pb-1 text-[0.95rem] leading-6 outline-none placeholder:text-muted-foreground disabled:cursor-not-allowed disabled:opacity-60"
      />
      <div className="flex items-center gap-1 px-2 pb-2">
        {web && <WebToggle web={web} />}
        {options}
        <span className="min-w-0 flex-1 truncate px-1 text-right text-xs text-muted-foreground">{notice}</span>
        {working && onStop ? (
          <Button type="button" size="icon" variant="outline" className="rounded-full" onClick={onStop} aria-label="Stop">
            <Square className="size-3 fill-current" />
          </Button>
        ) : (
          <Button type="submit" size="icon" className="rounded-full" disabled={!text || blocked} aria-label="Send">
            {sending ? <Loader2 className="animate-spin" /> : <ArrowUp />}
          </Button>
        )}
      </div>
    </form>
  )
}
