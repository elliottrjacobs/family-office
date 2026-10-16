import * as React from "react"
import { Check, Copy } from "lucide-react"

import { Button } from "@/components/ui/button"

/** A terminal command to run outside the browser, with a copy button. */
export function CommandLine({ command }: { command: string }) {
  const [copied, setCopied] = React.useState<"yes" | "no" | null>(null)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(command)
      setCopied("yes")
    } catch {
      setCopied("no")
    }
    window.setTimeout(() => setCopied(null), 1600)
  }
  return (
    <div className="flex items-center gap-2 rounded-lg border bg-muted/50 py-1.5 pr-1.5 pl-3">
      <code className="min-w-0 flex-1 overflow-x-auto font-mono text-xs whitespace-nowrap select-all">
        {command}
      </code>
      <Button
        variant="ghost"
        size="icon-sm"
        onClick={copy}
        aria-label={copied === "no" ? "Copy failed; select the text" : "Copy command"}
        title={copied === "no" ? "Copy failed; select the text instead" : "Copy"}
      >
        {copied === "yes" ? <Check /> : <Copy />}
      </Button>
    </div>
  )
}
