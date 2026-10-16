import * as React from "react"
import { cn } from "cn"

/** A single-choice segmented control: a radiogroup of buttons, arrow keys move the choice. */
export function Segmented<T extends string>({
  label,
  options,
  value,
  onChange,
  invalid,
  className,
}: {
  label: string
  options: { value: T; label: string }[]
  value: T | null
  onChange: (value: T) => void
  invalid?: boolean
  className?: string
}) {
  const refs = React.useRef<(HTMLButtonElement | null)[]>([])
  const move = (index: number) => {
    const next = (index + options.length) % options.length
    onChange(options[next].value)
    refs.current[next]?.focus()
  }
  return (
    <div
      role="radiogroup"
      aria-label={label}
      aria-invalid={invalid || undefined}
      className={cn(
        "inline-flex w-fit rounded-lg bg-muted p-[3px]",
        invalid && "ring-1 ring-destructive",
        className
      )}
    >
      {options.map((option, index) => {
        const checked = option.value === value
        return (
          <button
            key={option.value}
            ref={(element) => {
              refs.current[index] = element
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked || (value === null && index === 0) ? 0 : -1}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => {
              if (event.key === "ArrowRight" || event.key === "ArrowDown") {
                event.preventDefault()
                move(index + 1)
              } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
                event.preventDefault()
                move(index - 1)
              }
            }}
            className={cn(
              "rounded-md px-3 py-1 text-sm font-medium text-muted-foreground transition-colors outline-none focus-visible:ring-2 focus-visible:ring-ring/50",
              checked && "bg-background text-foreground shadow-sm"
            )}
          >
            {option.label}
          </button>
        )
      })}
    </div>
  )
}
