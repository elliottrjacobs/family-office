import * as React from "react"

import { Link, reportHref } from "@/lib/router"

/**
 * Report markdown rendered as React elements, never as HTML. Report text includes
 * provider-derived and model-written content, so raw HTML stays literal text, only web
 * and mail links become anchors, and report paths link inside the app.
 */

type Align = "left" | "center" | "right" | undefined

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "code"; text: string }
  | { kind: "quote"; blocks: Block[] }
  | { kind: "rule" }
  | { kind: "list"; ordered: boolean; items: { text: string; children: Block[] }[] }
  | { kind: "table"; header: string[]; align: Align[]; rows: string[][] }

const FENCE = /^\s*(```|~~~)/
const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/
const RULE = /^\s*([-*_])(\s*\1){2,}\s*$/
const QUOTE = /^\s*>\s?(.*)$/
const LIST = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/
const DIVIDER = /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/

function indentOf(line: string) {
  return line.match(/^\s*/)![0].length
}

function cells(line: string) {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim())
}

function startsBlock(lines: string[], i: number) {
  const line = lines[i]
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    RULE.test(line) ||
    QUOTE.test(line) ||
    LIST.test(line) ||
    (line.includes("|") && i + 1 < lines.length && DIVIDER.test(lines[i + 1]))
  )
}

function list(lines: string[], start: number): [Block, number] {
  const first = lines[start].match(LIST)!
  const indent = first[1].length
  const ordered = /\d/.test(first[2])
  const items: { text: string; children: Block[] }[] = []
  let i = start
  while (i < lines.length) {
    const line = lines[i]
    const match = line.match(LIST)
    if (match && match[1].length === indent && /\d/.test(match[2]) === ordered) {
      items.push({ text: match[3], children: [] })
      i++
    } else if (line.trim() && indentOf(line) > indent) {
      const begin = i
      while (i < lines.length && lines[i].trim() && indentOf(lines[i]) > indent) i++
      const nested = lines.slice(begin, i)
      const shift = Math.min(...nested.map(indentOf))
      const last = items[items.length - 1]
      if (LIST.test(nested[0])) last.children.push(...parse(nested.map((l) => l.slice(shift))))
      else last.text += " " + nested.map((l) => l.trim()).join(" ")
    } else if (!line.trim()) {
      let next = i
      while (next < lines.length && !lines[next].trim()) next++
      const following = next < lines.length ? lines[next].match(LIST) : null
      if (following && following[1].length === indent && /\d/.test(following[2]) === ordered) {
        i = next
      } else {
        break
      }
    } else {
      break
    }
  }
  return [{ kind: "list", ordered, items }, i]
}

function parse(lines: string[]): Block[] {
  const blocks: Block[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) {
      i++
      continue
    }
    const fence = line.match(FENCE)
    if (fence) {
      const body: string[] = []
      i++
      while (i < lines.length && !lines[i].trim().startsWith(fence[1])) body.push(lines[i++])
      i++
      blocks.push({ kind: "code", text: body.join("\n") })
      continue
    }
    const heading = line.match(HEADING)
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2] })
      i++
      continue
    }
    if (RULE.test(line)) {
      blocks.push({ kind: "rule" })
      i++
      continue
    }
    if (QUOTE.test(line)) {
      const quoted: string[] = []
      while (i < lines.length && QUOTE.test(lines[i])) quoted.push(lines[i++].match(QUOTE)![1])
      blocks.push({ kind: "quote", blocks: parse(quoted) })
      continue
    }
    if (line.includes("|") && i + 1 < lines.length && DIVIDER.test(lines[i + 1])) {
      const header = cells(line)
      const align = cells(lines[i + 1]).map((cell): Align =>
        cell.startsWith(":") && cell.endsWith(":")
          ? "center"
          : cell.endsWith(":")
            ? "right"
            : cell.startsWith(":")
              ? "left"
              : undefined
      )
      i += 2
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) rows.push(cells(lines[i++]))
      blocks.push({ kind: "table", header, align, rows })
      continue
    }
    if (LIST.test(line)) {
      const [block, next] = list(lines, i)
      blocks.push(block)
      i = next
      continue
    }
    const text: string[] = []
    while (i < lines.length && lines[i].trim() && (text.length === 0 || !startsBlock(lines, i))) {
      text.push(lines[i++].trim())
    }
    blocks.push({ kind: "paragraph", text: text.join(" ") })
  }
  return blocks
}

const INLINE =
  /(`+)(.+?)\1|\*\*(.+?)\*\*|__(.+?)__|\*(?!\s)(.+?)\*|(?<!\w)_(?!\s)(.+?)_(?!\w)|\[([^\]]+)\]\(([^)\s]+)\)/g

function destination(href: string): { kind: "web" | "report"; href: string } | null {
  if (/^(https?:\/\/|mailto:)/i.test(href)) return { kind: "web", href }
  if (/^reports\/[^\s]+\.md$/.test(href) && !href.split("/").includes("..")) {
    return { kind: "report", href: reportHref(href) }
  }
  return null
}

function inline(text: string, key = "i"): React.ReactNode[] {
  const nodes: React.ReactNode[] = []
  let last = 0
  let index = 0
  for (const match of text.matchAll(INLINE)) {
    const at = match.index ?? 0
    if (at > last) nodes.push(text.slice(last, at))
    const id = `${key}-${index++}`
    if (match[2] !== undefined) {
      nodes.push(
        <code key={id} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em]">
          {match[2]}
        </code>
      )
    } else if (match[3] !== undefined || match[4] !== undefined) {
      nodes.push(<strong key={id}>{inline(match[3] ?? match[4], id)}</strong>)
    } else if (match[5] !== undefined || match[6] !== undefined) {
      nodes.push(<em key={id}>{inline(match[5] ?? match[6], id)}</em>)
    } else {
      const label = inline(match[7], id)
      const target = destination(match[8])
      if (target?.kind === "web") {
        nodes.push(
          <a
            key={id}
            href={target.href}
            target="_blank"
            rel="noopener noreferrer"
            className="font-medium underline underline-offset-4"
          >
            {label}
          </a>
        )
      } else if (target?.kind === "report") {
        nodes.push(
          <Link key={id} to={target.href} className="font-medium underline underline-offset-4">
            {label}
          </Link>
        )
      } else {
        nodes.push(<React.Fragment key={id}>{label}</React.Fragment>)
      }
    }
    last = at + match[0].length
  }
  if (last < text.length) nodes.push(text.slice(last))
  return nodes
}

const HEADINGS = [
  "mt-6 text-2xl first:mt-0",
  "mt-6 text-xl first:mt-0",
  "mt-5 text-lg first:mt-0",
  "mt-4 text-base font-semibold first:mt-0",
  "mt-4 text-sm font-semibold first:mt-0",
  "mt-4 text-sm font-semibold text-muted-foreground first:mt-0",
]

function render(blocks: Block[], key: string): React.ReactNode[] {
  return blocks.map((block, index) => {
    const id = `${key}.${index}`
    switch (block.kind) {
      case "heading": {
        const Tag = `h${block.level}` as "h1"
        return (
          <Tag key={id} className={HEADINGS[block.level - 1]}>
            {inline(block.text, id)}
          </Tag>
        )
      }
      case "paragraph":
        return (
          <p key={id} className="mt-3 leading-relaxed first:mt-0">
            {inline(block.text, id)}
          </p>
        )
      case "code":
        return (
          <pre key={id} className="mt-3 overflow-x-auto rounded-lg bg-muted p-3 text-xs leading-relaxed">
            <code className="font-mono">{block.text}</code>
          </pre>
        )
      case "quote":
        return (
          <blockquote key={id} className="mt-3 border-l-2 pl-4 text-muted-foreground">
            {render(block.blocks, id)}
          </blockquote>
        )
      case "rule":
        return <hr key={id} className="my-6" />
      case "list": {
        const Tag = block.ordered ? "ol" : "ul"
        return (
          <Tag
            key={id}
            className={`mt-3 space-y-1 pl-5 ${block.ordered ? "list-decimal" : "list-disc"}`}
          >
            {block.items.map((item, n) => (
              <li key={`${id}-${n}`} className="leading-relaxed">
                <span>{inline(item.text, `${id}-${n}`)}</span>
                {render(item.children, `${id}-${n}`)}
              </li>
            ))}
          </Tag>
        )
      }
      case "table":
        return (
          <div key={id} className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  {block.header.map((cell, n) => (
                    <th
                      key={n}
                      style={{ textAlign: block.align[n] }}
                      className="px-2 py-1.5 text-left font-medium text-muted-foreground"
                    >
                      {inline(cell, `${id}-h${n}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {block.rows.map((row, r) => (
                  <tr key={r} className="border-b last:border-0">
                    {row.map((cell, n) => (
                      <td key={n} style={{ textAlign: block.align[n] }} className="px-2 py-1.5">
                        {inline(cell, `${id}-${r}-${n}`)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
    }
  })
}

export function Markdown({ text, className }: { text: string; className?: string }) {
  const blocks = React.useMemo(() => parse(text.replace(/\r\n?/g, "\n").split("\n")), [text])
  return <div className={className}>{render(blocks, "md")}</div>
}
