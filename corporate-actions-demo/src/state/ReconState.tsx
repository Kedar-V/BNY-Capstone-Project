import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import { reconData, type TicketStatus } from '../data/reconciliation'

export interface ReconStep {
  id: string
  title: string
  detail: string
  status: 'pending' | 'active' | 'done'
}

interface ReconRun {
  open: boolean
  running: boolean
  finished: boolean
  hasRun: boolean
  steps: ReconStep[]
  progress: number
}

interface ReconState {
  run: ReconRun
  start: () => void
  close: () => void
  statuses: Record<string, TicketStatus>
  setStatus: (id: string, s: TicketStatus) => void
}

const Ctx = createContext<ReconState | null>(null)
export function useRecon() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useRecon must be used inside ReconProvider')
  return v
}

const wait = (min: number, max = min) => new Promise((r) => window.setTimeout(r, min + Math.random() * (max - min)))

const { vendors, totals, tickets } = reconData
const high = tickets.filter((t) => t.severity === 'high').length

const STEPS: Omit<ReconStep, 'status'>[] = [
  { id: 'load', title: 'Loading vendor feeds', detail: '' },
  { id: 'normalize', title: 'Normalizing to a common record', detail: '' },
  { id: 'match', title: 'Matching vendor records to SEC filings', detail: '' },
  { id: 'compare', title: 'Comparing offer price, expiration and CUSIP', detail: '' },
  { id: 'raise', title: 'Raising discrepancies', detail: '' },
  { id: 'evidence', title: 'Attaching filing evidence', detail: '' },
]

const fresh = (hasRun = false): ReconRun => ({
  open: false,
  running: false,
  finished: false,
  hasRun,
  steps: STEPS.map((s) => ({ ...s, status: 'pending' })),
  progress: 0,
})

export function ReconProvider({ children }: { children: ReactNode }) {
  const [run, setRun] = useState<ReconRun>(fresh)
  const [statuses, setStatuses] = useState<Record<string, TicketStatus>>({})
  const busy = useRef(false)

  const patch = (id: string, p: Partial<ReconStep>) => setRun((r) => ({ ...r, steps: r.steps.map((s) => (s.id === id ? { ...s, ...p } : s)) }))
  const bar = async (n: number, min: number, max: number) => {
    for (let i = 1; i <= n; i++) {
      setRun((r) => ({ ...r, progress: i / n }))
      await wait(min, max)
    }
    setRun((r) => ({ ...r, progress: 0 }))
  }

  const start = useCallback(async () => {
    if (busy.current) return
    busy.current = true
    setRun((r) => ({ ...fresh(r.hasRun), open: true, running: true }))

    patch('load', { status: 'active', detail: 'Reading vendor files…' })
    await wait(900, 1300)
    patch('load', { status: 'done', detail: vendors.map((v) => `${v.name} (${v.format}) ${v.records} records`).join(' · ') })

    patch('normalize', { status: 'active', detail: 'Standardizing issuer names, number formats, date formats and UTC timestamps…' })
    await bar(8, 140, 260)
    patch('normalize', { status: 'done', detail: `${totals.vendorRecords} records converted to one common format` })

    patch('match', { status: 'active', detail: 'Matching on issuer name, announcement date and CUSIP…' })
    await bar(10, 130, 240)
    patch('match', { status: 'done', detail: `${totals.matched} of ${totals.vendorRecords} vendor records matched to a filing-based record` })

    patch('compare', { status: 'active', detail: 'Checking each matched record…' })
    await bar(12, 160, 300)
    patch('compare', { status: 'done', detail: 'Price compared where the filing states a dollar amount; dates compared to the day' })

    patch('raise', { status: 'active', detail: 'Applying severity rules…' })
    await wait(900, 1300)
    patch('raise', { status: 'done', detail: `${tickets.length} discrepancies raised · ${high} high · ${tickets.length - high} medium` })

    patch('evidence', { status: 'active', detail: 'Linking each ticket to the filing passage it was checked against…' })
    await wait(1000, 1400)
    patch('evidence', { status: 'done', detail: 'Source passage, form and filing date attached to every ticket' })

    setRun((r) => ({ ...r, running: false, finished: true, hasRun: true }))
    busy.current = false
  }, [])

  const close = useCallback(() => setRun((r) => (r.running ? r : { ...r, open: false })), [])
  const setStatus = useCallback((id: string, s: TicketStatus) => setStatuses((m) => ({ ...m, [id]: s })), [])

  return <Ctx.Provider value={{ run, start, close, statuses, setStatus }}>{children}</Ctx.Provider>
}
