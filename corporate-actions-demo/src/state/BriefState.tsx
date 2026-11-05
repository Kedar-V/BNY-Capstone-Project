import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { briefData, getBrief, reviewKey, type Brief, type BriefClient, type BriefItem, type Cadence } from '../data/briefs'

export interface HeldItem {
  client: BriefClient
  asOf: string
  item: BriefItem
  key: string
  approved: boolean
}

export type Perspective = 'client' | 'rm'

/** The client portal belongs to one client. Relationship managers choose the client they are looking at. */
export const PORTAL_CLIENT_ID = briefData.clients[0].id

const PerspectiveCtx = createContext<Perspective>('rm')
export const PerspectiveProvider = PerspectiveCtx.Provider

interface ClientView {
  client: BriefClient
  brief: Brief | undefined
  /** Items the client can see: cleared by the checks or approved by an operations reviewer. */
  visibleItems: BriefItem[]
  heldCount: number
}

interface BriefState extends ClientView {
  perspective: Perspective
  /** Relationship manager only. The client portal always shows its own client. */
  setClientId: (id: string) => void
  asOf: string
  setAsOf: (d: string) => void
  cadence: Cadence
  setCadence: (c: Cadence) => void
  heldItems: HeldItem[]
  pendingCount: number
  approve: (key: string) => void
  revoke: (key: string) => void
}

type Shared = Omit<BriefState, keyof ClientView | 'perspective'> & { portal: ClientView; rm: ClientView }

const Ctx = createContext<Shared | null>(null)
export function useBrief(): BriefState {
  const v = useContext(Ctx)
  const perspective = useContext(PerspectiveCtx)
  if (!v) throw new Error('useBrief must be used inside BriefProvider')
  const { portal, rm, ...shared } = v
  return { ...shared, ...(perspective === 'client' ? portal : rm), perspective }
}

export function BriefProvider({ children }: { children: ReactNode }) {
  const portalClient = briefData.clients.find((c) => c.id === PORTAL_CLIENT_ID)!
  const [clientId, setClientId] = useState(briefData.clients[0].id)
  const [asOf, setAsOf] = useState(briefData.asOfDates[briefData.asOfDates.length - 1])
  const [cadence, setCadence] = useState<Cadence>(portalClient.cadence)
  const [approved, setApproved] = useState<Set<string>>(new Set())

  const viewFor = useCallback(
    (client: BriefClient): ClientView => {
      const brief = getBrief(client.id, asOf, cadence)
      const visibleItems = (brief?.items ?? []).filter((i) => !i.review.needed || approved.has(reviewKey(client.id, asOf, i.id)))
      return { client, brief, visibleItems, heldCount: (brief?.items.length ?? 0) - visibleItems.length }
    },
    [asOf, cadence, approved],
  )
  const portal = useMemo(() => viewFor(portalClient), [viewFor, portalClient])
  const rm = useMemo(() => viewFor(briefData.clients.find((c) => c.id === clientId) ?? briefData.clients[0]), [viewFor, clientId])

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

  const value: Shared = {
    portal,
    rm,
    setClientId,
    asOf,
    setAsOf,
    cadence,
    setCadence,
    heldItems,
    pendingCount: heldItems.filter((h) => !h.approved).length,
    approve,
    revoke,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
