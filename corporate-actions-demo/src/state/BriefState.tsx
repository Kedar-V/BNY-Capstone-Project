import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { briefData, getBrief, reviewKey, type Brief, type BriefClient, type BriefItem, type Cadence } from '../data/briefs'

export interface HeldItem {
  client: BriefClient
  asOf: string
  item: BriefItem
  key: string
  approved: boolean
}

interface BriefState {
  client: BriefClient
  setClientId: (id: string) => void
  asOf: string
  setAsOf: (d: string) => void
  cadence: Cadence
  setCadence: (c: Cadence) => void
  brief: Brief | undefined
  /** Items the client can see: cleared by the checks or approved by an operations reviewer. */
  visibleItems: BriefItem[]
  heldCount: number
  heldItems: HeldItem[]
  pendingCount: number
  approve: (key: string) => void
  revoke: (key: string) => void
}

const Ctx = createContext<BriefState | null>(null)
export function useBrief() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useBrief must be used inside BriefProvider')
  return v
}

export function BriefProvider({ children }: { children: ReactNode }) {
  const [clientId, setClientId] = useState(briefData.clients[0].id)
  const [asOf, setAsOf] = useState(briefData.asOfDates[briefData.asOfDates.length - 1])
  const [cadence, setCadence] = useState<Cadence>('weekly')
  const [approved, setApproved] = useState<Set<string>>(new Set())

  const client = briefData.clients.find((c) => c.id === clientId) ?? briefData.clients[0]
  const brief = getBrief(client.id, asOf, cadence)

  const visibleItems = useMemo(
    () => (brief?.items ?? []).filter((i) => !i.review.needed || approved.has(reviewKey(client.id, asOf, i.id))),
    [brief, approved, client.id, asOf],
  )

  // The review queue spans every client and date. Daily and weekly briefs share one approval.
  const heldItems = useMemo(() => {
    const seen = new Map<string, HeldItem>()
    for (const c of briefData.clients) {
      for (const day of briefData.asOfDates) {
        for (const cad of briefData.cadences) {
          for (const item of getBrief(c.id, day, cad)?.items ?? []) {
            if (!item.review.needed) continue
            const key = reviewKey(c.id, day, item.id)
            if (!seen.has(key)) seen.set(key, { client: c, asOf: day, item, key, approved: approved.has(key) })
          }
        }
      }
    }
    return [...seen.values()].sort((a, b) => b.asOf.localeCompare(a.asOf))
  }, [approved])

  const approve = useCallback((key: string) => setApproved((s) => new Set(s).add(key)), [])
  const revoke = useCallback((key: string) => {
    setApproved((s) => {
      const n = new Set(s)
      n.delete(key)
      return n
    })
  }, [])

  const value: BriefState = {
    client,
    setClientId,
    asOf,
    setAsOf,
    cadence,
    setCadence,
    brief,
    visibleItems,
    heldCount: (brief?.items.length ?? 0) - visibleItems.length,
    heldItems,
    pendingCount: heldItems.filter((h) => !h.approved).length,
    approve,
    revoke,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
