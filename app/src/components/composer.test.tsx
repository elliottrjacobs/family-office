import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import * as React from "react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { Composer, type WebSwitch } from "@/components/composer"

afterEach(cleanup)

function Box({
  onSend = vi.fn(async () => {}),
  web,
  ...props
}: Omit<Partial<React.ComponentProps<typeof Composer>>, "web"> & { web?: Partial<WebSwitch> }) {
  const [value, setValue] = React.useState("")
  const [on, setOn] = React.useState(web?.on ?? true)
  return (
    <Composer
      placeholder="Message Tax"
      value={value}
      onValueChange={setValue}
      onSend={onSend}
      working={false}
      web={{ available: true, ...web, on, onChange: setOn }}
      {...props}
    />
  )
}

const box = () => screen.getByRole("textbox", { name: "Message" }) as HTMLTextAreaElement

describe("Composer", () => {
  it("is a free-text message box named for the advisor, not a ticker field", () => {
    render(<Box />)
    expect(box().placeholder).toBe("Message Tax")
    expect(box().tagName).toBe("TEXTAREA")
    expect((screen.getByRole("button", { name: "Send" }) as HTMLButtonElement).disabled).toBe(true)
  })

  it("sends on Enter, keeps Shift+Enter for a new line, and ignores an empty box", async () => {
    const onSend = vi.fn(async () => {})
    render(<Box onSend={onSend} />)
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(onSend).not.toHaveBeenCalled()
    fireEvent.change(box(), { target: { value: "  What changed for 2026?  " } })
    fireEvent.keyDown(box(), { key: "Enter", shiftKey: true })
    expect(onSend).not.toHaveBeenCalled()
    fireEvent.keyDown(box(), { key: "Enter", isComposing: true })
    expect(onSend).not.toHaveBeenCalled()
    fireEvent.keyDown(box(), { key: "Enter" })
    expect(onSend).toHaveBeenCalledWith("What changed for 2026?")
  })

  it("offers Stop instead of Send while the advisor answers", () => {
    const onStop = vi.fn()
    render(<Box working onStop={onStop} />)
    expect(screen.queryByRole("button", { name: "Send" })).toBeNull()
    fireEvent.click(screen.getByRole("button", { name: "Stop" }))
    expect(onStop).toHaveBeenCalled()
  })

  it("switches web access on and off, and explains when it cannot be on", () => {
    const { unmount } = render(<Box />)
    const toggle = () => screen.getByRole("button", { name: "Web search" }) as HTMLButtonElement
    expect(toggle().getAttribute("aria-pressed")).toBe("true")
    expect(toggle().textContent).toBe("Web on")
    fireEvent.click(toggle())
    expect(toggle().getAttribute("aria-pressed")).toBe("false")
    expect(toggle().textContent).toBe("Web off")
    unmount()
    render(<Box web={{ available: false, reason: "Web access is turned off for this office." }} />)
    expect(toggle().disabled).toBe(true)
    expect(toggle().title).toBe("Web access is turned off for this office.")
    expect(toggle().getAttribute("aria-pressed")).toBe("false")
  })

  it("cannot send while disabled and says why", () => {
    render(<Box disabled notice="This chat cannot continue. Start a new one." />)
    expect(box().disabled).toBe(true)
    expect(screen.getByText("This chat cannot continue. Start a new one.")).toBeTruthy()
  })
})
