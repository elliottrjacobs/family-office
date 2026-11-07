import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { defaultAppearance } from "@/avatars/appearance"
import { Robot } from "@/avatars/Robot"
import { saveAppearance } from "@/avatars/store"
import { AppearanceSheet } from "@/components/appearance-sheet"

afterEach(() => {
  cleanup()
  window.localStorage.clear()
})

const stored = () => JSON.parse(window.localStorage.getItem("fo.avatar.v1.cio") ?? "null")

function renderSheet() {
  return render(
    <AppearanceSheet advisorId="cio">
      <Robot advisor="cio" size={48} />
    </AppearanceSheet>
  )
}

async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Customize CIO's look" }))
  return await screen.findByRole("dialog")
}

describe("AppearanceSheet", () => {
  it("opens from the header robot with the title, an idle preview and the caption", async () => {
    renderSheet()
    const sheet = await open()
    expect(within(sheet).getByText("CIO's look")).toBeDefined()
    expect(within(sheet).getByRole("img", { name: "CIO idle" })).toBeDefined()
    expect(within(sheet).getByText("Cobalt · tap any color to try it")).toBeDefined()
    fireEvent.click(within(sheet).getByRole("radio", { name: "Teal" }))
    expect(within(sheet).getByText("Teal · tap any color to try it")).toBeDefined()
    expect(within(sheet).getByRole("button", { name: "Reset to Cobalt" })).toBeDefined()
  })

  it("Cancel puts back the look the sheet opened with", async () => {
    act(() => {
      saveAppearance("cio", { ...defaultAppearance("cio"), shell: "#E84593", eyes: "ring" })
    })
    const { container } = renderSheet()
    const sheet = await open()
    fireEvent.click(within(sheet).getByRole("radio", { name: "Teal" }))
    fireEvent.click(within(within(sheet).getByRole("radiogroup", { name: "Screen glow" })).getByRole("radio", { name: "Mint" }))
    // Edits show at once on every robot, the header one included.
    expect(stored()).toMatchObject({ shell: "#0EA5B7", screen: "mint" })
    expect(container.querySelector("linearGradient stop[offset='0.55']")?.getAttribute("stop-color")).toBe("#0EA5B7")
    fireEvent.click(within(sheet).getByRole("button", { name: "Cancel" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(stored()).toMatchObject({ shell: "#E84593", eyes: "ring", screen: "tinted" })
  })

  it("Cancel from the default look leaves nothing stored", async () => {
    renderSheet()
    const sheet = await open()
    fireEvent.click(within(sheet).getByRole("radio", { name: "Olive" }))
    fireEvent.click(within(sheet).getByRole("button", { name: "Cancel" }))
    expect(window.localStorage.getItem("fo.avatar.v1.cio")).toBeNull()
  })

  it("Done keeps the edits and closes", async () => {
    renderSheet()
    const sheet = await open()
    fireEvent.click(within(sheet).getByRole("radio", { name: "Teal" }))
    fireEvent.click(within(sheet).getByRole("button", { name: "Done" }))
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(stored().shell).toBe("#0EA5B7")
  })

  it("Escape cancels like the Cancel button", async () => {
    renderSheet()
    const sheet = await open()
    fireEvent.click(within(sheet).getByRole("radio", { name: "Teal" }))
    fireEvent.keyDown(sheet, { key: "Escape" })
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
    expect(window.localStorage.getItem("fo.avatar.v1.cio")).toBeNull()
  })
})
