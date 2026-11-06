import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'
import { amendData, type ApprovalStatus } from '../data/amendments'
import type { ReconStep } from './ReconState'

interface AmendRun {
  open: boolean
  running: boolean
  finished: boolean
  hasRun: boolean
  steps: ReconStep[]
}

export interface Decision {
  status: ApprovalStatus
  at: string
  notice?: string
  edited?: boolean
  reason?: string
}

export interface AuditEntry {
  id: string
  itemId: string
  title: string
  action: string
  detail: string
  at: string
}

interface AmendState {
  run: AmendRun
  start: () => void
  close: () => void
  decisions: Record<string, Decision>
  decide: (itemId: string, title: string, d: Omit<Decision, 'at'>, detail: string) => void
  reopen: (itemId: string, title: string) => void
  audit: AuditEntry[]
}

const Ctx = createContext<AmendState | null>(null)
export function useAmend() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useAmend must be used inside AmendmentProvider')
  return v
}

const wait = (min: number, max = min) => new Promise((r) => window.setTimeout(r, min + Math.random() * (max - min)))
const s = amendData.summary
const STEPS: Omit<ReconStep, 'status'>[] = [
  { id: 'events', title: 'Loading corporate action events', detail: '' },
  { id: 'diff', title: 'Comparing each filing with the version before it', detail: '' },
  { id: 'rules', title: 'Applying rules to dates, prices, ratios and status', detail: '' },
  { id: 'llm', title: 'LLM judging changed wording', detail: '' },
  { id: 'checks', title: 'Running checks before anything is sent', detail: '' },
  { id: 'notices', title: 'Finding affected clients and drafting notices', detail: '' },
]

const fresh = (hasRun = false): AmendRun => ({ open: false, running: false, finished: false, hasRun, steps: STEPS.map((x) => ({ ...x, status: 'pending' })) })
const now = () => new Date().toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })

export function AmendmentProvider({ children }: { children: ReactNode }) {
  const [run, setRun] = useState<AmendRun>(fresh)
  const [decisions, setDecisions] = useState<Record<string, Decision>>({})
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const busy = useRef(false)
  const patch = (id: string, p: Partial<ReconStep>) => setRun((r) => ({ ...r, steps: r.steps.map((x) => (x.id === id ? { ...x, ...p } : x)) }))

  const start = useCallback(async () => {
    if (busy.current) return
    busy.current = true
    setRun((r) => ({ ...fresh(r.hasRun), open: true, running: true }))
    const step = async (id: string, active: string, done: string, min = 900, max = 1300) => {
      patch(id, { status: 'active', detail: active })
      await wait(min, max)
      patch(id, { status: 'done', detail: done })
    }
    await step('events', 'Grouping filings by SEC file number, deal and issuer…', `${s.events} events with more than one filing`)
    await step('diff', 'Replaying filings in date order; a blank never erases an earlier value…', `${s.amendments} later filings compared`, 1100, 1500)
    await step('rules', 'Same value written differently counts as no change…',
      `${s.by_tier.action} action needed · ${s.by_tier.informational} informational · ${s.by_tier.log_only} log only`)
    await step('llm', 'Only the changed field’s old and new wording is sent, never the whole filing…',
      `${s.llmJudged} of ${s.textChanges} wording changes judged · ${s.llmMaterial} material · answers must quote the filing`, 1300, 1700)
    await step('checks', 'Price-change window, deadlines moved earlier or into the past, missing quotes…', `${s.held_for_review} filings held for an operations reviewer`)
    await step('notices', 'Matching securities to client holdings and watchlists…',
      `${s.notices} draft notices · ${s.reachingClients} reach a client · nothing is sent until approved`)
    setRun((r) => ({ ...r, running: false, finished: true, hasRun: true }))
    busy.current = false
  }, [])

  const close = useCallback(() => setRun((r) => (r.running ? r : { ...r, open: false })), [])

  const log = (itemId: string, title: string, action: string, detail: string) =>
    setAudit((a) => [{ id: `L-${a.length + 1}`, itemId, title, action, detail, at: now() }, ...a])

  const decide = useCallback((itemId: string, title: string, d: Omit<Decision, 'at'>, detail: string) => {
    setDecisions((m) => ({ ...m, [itemId]: { ...d, at: now() } }))
    log(itemId, title, d.status === 'approved' ? 'Approved' : d.status === 'rejected' ? 'Rejected' : 'Reviewed', detail)
  }, [])

  const reopen = useCallback((itemId: string, title: string) => {
    setDecisions((m) => {
      const next = { ...m }
      delete next[itemId]
      return next
    })
    log(itemId, title, 'Reopened', 'Decision undone')
  }, [])

  return <Ctx.Provider value={{ run, start, close, decisions, decide, reopen, audit }}>{children}</Ctx.Provider>
}
