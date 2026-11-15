/** Which advisors are answering now, and which answered while the person was elsewhere. */

import * as React from "react"

import { ACTIVE, type Run } from "@/api/runs"

export interface ChatActivity {
  /** The chat each advisor is answering in, by advisor name. */
  answering: Record<string, Run>
  /** The chat that finished unseen for each advisor, by advisor name. */
  finished: Record<string, Run>
}

interface Memory {
  list: Run[] | undefined
  open: string | null
  /** Chats this page has seen answering. */
  watched: string[]
  unseen: string[]
}

function advance(memory: Memory, list: Run[] | undefined, open: string | null): Memory {
  const watched = new Set(memory.watched)
  const unseen = new Set(memory.unseen)
  if (open) unseen.delete(open)
  for (const run of list ?? []) {
    if (ACTIVE.includes(run.status)) watched.add(run.id)
    else if (watched.delete(run.id) && run.id !== open) unseen.add(run.id)
  }
  return { list, open, watched: [...watched], unseen: [...unseen] }
}

/**
 * Follow the polled chat list. A chat this page saw answering that then stops, while a
 * different page is open, counts as finished until it is opened. Nothing is stored: a
 * reload starts clean, and chats that were already done are never marked.
 */
export function useChatActivity(list: Run[] | undefined, open: string | null): ChatActivity {
  const [memory, setMemory] = React.useState<Memory>(() =>
    advance({ list: undefined, open, watched: [], unseen: [] }, list, open)
  )
  // Derived from the props during render, as React asks of state that follows them.
  if (memory.list !== list || memory.open !== open) setMemory(advance(memory, list, open))
  const unseen = memory.unseen

  return React.useMemo(() => {
    const answering: Record<string, Run> = {}
    const finished: Record<string, Run> = {}
    // Oldest first, so each advisor ends on its most recent chat.
    for (const run of [...(list ?? [])].reverse()) {
      if (ACTIVE.includes(run.status)) answering[run.skill] = run
      else if (unseen.includes(run.id)) finished[run.skill] = run
    }
    return { answering, finished }
  }, [list, unseen])
}
