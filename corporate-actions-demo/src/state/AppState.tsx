import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { allFilings, buildEvents, buildNotifications } from '../data/store'
import type { CorporateEvent, Filing, Notification } from '../types'

export interface PipelineStep {
  id: string
  title: string
  detail: string
  status: 'pending' | 'active' | 'done' | 'skipped'
}

export interface Pipeline {
  open: boolean
  running: boolean
  finished: boolean
  steps: PipelineStep[]
  progress: number
  current?: string
  chips: { label: string; count: number }[]
  foundCount: number
  storedRecords: number
}

interface Toast {
  id: number
  message: string
}

interface AppState {
  filings: Filing[]
  events: CorporateEvent[]
  eventById: (id: string) => CorporateEvent | undefined
  fetchedIds: Set<string>
  pipeline: Pipeline
  runFetch: () => void
  closePipeline: () => void
  subscribed: Set<string>
  toggleSubscription: (eventSubjectId: string) => void
  notifications: Notification[]
  readIds: Set<string>
  markRead: (id: string) => void
  markAllRead: () => void
  toasts: Toast[]
  toast: (m: string) => void
}

const Ctx = createContext<AppState | null>(null)
export function useApp() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp must be used inside AppProvider')
  return v
}

const wait = (ms: number) => new Promise((r) => window.setTimeout(r, ms))

const STEP_DEFS: Omit<PipelineStep, 'status'>[] = [
  { id: 'connect', title: 'Connecting to SEC EDGAR', detail: 'Searching Schedule TO, 14D-9, 425, S-4, 8-K, DEFM14A, PREM14A and 13E-3 filings' },
  { id: 'found', title: 'Identifying new filings', detail: '' },
  { id: 'download', title: 'Downloading filing documents', detail: '' },
  { id: 'process', title: 'Processing files', detail: 'Cleaning HTML, merging exhibits and preparing text for extraction' },
  { id: 'extract', title: 'Extracting terms with language models', detail: '' },
  { id: 'link', title: 'Validating and linking to events', detail: '' },
  { id: 'store', title: 'Storing records in the database', detail: '' },
]

const freshPipeline = (): Pipeline => ({
  open: false,
  running: false,
  finished: false,
  steps: STEP_DEFS.map((s) => ({ ...s, status: 'pending' })),
  progress: 0,
  chips: [],
  foundCount: 0,
  storedRecords: 0,
})

export function AppProvider({ children }: { children: ReactNode }) {
  const [fetchedIds, setFetchedIds] = useState<Set<string>>(new Set())
  const [pipeline, setPipeline] = useState<Pipeline>(freshPipeline)
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextToast = useRef(1)
  const running = useRef(false)

  const filings = useMemo(() => allFilings.filter((f) => !f.incoming || fetchedIds.has(f.id)), [fetchedIds])
  const events = useMemo(() => buildEvents(filings), [filings])
  const eventById = useCallback((id: string) => events.find((e) => e.id === id), [events])

  // Default watchlist: events that will receive follow-up filings plus the most active events
  const [subscribed, setSubscribed] = useState<Set<string>>(() => {
    const all = buildEvents(allFilings)
    const touched = new Set(allFilings.filter((f) => f.incoming).map((f) => f.eventKey))
    const ids = all.filter((e) => e.versions.length > 1 && e.versions.some((v) => touched.has(v.filing.eventKey))).map((e) => e.id)
    const busiest = [...all].sort((a, b) => b.versions.length - a.versions.length).slice(0, 4).map((e) => e.id)
    const tenders = all.filter((e) => e.action === 'tender_offer').sort((x, y) => Object.keys(y.fields).length - Object.keys(x.fields).length).slice(0, 4).map((e) => e.id)
    return new Set([...ids.slice(0, 4), ...busiest, ...tenders])
  })

  const notifications = useMemo(() => buildNotifications(events, subscribed), [events, subscribed])
  const [readIds, setReadIds] = useState<Set<string>>(() => {
    const base = buildNotifications(buildEvents(allFilings.filter((f) => !f.incoming)), subscribed)
    return new Set(base.map((n) => n.id))
  })

  const toast = useCallback((message: string) => {
    const id = nextToast.current++
    setToasts((t) => [...t, { id, message }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3200)
  }, [])

  const patchStep = (id: string, patch: Partial<PipelineStep>) =>
    setPipeline((p) => ({ ...p, steps: p.steps.map((s) => (s.id === id ? { ...s, ...patch } : s)) }))

  const runFetch = useCallback(async () => {
    if (running.current) return
    running.current = true
    const incoming = allFilings.filter((f) => f.incoming && !fetchedIds.has(f.id))
    setPipeline({ ...freshPipeline(), open: true, running: true, foundCount: incoming.length })

    // 1. Connect
    patchStep('connect', { status: 'active' })
    await wait(1300)
    patchStep('connect', { status: 'done', detail: 'Connected · 9 form types queried for the latest filing window' })

    // 2. Found
    patchStep('found', { status: 'active' })
    await wait(1100)
    const formCounts = Object.entries(incoming.reduce<Record<string, number>>((a, f) => ({ ...a, [f.form]: (a[f.form] ?? 0) + 1 }), {})).map(
      ([label, count]) => ({ label, count }),
    )
    if (!incoming.length) {
      patchStep('found', { status: 'done', title: 'No new filings found', detail: 'Everything on EDGAR for the monitored forms is already in the database' })
      setPipeline((p) => ({ ...p, steps: p.steps.map((s) => (s.status === 'pending' ? { ...s, status: 'skipped' } : s)), running: false, finished: true }))
      running.current = false
      return
    }
    const tender = incoming.filter((f) => f.action === 'tender_offer').length
    patchStep('found', {
      status: 'done',
      title: `Found ${incoming.length} new filings`,
      detail: `${tender} tender offer · ${incoming.length - tender} merger`,
    })
    setPipeline((p) => ({ ...p, chips: formCounts }))

    // 3. Download
    const docs = incoming.reduce((s, f) => s + f.docs, 0)
    const mb = incoming.reduce((s, f) => s + f.sizeMb, 0)
    patchStep('download', { status: 'active', detail: `Retrieving ${docs} documents…` })
    for (let i = 1; i <= 10; i++) {
      setPipeline((p) => ({ ...p, progress: i / 10 }))
      await wait(130)
    }
    patchStep('download', { status: 'done', detail: `${docs} documents retrieved · ${mb.toFixed(1)} MB of filing text` })

    // 4. Process
    setPipeline((p) => ({ ...p, progress: 0 }))
    patchStep('process', { status: 'active' })
    for (let i = 1; i <= 8; i++) {
      setPipeline((p) => ({ ...p, progress: i / 8 }))
      await wait(130)
    }
    patchStep('process', { status: 'done', detail: `${incoming.length} filings cleaned and prepared for extraction` })

    // 5. Extract
    setPipeline((p) => ({ ...p, progress: 0 }))
    patchStep('extract', { status: 'active' })
    for (let i = 0; i < incoming.length; i++) {
      const f = incoming[i]
      setPipeline((p) => ({ ...p, progress: (i + 1) / incoming.length, current: `${f.form} · ${f.subject}` }))
      patchStep('extract', { detail: `Filing ${i + 1} of ${incoming.length}` })
      await wait(380)
    }
    const fieldCount = incoming.reduce((s, f) => s + Object.keys(f.fields).length, 0)
    patchStep('extract', { status: 'done', detail: `${fieldCount} fields extracted with source passages` })
    setPipeline((p) => ({ ...p, current: undefined, progress: 0 }))

    // 6. Link
    patchStep('link', { status: 'active' })
    await wait(1100)
    const existing = new Set(allFilings.filter((f) => !f.incoming || fetchedIds.has(f.id)).map((f) => f.eventKey))
    const linked = incoming.filter((f) => existing.has(f.eventKey)).length
    patchStep('link', { status: 'done', detail: `${linked} linked as amendments to existing events · ${incoming.length - linked} new events created` })

    // 7. Store
    patchStep('store', { status: 'active' })
    await wait(1200)
    patchStep('store', { status: 'done', detail: `${incoming.length} filing records and ${fieldCount} field values written` })

    setFetchedIds((s) => new Set([...s, ...incoming.map((f) => f.id)]))
    setPipeline((p) => ({ ...p, running: false, finished: true, storedRecords: incoming.length }))
    running.current = false
  }, [fetchedIds])

  const closePipeline = useCallback(() => setPipeline((p) => (p.running ? p : { ...p, open: false })), [])

  const toggleSubscription = useCallback(
    (id: string) => {
      setSubscribed((s) => {
        const n = new Set(s)
        n.has(id) ? n.delete(id) : n.add(id)
        return n
      })
    },
    [],
  )
  const markRead = useCallback((id: string) => setReadIds((s) => new Set(s).add(id)), [])
  const markAllRead = useCallback(() => {
    setReadIds(new Set(notifications.map((n) => n.id)))
    toast('All notifications marked as read')
  }, [notifications, toast])

  const value: AppState = {
    filings,
    events,
    eventById,
    fetchedIds,
    pipeline,
    runFetch,
    closePipeline,
    subscribed,
    toggleSubscription,
    notifications,
    readIds,
    markRead,
    markAllRead,
    toasts,
    toast,
  }
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}
