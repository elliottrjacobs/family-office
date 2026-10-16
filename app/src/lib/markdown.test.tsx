import { cleanup, render } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import { Markdown } from "@/lib/markdown"

afterEach(cleanup)

describe("Markdown", () => {
  it("renders raw HTML as text and never creates script or image elements", () => {
    const { container } = render(
      <Markdown text={'Hello <script>alert("x")</script>\n\n<img src=x onerror=alert(1)>'} />
    )
    expect(container.querySelector("script")).toBeNull()
    expect(container.querySelector("img")).toBeNull()
    expect(container.textContent).toContain('<script>alert("x")</script>')
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>")
  })

  it("renders headings, lists, tables, code, quotes, and emphasis", () => {
    const text = [
      "# Title",
      "## What changed",
      "",
      "A **bold** and *quiet* line with `code`.",
      "",
      "- first",
      "- second",
      "  - nested",
      "",
      "1. one",
      "2. two",
      "",
      "| Name | Weight |",
      "|---|---:|",
      "| ACME | 40% |",
      "",
      "> A quote",
      "",
      "```",
      "fo allocation --json",
      "```",
      "",
      "---",
    ].join("\n")
    const { container } = render(<Markdown text={text} />)
    expect(container.querySelector("h1")?.textContent).toBe("Title")
    expect(container.querySelector("h2")?.textContent).toBe("What changed")
    expect(container.querySelector("strong")?.textContent).toBe("bold")
    expect(container.querySelector("em")?.textContent).toBe("quiet")
    expect(container.querySelector("p code")?.textContent).toBe("code")
    const top = [...container.querySelector("ul")!.children]
    expect(top.map((li) => li.firstChild?.textContent)).toEqual(["first", "second"])
    expect(container.querySelector("ul ul li")?.textContent).toBe("nested")
    expect(container.querySelectorAll("ol > li")).toHaveLength(2)
    expect([...container.querySelectorAll("th")].map((th) => th.textContent)).toEqual([
      "Name",
      "Weight",
    ])
    expect(container.querySelector("td:last-child")?.getAttribute("style")).toContain("right")
    expect(container.querySelector("blockquote")?.textContent).toBe("A quote")
    expect(container.querySelector("pre code")?.textContent).toBe("fo allocation --json")
    expect(container.querySelector("hr")).not.toBeNull()
  })

  it("opens web links in a new tab and drops unsafe ones", () => {
    const { container } = render(
      <Markdown text="[docs](https://example.com/a) and [bad](javascript:alert(1)) and [mail](mailto:a@example.com)" />
    )
    const links = [...container.querySelectorAll("a")]
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "https://example.com/a",
      "mailto:a@example.com",
    ])
    expect(links[0].getAttribute("target")).toBe("_blank")
    expect(links[0].getAttribute("rel")).toBe("noopener noreferrer")
    expect(container.textContent).toContain("bad")
  })

  it("links report paths inside the app", () => {
    const { container } = render(<Markdown text="See [prior](reports/research/ACME/2026-01-02-report.md)." />)
    const link = container.querySelector("a")
    expect(link?.getAttribute("href")).toBe(
      "/reports/view?path=reports%2Fresearch%2FACME%2F2026-01-02-report.md"
    )
    expect(link?.getAttribute("target")).toBeNull()
  })
})
