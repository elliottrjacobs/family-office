// The phone customize sheet from the Figma frame (U20): "<Advisor>'s look" with Cancel and
// Done. Edits save as they happen so every robot follows; Cancel, Escape or a tap outside
// put back the look the sheet opened with, and Done keeps the edits.

import * as React from "react"

import { ADVISORS, type AdvisorId, type Appearance, isDefault } from "@/avatars/appearance"
import { loadAppearance, resetAppearance, saveAppearance, useAppearance } from "@/avatars/store"
import { AppearanceEditor } from "@/components/appearance-editor"
import { colorName } from "@/components/swatch-row"
import { Sheet, SheetContent, SheetDescription, SheetTitle, SheetTrigger } from "@/components/ui/sheet"

function restore(advisorId: AdvisorId, look: Appearance) {
  if (isDefault(look, advisorId)) resetAppearance(advisorId)
  else saveAppearance(advisorId, look)
}

export function AppearanceSheet({
  advisorId,
  children,
  className,
  defaultOpen = false,
  container,
  modal = true,
}: {
  advisorId: AdvisorId
  /** The trigger's content, normally the header robot. */
  children: React.ReactNode
  className?: string
  /** Opens the sheet on mount (the playground shows it open). */
  defaultOpen?: boolean
  /** Where the sheet mounts; the document body by default. */
  container?: HTMLElement | null
  /** Whether the page behind is inert while the sheet is open. */
  modal?: boolean
}) {
  const [open, setOpen] = React.useState(defaultOpen)
  const opened = React.useRef<Appearance | null>(defaultOpen ? loadAppearance(advisorId) : null)
  const look = useAppearance(advisorId)
  const name = ADVISORS[advisorId].name

  const close = (keep: boolean) => {
    if (!keep && opened.current) restore(advisorId, opened.current)
    opened.current = null
    setOpen(false)
  }

  return (
    <Sheet
      open={open}
      modal={modal}
      onOpenChange={(next) => {
        if (next) {
          opened.current = loadAppearance(advisorId)
          setOpen(true)
        } else {
          close(false)
        }
      }}
    >
      <SheetTrigger
        aria-label={`Customize ${name}'s look`}
        className={className}
        render={<button type="button" />}
      >
        {children}
      </SheetTrigger>
      <SheetContent
        side="bottom"
        showCloseButton={false}
        container={container}
        className="max-h-[92dvh] gap-0 overflow-y-auto rounded-t-3xl border-t-0 px-5 pb-[max(1.5rem,env(safe-area-inset-bottom))]"
      >
        {/* Cancel and Done stay in reach while the options scroll. */}
        <div className="sticky top-0 z-10 -mx-5 mb-2 bg-popover px-5 pt-2 pb-2">
          <div className="mx-auto mb-2 h-1 w-9 rounded-full bg-muted-foreground/30" aria-hidden />
          <div className="grid grid-cols-[1fr_auto_1fr] items-center">
            <button
              type="button"
              onClick={() => close(false)}
              className="justify-self-start rounded-md py-1 text-[15px] text-muted-foreground outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              Cancel
            </button>
            <SheetTitle className="font-sans text-[17px] font-semibold">{name}'s look</SheetTitle>
            <button
              type="button"
              onClick={() => close(true)}
              className="justify-self-end rounded-md py-1 text-[15px] font-semibold text-primary outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              Done
            </button>
          </div>
        </div>
        <SheetDescription className="sr-only">
          Changes show on every {name} robot as you make them. Cancel puts back the look you started with.
        </SheetDescription>
        <AppearanceEditor advisorId={advisorId} size="phone" caption={`${colorName(look.shell)} · tap any color to try it`} />
      </SheetContent>
    </Sheet>
  )
}
