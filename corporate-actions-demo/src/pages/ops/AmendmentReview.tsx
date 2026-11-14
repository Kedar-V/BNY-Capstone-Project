import {
  Activity, AlertTriangle, Bot, CalendarClock, CalendarPlus, CalendarSearch, CalendarX2, Check, CheckCircle2, ChevronDown, CircleDollarSign, ExternalLink,
  FileDiff, FileText, Loader2, Pencil, Quote, RotateCcw, Scale, Send, Users, XCircle, type LucideIcon,
} from 'lucide-react'
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, CardHeader, Drawer, Empty, Modal, PageHeader, SearchInput, Segmented, ShowMore, Toggle, type Tone } from '../../components/ui'
import {
  ACTION_LABEL, amendData, changeSummary, CHECK_LABEL, dateShift, dayNum, daysFromFiling, deadlineShift, fieldLabel, fmtDays, headlineChange,
  noticeText, numericDelta, recordUpdates, REJECT_REASONS, SECTORS, TIER_HINT, TIER_LABEL, wordDiff,
  type AmendAction, type AmendChange, type Amendment, type AmendTier, type ApprovalStatus, type DateShift, type ShiftKind,
} from '../../data/amendments'
import { fmtDate } from '../../data/store'
import { useAmend } from '../../state/AmendmentState'
import { useApp } from '../../state/AppState'
import type { ReconStep } from '../../state/ReconState'

const PAGE = 20
const TIER_TONE: Record<AmendTier, Tone> = { action: 'review', needs_review: 'pending', informational: 'new', log_only: 'neutral' }
const STATUS_TONE: Record<ApprovalStatus, Tone> = { pending: 'pending', approved: 'completed', rejected: 'neutral', reviewed: 'brand' }
const STATUS_LABEL: Record<ApprovalStatus, string> = { pending: 'Awaiting decision', approved: 'Approved', rejected: 'Rejected', reviewed: 'Reviewed' }
const items = amendData.items
const sendable = (a: Amendment) => a.tier !== 'log_only'

function Steps({ steps }: { steps: ReconStep[] }) {
  return (
    <ol>
      {steps.map((s, i) => (
        <li key={s.id} className="relative flex gap-4 pb-5 last:pb-0">
          {i < steps.length - 1 && <span className={`absolute left-[13px] top-7 h-[calc(100%-1.75rem)] w-0.5 transition-colors duration-500 ${s.status === 'done' ? 'bg-brand-500' : 'bg-slate-200'}`} />}
          <span
            className={`relative z-10 grid h-7 w-7 shrink-0 place-items-center rounded-full transition-all duration-300 ${
              s.status === 'done' ? 'bg-brand-600 text-white' : s.status === 'active' ? 'bg-white text-brand-600 ring-2 ring-brand-500' : 'bg-white text-slate-300 ring-1 ring-slate-200'
            }`}
          >
            {s.status === 'done' ? <Check size={15} strokeWidth={3} /> : s.status === 'active' ? <Loader2 size={15} className="animate-spin" /> : <span className="h-2 w-2 rounded-full bg-slate-300" />}
          </span>
          <div className="min-w-0 flex-1 pt-0.5">
            <div className={`text-sm font-semibold ${s.status === 'pending' ? 'text-slate-400' : 'text-navy-900'}`}>{s.title}</div>
            {s.status !== 'pending' && s.detail && <div className="fade-in mt-0.5 text-xs text-slate-500">{s.detail}</div>}
          </div>
        </li>
      ))}
    </ol>
  )
}

function RunPanel() {
  const { run, close } = useAmend()
  return (
    <Modal open={run.open} onClose={close} wide title={run.finished ? 'Amendment check complete' : 'Checking filings for amendments'}>
      <div className="px-6 py-5"><Steps steps={run.steps} /></div>
      <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50 px-6 py-3.5">
        <span className="text-xs text-slate-500">{run.running ? 'Rules decide first; the LLM only sees changed wording.' : 'Draft notices are waiting for an operations decision.'}</span>
        <Button variant="primary" onClick={close} disabled={run.running}>{run.finished ? 'Review the queue' : 'Close'}</Button>
      </div>
    </Modal>
  )
}

const wait = (ms: number) => new Promise((r) => window.setTimeout(r, ms + Math.random() * 400))

/** Mock of what approving would trigger. Nothing is sent in the demo. */
function ApprovalRun({ item, edited, onDone }: { item: Amendment; edited: boolean; onDone: () => void }) {
  const recipients = item.notice?.recipients ?? []
  const watchers = item.notice?.watchers ?? []
  const updates = recordUpdates(item)
  const llm = item.changes.filter((c) => c.decidedBy === 'llm').length
  const plan: [string, string][] = [
    ['Notice approved', `Approved by you (operations reviewer)${edited ? ', with your edits' : ''}`],
    ['Event record updated', updates.length ? updates.join(' · ') : 'No dated or numeric terms to update'],
    ['Notice queued for clients', recipients.length ? `${recipients.join(', ')} (portal and email)` : 'No client holds this security; the notice is filed with the event'],
    ['Watchlists and relationship managers alerted', watchers.length ? `Watchlist alert: ${watchers.join(', ')}` : recipients.length ? `Relationship managers for ${recipients.join(', ')} copied` : 'No one to alert'],
    ['Audit log written', `Approver, time, edits${llm ? ` and ${llm} LLM-decided change${llm === 1 ? '' : 's'}` : ''} recorded with the filing`],
  ]
  const [steps, setSteps] = useState<ReconStep[]>(plan.map(([title], i) => ({ id: String(i), title, detail: '', status: 'pending' })))
  const [done, setDone] = useState(false)
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      for (let i = 0; i < plan.length && !cancelled; i++) {
        setSteps((s) => s.map((x, j) => (j === i ? { ...x, status: 'active', detail: 'Working…' } : x)))
        await wait(650)
        if (cancelled) return
        setSteps((s) => s.map((x, j) => (j === i ? { ...x, status: 'done', detail: plan[i][1] } : x)))
      }
      if (!cancelled) setDone(true)
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return (
    <Modal open onClose={() => done && onDone()} wide title={done ? 'Notice approved' : 'Approving notice'}>
      <div className="px-6 py-5"><Steps steps={steps} /></div>
      <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50 px-6 py-3.5">
        <span className="text-xs text-slate-500">Demo only: no notice is sent and no record is changed.</span>
        <Button variant="primary" onClick={onDone} disabled={!done}>Done</Button>
      </div>
    </Modal>
  )
}


/* ---------- Date visibility ---------- */

const SHIFT_STYLE: Record<ShiftKind, { chip: string; box: string; icon: LucideIcon; label: string }> = {
  earlier: { chip: 'bg-rose-100 text-rose-800 ring-rose-300', box: 'border-rose-300 bg-rose-50 text-rose-900', icon: CalendarX2, label: 'Moved earlier' },
  later: { chip: 'bg-sky-100 text-sky-800 ring-sky-300', box: 'border-sky-200 bg-sky-50 text-sky-900', icon: CalendarClock, label: 'Extended' },
  set: { chip: 'bg-slate-100 text-slate-700 ring-slate-300', box: 'border-slate-200 bg-slate-50 text-slate-800', icon: CalendarPlus, label: 'Date set' },
  stale: { chip: 'bg-amber-100 text-amber-900 ring-amber-300', box: 'border-amber-200 bg-amber-50 text-amber-900', icon: CalendarSearch, label: 'Date before filing' },
}
const ICON_TONE: Record<ShiftKind, string> = { earlier: 'text-rose-600', later: 'text-sky-600', set: 'text-slate-500', stale: 'text-amber-600' }
const short = (s: string | null) => (s ?? '').replace(/, \d{4}$/, '')

/** "Expiration Feb 8 → Feb 6  −2d" for the queue table. */
function DateChip({ shift }: { shift: DateShift }) {
  const st = SHIFT_STYLE[shift.kind]
  const c = shift.change
  return (
    <span className="inline-flex items-center gap-1.5">
      <st.icon size={14} className={ICON_TONE[shift.kind]} />
      <span className="text-slate-600">{fieldLabel(c.field)}</span>
      {c.previous && <><span className="text-slate-400 line-through">{short(c.previous)}</span><span className="text-slate-400">→</span></>}
      <span className="font-semibold text-navy-900">{short(c.current)}</span>
      <span className={`rounded-full px-1.5 py-px text-[11px] font-semibold ring-1 ring-inset ${st.chip}`}>{shift.days !== null ? fmtDays(shift.days) : 'new'}</span>
    </span>
  )
}

/** Filing date, old deadline and new deadline on one line, so the shift is visible at a glance. */
function DateTimeline({ item, shift }: { item: Amendment; shift: DateShift }) {
  const filed = dayNum(item.filed)!
  const was = dayNum(shift.change.previous)
  const now = dayNum(shift.change.current)!
  const pts = [filed, now, ...(was !== null ? [was] : [])]
  const lo = Math.min(...pts), hi = Math.max(...pts)
  const pad = Math.max(2, (hi - lo) * 0.08)
  const pos = (d: number) => `${((d - lo + pad) / (hi - lo + 2 * pad)) * 100}%`
  const bar = { earlier: 'bg-rose-400', later: 'bg-sky-400', set: 'bg-slate-400', stale: 'bg-amber-400' }[shift.kind]
  const dot = { earlier: 'bg-rose-600', later: 'bg-sky-600', set: 'bg-slate-600', stale: 'bg-amber-500' }[shift.kind]
  return (
    <div className="mt-3">
      <div className="relative h-6">
        <div className="absolute inset-x-0 top-1/2 h-0.5 -translate-y-1/2 rounded bg-slate-200" />
        {was !== null && (
          <div className={`absolute top-1/2 h-1 -translate-y-1/2 rounded ${bar}`} style={{ left: pos(Math.min(was, now)), width: `calc(${pos(Math.max(was, now))} - ${pos(Math.min(was, now))})` }} />
        )}
        <span className="absolute top-1/2 h-3 w-0.5 -translate-x-1/2 -translate-y-1/2 bg-slate-500" style={{ left: pos(filed) }} title={`Filed ${fmtDate(item.filed)}`} />
        {was !== null && <span className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-slate-400 bg-white" style={{ left: pos(was) }} title={`Was ${shift.change.previous}`} />}
        <span className={`absolute top-1/2 h-3.5 w-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full ring-2 ring-white ${dot}`} style={{ left: pos(now) }} title={`Now ${shift.change.current}`} />
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-600">
        <span className="flex items-center gap-1"><span className="h-2.5 w-0.5 bg-slate-500" /> Filed {short(fmtDate(item.filed))}</span>
        {was !== null && <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-full border-2 border-slate-400" /> Was {short(shift.change.previous)}</span>}
        <span className="flex items-center gap-1"><span className={`h-2 w-2 rounded-full ${dot}`} /> Now {short(shift.change.current)}</span>
      </div>
    </div>
  )
}

/** The headline deadline change at the top of the drawer. */
function DateAlert({ item, shift }: { item: Amendment; shift: DateShift }) {
  const st = SHIFT_STYLE[shift.kind]
  const left = daysFromFiling(item, shift.change.current)
  const what = fieldLabel(shift.change.field)
  const head =
    shift.kind === 'earlier' ? `${what} moved ${Math.abs(shift.days!)} day${Math.abs(shift.days!) === 1 ? '' : 's'} earlier`
    : shift.kind === 'later' ? `${what} extended by ${shift.days} day${shift.days === 1 ? '' : 's'}`
    : shift.kind === 'stale' ? `${what} is before this filing's date`
    : `${what} set`
  return (
    <div className={`rounded-xl border p-3.5 ${st.box}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2 text-sm font-semibold"><st.icon size={17} /> {head}</div>
        {left !== null && (
          <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ring-inset ${left < 0 ? 'bg-slate-100 text-slate-600 ring-slate-300' : left <= 10 ? 'bg-rose-100 text-rose-800 ring-rose-300' : 'bg-white/70 text-slate-700 ring-slate-300'}`}>
            {left < 0 ? 'already past at filing' : `${left} days after filing`}
          </span>
        )}
      </div>
      <div className="mt-1.5 text-lg font-semibold tracking-tight text-navy-900">
        {shift.change.previous && <><span className="font-normal text-slate-400 line-through">{shift.change.previous}</span><span className="mx-2 text-slate-400">→</span></>}
        {shift.change.current}
      </div>
      <DateTimeline item={item} shift={shift} />
      {shift.kind === 'stale' && <p className="mt-2 text-xs">Usually an earlier offer round's date carried into this filing. Check the filing before sending.</p>}
    </div>
  )
}

/* ---------- What changed ---------- */

function fieldIcon(c: AmendChange): LucideIcon {
  if (dateShift(c) || /date|deadline/.test(c.field)) return CalendarClock
  if (c.kind === 'status') return Activity
  if (c.kind === 'text') return FileText
  if (/ratio/.test(c.field)) return Scale
  if (/price|cash|consideration/.test(c.field)) return CircleDollarSign
  return Pencil
}

/** Changed words highlighted in place; long unchanged runs are trimmed. */
function WordDiff({ before, after }: { before: string; after: string }) {
  const [all, setAll] = useState(false)
  const parts = useMemo(() => wordDiff(before, after), [before, after])
  const added = parts.filter((p) => p.t === 'add').reduce((n, p) => n + p.text.split(' ').length, 0)
  const total = after.split(/\s+/).filter(Boolean).length || 1
  const trim = (s: string, first: boolean, last: boolean) => {
    const w = s.split(' ')
    if (all || w.length <= 12) return s
    if (first) return '… ' + w.slice(-6).join(' ')
    if (last) return w.slice(0, 6).join(' ') + ' …'
    return `${w.slice(0, 5).join(' ')} … ${w.slice(-5).join(' ')}`
  }
  return (
    <div className="mt-2">
      <p className="rounded-lg bg-slate-50 p-2.5 text-xs leading-relaxed text-slate-600">
        {parts.map((p, i) => [
          p.t === 'same' ? <span key={i}>{trim(p.text, i === 0, i === parts.length - 1)}</span>
          : p.t === 'del' ? <del key={i} className="rounded bg-rose-100 px-0.5 text-rose-800 decoration-rose-400">{p.text}</del>
          : <ins key={i} className="rounded bg-emerald-100 px-0.5 font-medium text-emerald-900 no-underline">{p.text}</ins>,
          ' ',
        ])}
      </p>
      <div className="mt-1 flex items-center gap-3 text-[11px] text-slate-500">
        <span><span className="rounded bg-rose-100 px-1 text-rose-800">removed</span> <span className="rounded bg-emerald-100 px-1 text-emerald-900">added</span></span>
        <span>{Math.round((added / total) * 100)}% of the new wording is new</span>
        <button onClick={() => setAll((v) => !v)} className="font-medium text-brand-700 hover:underline">{all ? 'Trim unchanged text' : 'Show full text'}</button>
      </div>
    </div>
  )
}

function ChangeRow({ c }: { c: AmendChange }) {
  const [open, setOpen] = useState(false)
  const Icon = fieldIcon(c)
  const shift = dateShift(c)
  const delta = shift ? (shift.days !== null ? fmtDays(shift.days) : 'new') : numericDelta(c)
  const deltaTone = shift?.kind === 'earlier' ? 'bg-rose-100 text-rose-800 ring-rose-300' : shift?.kind === 'later' ? 'bg-sky-100 text-sky-800 ring-sky-300' : 'bg-slate-100 text-slate-700 ring-slate-300'
  return (
    <li className="px-3 py-2.5">
      <div className="flex items-start gap-2.5">
        <span className={`mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-lg ${c.tier === 'action' ? 'bg-rose-50 text-rose-600' : c.tier === 'informational' ? 'bg-sky-50 text-sky-600' : 'bg-slate-100 text-slate-500'}`}><Icon size={15} /></span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{fieldLabel(c.field)}</span>
            {c.decidedBy === 'llm' && <Badge tone="amended"><Bot size={11} /> LLM</Badge>}
            <span className="ml-auto flex items-center gap-1.5">
              {c.quote && (
                <button onClick={() => setOpen((v) => !v)} className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${open ? 'bg-brand-50 text-brand-700 ring-brand-200' : 'text-slate-500 ring-slate-200 hover:bg-slate-50'}`} title="Show the filing text this comes from">
                  <Quote size={10} /> Source
                </button>
              )}
            </span>
          </div>
          {c.kind === 'text' && c.previous && c.current ? (
            <WordDiff before={c.previous} after={c.current} />
          ) : (
            <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-sm">
              {c.previous && <><span className="text-slate-400 line-through">{c.previous}</span><span className="text-slate-400">→</span></>}
              <span className="font-semibold text-navy-900">{c.current ?? '—'}</span>
              {delta && <span className={`rounded-full px-1.5 py-px text-[11px] font-semibold ring-1 ring-inset ${deltaTone}`}>{delta}</span>}
            </div>
          )}
          {open && c.quote && (
            <blockquote className="mt-2 rounded border-l-4 border-brand-500 bg-brand-50/50 p-2 text-xs leading-relaxed text-slate-700">
              “{c.quote}”{c.location && <div className="mt-0.5 text-slate-500">{c.location}</div>}
            </blockquote>
          )}
        </div>
      </div>
    </li>
  )
}

function Section({ title, right, children }: { title: string; right?: ReactNode; children: ReactNode }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</span>
        {right}
      </div>
      {children}
    </div>
  )
}

function Clients({ holders }: { holders: Amendment['holders'] }) {
  const owners = holders.filter((h) => !h.watchOnly)
  const max = Math.max(1, ...owners.map((h) => h.shares))
  const total = owners.reduce((n, h) => n + h.shares, 0)
  const watch = holders.filter((h) => h.watchOnly)
  return (
    <Section title="Affected clients (simulated)" right={<span className="flex items-center gap-1 text-xs text-slate-600"><Users size={13} /> {owners.length} holding · {total.toLocaleString('en-US')} shares</span>}>
      <ul className="space-y-1.5">
        {owners.map((h) => (
          <li key={h.client + h.ticker} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-2 text-xs">
            <span className="truncate font-medium text-navy-900">{h.client}</span>
            <span className="h-2 rounded-full bg-slate-100"><span className="block h-2 rounded-full bg-brand-500" style={{ width: `${(h.shares / max) * 100}%` }} /></span>
            <span className="tabular-nums text-slate-600">{h.shares.toLocaleString('en-US')} {h.ticker}</span>
          </li>
        ))}
      </ul>
      {watch.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
          Watchlist: {watch.map((h) => <Badge key={h.client + h.ticker}>{h.client} · {h.ticker}</Badge>)}
        </div>
      )}
    </Section>
  )
}

function NoticePreview({ item, text }: { item: Amendment; text: string }) {
  // Show the structured notice unless operations edited it, in which case show their text as written
  if (text !== noticeText(item) || !item.notice) return <pre className="whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 p-3 font-sans text-xs leading-relaxed text-slate-800">{text}</pre>
  return (
    <div className="overflow-hidden rounded-lg border border-slate-200">
      <div className="border-b border-slate-100 bg-slate-50 px-3 py-2 text-sm font-semibold text-navy-900">{item.notice.subject}</div>
      <ul className="space-y-1.5 px-3 py-2.5 text-xs leading-relaxed text-slate-700">
        {item.notice.lines.map((l, i) => <li key={i} className="flex gap-2"><span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-brand-500" />{l}</li>)}
      </ul>
      <div className="border-t border-slate-100 px-3 py-1.5 text-[11px] text-slate-500">Source: {item.notice.source}</div>
    </div>
  )
}

function ItemDrawer({ item, onClose }: { item: Amendment | null; onClose: () => void }) {
  const { events, toast } = useApp()
  const { decisions, decide, reopen } = useAmend()
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState('')
  const [checked, setChecked] = useState(false)
  const [rejecting, setRejecting] = useState(false)
  const [reason, setReason] = useState(REJECT_REASONS[0])
  const [approving, setApproving] = useState(false)
  const [forId, setForId] = useState<string | null>(null)
  if (!item) return null
  if (forId !== item.id) {
    setForId(item.id)
    setEditing(false)
    setDraft(noticeText(item))
    setChecked(false)
    setRejecting(false)
  }
  const decision = decisions[item.id]
  const status: ApprovalStatus = decision?.status ?? 'pending'
  const edited = draft !== noticeText(item)
  const event = events.find((e) => e.versions.some((v) => v.filing.accession === item.accession))
  const flagged = item.review.length > 0
  const shown = item.changes.filter((c) => c.tier !== 'log_only')
  const quiet = item.changes.filter((c) => c.tier === 'log_only')
  const shift = deadlineShift(item)

  return (
    <Drawer open onClose={onClose} title={`Amendment ${item.id}`} wide>
      <div className="space-y-5">
        <div>
          <div className="text-base font-semibold leading-snug text-navy-900">{item.title}</div>
          <div className="mt-0.5 text-xs text-slate-500">{item.form} · filed {fmtDate(item.filed)} · version {item.version}</div>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <span title={TIER_HINT[item.tier]}><Badge tone={TIER_TONE[item.tier]}>{TIER_LABEL[item.tier]}</Badge></span>
            <Badge>{ACTION_LABEL[item.action]}</Badge>
            <Badge tone="brand">{item.sector}</Badge>
            {sendable(item) && <Badge tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Badge>}
          </div>
        </div>

        {shift && <DateAlert item={item} shift={shift} />}

        {flagged && (
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-3">
            <div className="flex flex-wrap items-center gap-1.5">
              <AlertTriangle size={15} className="text-amber-700" />
              <span className="mr-1 text-sm font-semibold text-amber-900">Held for review</span>
              {item.review.map((r, i) => <span key={i} title={r.detail} className="rounded-full bg-white/70 px-2 py-0.5 text-xs font-medium text-amber-900 ring-1 ring-inset ring-amber-300">{CHECK_LABEL[r.code] ?? r.code}</span>)}
            </div>
            <details className="mt-1.5 text-xs text-amber-900">
              <summary className="cursor-pointer text-amber-800">Details</summary>
              <ul className="mt-1 space-y-0.5">{item.review.map((r, i) => <li key={i}>{r.detail}</li>)}</ul>
            </details>
          </div>
        )}

        <Section title={`What changed (${shown.length || 0})`}>
          {shown.length === 0 ? (
            <p className="rounded-lg bg-slate-50 p-3 text-sm text-slate-600">{item.why}.</p>
          ) : (
            <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">{shown.map((c) => <ChangeRow key={c.field} c={c} />)}</ul>
          )}
          {(quiet.length > 0 || item.restated.length > 0) && (
            <div className="mt-2 flex flex-wrap items-center gap-1 text-[11px] text-slate-500">
              {quiet.length > 0 && <><span>No effect on holders:</span>{quiet.map((c) => <span key={c.field} className="rounded bg-slate-100 px-1.5 py-0.5">{fieldLabel(c.field)}</span>)}</>}
              {item.restated.length > 0 && <span className="ml-1" title={item.restated.map(fieldLabel).join(', ')}>· {item.restated.length} field{item.restated.length === 1 ? '' : 's'} restated unchanged</span>}
            </div>
          )}
        </Section>

        {item.holders.length > 0 && <Clients holders={item.holders} />}

        {item.notice && (
          <Section
            title={`Draft notice${edited ? ' (edited)' : ''}`}
            right={status === 'pending' && !editing && <Button size="sm" variant="ghost" onClick={() => setEditing(true)}><Pencil size={13} /> Edit</Button>}
          >
            {editing ? (
              <>
                <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={9} className="w-full rounded-lg border border-slate-300 p-3 font-mono text-xs leading-relaxed focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100" />
                <div className="mt-1.5 flex gap-2">
                  <Button size="sm" variant="primary" onClick={() => setEditing(false)}>Save edits</Button>
                  <Button size="sm" onClick={() => { setDraft(noticeText(item)); setEditing(false) }}>Discard</Button>
                </div>
              </>
            ) : (
              <NoticePreview item={item} text={decision?.notice ?? draft} />
            )}
            <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
              <Send size={12} />
              {item.notice.recipients.length ? item.notice.recipients.map((r) => <Badge key={r} tone="brand">{r}</Badge>) : 'No client holds this security'}
              {item.notice.watchers.length > 0 && <>· watchlist: {item.notice.watchers.map((r) => <Badge key={r}>{r}</Badge>)}</>}
            </div>
          </Section>
        )}

        <div className="border-t border-slate-100 pt-4">
          {!sendable(item) ? (
            <p className="text-sm text-slate-600">Nothing is sent for a log-only filing. It is kept with the event for the audit trail.</p>
          ) : status !== 'pending' ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-slate-50 p-3 text-sm">
              <span>
                <span className="font-semibold text-navy-900">{STATUS_LABEL[status]}</span> at {decision?.at}
                {decision?.edited ? ' · notice edited' : ''}{decision?.reason ? ` · ${decision.reason}` : ''}
              </span>
              <Button size="sm" onClick={() => { reopen(item.id, item.title); toast(`${item.id} reopened`) }}><RotateCcw size={13} /> Reopen</Button>
            </div>
          ) : rejecting ? (
            <div className="space-y-2">
              <label className="block text-xs font-medium text-slate-600">Why is this being rejected?</label>
              <select value={reason} onChange={(e) => setReason(e.target.value)} className="w-full rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm">
                {REJECT_REASONS.map((r) => <option key={r}>{r}</option>)}
              </select>
              <div className="flex gap-2">
                <Button variant="primary" onClick={() => { decide(item.id, item.title, { status: 'rejected', reason }, reason); toast(`${item.id} rejected: nothing sent`); setRejecting(false) }}><XCircle size={15} /> Reject</Button>
                <Button onClick={() => setRejecting(false)}>Cancel</Button>
              </div>
            </div>
          ) : (
            <>
              {flagged && (
                <label className="mb-3 flex items-start gap-2 text-sm text-slate-700">
                  <input type="checkbox" checked={checked} onChange={(e) => setChecked(e.target.checked)} className="mt-0.5" />
                  I have checked the flagged items against the filing.
                </label>
              )}
              <div className="flex flex-wrap gap-2">
                {item.notice ? (
                  <Button variant="primary" disabled={(flagged && !checked) || editing} onClick={() => setApproving(true)}><Send size={15} /> Approve and send</Button>
                ) : (
                  <Button variant="primary" disabled={flagged && !checked} onClick={() => { decide(item.id, item.title, { status: 'reviewed' }, 'Reviewed: no notice needed'); toast(`${item.id} marked reviewed`) }}><CheckCircle2 size={15} /> Mark reviewed</Button>
                )}
                <Button onClick={() => setRejecting(true)}><XCircle size={15} /> Reject</Button>
              </div>
              <p className="mt-2 text-xs text-slate-500">Nothing reaches a client until operations approves it.</p>
            </>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {event && <Link to={`/internal/events/${event.id}`}><Button size="sm"><FileText size={13} /> Corporate action record</Button></Link>}
            <a href={item.url} target="_blank" rel="noreferrer"><Button size="sm"><ExternalLink size={13} /> SEC EDGAR</Button></a>
          </div>
        </div>

        <details className="group rounded-lg border border-slate-200 p-3 text-sm">
          <summary className="flex cursor-pointer list-none items-center justify-between font-medium text-navy-900">
            How this was decided <ChevronDown size={15} className="text-slate-400 transition group-open:rotate-180" />
          </summary>
          <ol className="mt-3">
            {item.trace.map((t, i) => (
              <li key={t.step} className="relative flex gap-3 pb-3 last:pb-0">
                {i < item.trace.length - 1 && <span className="absolute left-[9px] top-5 h-[calc(100%-1rem)] w-px bg-slate-200" />}
                <span className="relative z-10 grid h-[19px] w-[19px] shrink-0 place-items-center rounded-full bg-brand-50 text-brand-700 ring-1 ring-brand-200"><Check size={11} /></span>
                <div className="text-xs"><div className="font-medium text-slate-800">{t.step}</div><div className="text-slate-500">{t.detail}</div></div>
              </li>
            ))}
          </ol>
        </details>
      </div>

      {approving && (
        <ApprovalRun
          item={item}
          edited={edited}
          onDone={() => {
            setApproving(false)
            decide(item.id, item.title, { status: 'approved', notice: draft, edited },
              `${item.notice?.recipients.length ? `Notice to ${item.notice.recipients.join(', ')}` : 'Notice filed with the event'}${edited ? ' (edited)' : ''}`)
            toast(`${item.id} approved`)
          }}
        />
      )}
    </Drawer>
  )
}

/* ---------- Queue ---------- */

type View = 'queue' | 'decided' | 'all'
type DateFilter = 'all' | 'any' | ShiftKind

const SHIFTS = new Map(items.map((a) => [a.id, deadlineShift(a)]))

function DateAlerts({ base, value, onChange }: { base: Amendment[]; value: DateFilter; onChange: (v: DateFilter) => void }) {
  const tiles = (['earlier', 'later', 'set', 'stale'] as ShiftKind[]).map((k) => {
    const hit = base.filter((a) => SHIFTS.get(a.id)?.kind === k)
    return { k, n: hit.length, clients: hit.filter((a) => a.holders.some((h) => !h.watchOnly)).length }
  })
  const desc: Record<ShiftKind, string> = { earlier: 'Deadlines moved earlier', later: 'Deadlines extended', set: 'Deadlines set for the first time', stale: 'New date is before the filing: check' }
  const ring: Record<ShiftKind, string> = { earlier: 'border-rose-300 bg-rose-50', later: 'border-sky-200 bg-sky-50', set: 'border-slate-200 bg-slate-50', stale: 'border-amber-200 bg-amber-50' }
  const num: Record<ShiftKind, string> = { earlier: 'text-rose-700', later: 'text-sky-700', set: 'text-slate-700', stale: 'text-amber-700' }
  return (
    <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {tiles.map(({ k, n, clients }) => {
        const st = SHIFT_STYLE[k]
        const active = value === k
        return (
          <button
            key={k}
            onClick={() => onChange(active ? 'all' : k)}
            className={`flex items-center gap-3 rounded-xl border p-3 text-left transition hover:shadow-sm ${ring[k]} ${active ? 'ring-2 ring-navy-900/70' : ''} ${k === 'earlier' && n > 0 ? 'shadow-[0_0_0_1px_rgba(225,29,72,0.15)]' : ''}`}
          >
            <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-white ${num[k]}`}><st.icon size={18} /></span>
            <span className="min-w-0">
              <span className={`block text-2xl font-semibold leading-none tabular-nums ${num[k]}`}>{n}</span>
              <span className="mt-1 block text-xs font-medium text-slate-700">{desc[k]}</span>
              <span className="block text-[11px] text-slate-500">{clients ? `${clients} reach our clients` : 'none reach our clients'}{active ? ' · showing' : ''}</span>
            </span>
          </button>
        )
      })}
    </div>
  )
}

function Chip({ active, muted, onClick, children }: { active: boolean; muted?: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button onClick={onClick} className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset transition ${active ? 'bg-navy-900 text-white ring-navy-900' : 'bg-white text-slate-700 ring-slate-300 hover:bg-slate-50'} ${muted && !active ? 'opacity-50' : ''}`}>
      {children}
    </button>
  )
}

export function AmendmentReview() {
  const { run, start, decisions, audit } = useAmend()
  const [view, setView] = useState<View>('queue')
  const [tier, setTier] = useState<'all' | AmendTier>('all')
  const [action, setAction] = useState<'all' | AmendAction>('all')
  const [sectors, setSectors] = useState<string[]>([])
  const [dates, setDates] = useState<DateFilter>('all')
  const [clientsOnly, setClientsOnly] = useState(false)
  const [q, setQ] = useState('')
  const [shown, setShown] = useState(PAGE)
  const [selected, setSelected] = useState<Amendment | null>(null)
  const statusOf = (a: Amendment): ApprovalStatus => decisions[a.id]?.status ?? 'pending'

  // Every filter except sector and date, so the chips and alert tiles can show counts for what they would add
  const base = useMemo(
    () =>
      items.filter(
        (a) =>
          (view === 'all' || (view === 'queue' ? sendable(a) && statusOf(a) === 'pending' : statusOf(a) !== 'pending')) &&
          (tier === 'all' || a.tier === tier) &&
          (action === 'all' || a.action === action) &&
          (!clientsOnly || a.holders.length > 0) &&
          a.title.toLowerCase().includes(q.toLowerCase()),
      ),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [view, tier, action, clientsOnly, q, decisions],
  )
  const inSector = (a: Amendment) => sectors.length === 0 || sectors.includes(a.sector)
  const inDates = (a: Amendment) => dates === 'all' || (dates === 'any' ? !!SHIFTS.get(a.id) : SHIFTS.get(a.id)?.kind === dates)
  const rows = useMemo(
    () =>
      base.filter((a) => inSector(a) && inDates(a)).sort((x, y) => {
        // Deadlines moved earlier first: the costliest thing to miss
        const e = Number(SHIFTS.get(y.id)?.kind === 'earlier') - Number(SHIFTS.get(x.id)?.kind === 'earlier')
        return e || y.filed.localeCompare(x.filed)
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [base, sectors, dates],
  )
  const sectorCounts = useMemo(() => {
    const m = new Map<string, number>()
    base.filter(inDates).forEach((a) => m.set(a.sector, (m.get(a.sector) ?? 0) + 1))
    return m
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [base, dates])
  const awaiting = items.filter((a) => a.notice && statusOf(a) === 'pending').length
  const reset = () => setShown(PAGE)
  const toggleSector = (s: string) => { setSectors((cur) => (cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s])); reset() }
  const s = amendData.summary
  const select = 'rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm'

  return (
    <>
      <PageHeader
        title="Amendment Review"
        subtitle="When a later filing changes a corporate action, the agent works out what changed, whether holders need to know and who holds the security, then drafts a notice. Nothing is sent until operations approves it."
        actions={
          <Button variant="primary" onClick={start} disabled={run.running}>
            {run.running ? <Loader2 size={15} className="animate-spin" /> : <FileDiff size={15} />}
            {run.hasRun ? 'Run again' : 'Check for amendments'}
          </Button>
        }
      />

      {!run.hasRun ? (
        <Card>
          <div className="px-6 py-10 text-center">
            <div className="mx-auto grid h-11 w-11 place-items-center rounded-full bg-brand-50 text-brand-700"><FileDiff size={20} /></div>
            <h2 className="mt-3 text-base font-semibold text-navy-900">No amendment check has been run yet</h2>
            <p className="mx-auto mt-1 max-w-xl text-sm text-slate-600">
              The agent compares every filing with the version of the event before it. Rules decide dates, prices, ratios and status; the LLM only judges changed wording, and must quote it. Anything unusual is held for a person.
            </p>
            <div className="mt-4 text-xs text-slate-500">Tender offers · Mergers · Rights offerings</div>
            <Button variant="primary" className="mt-5" onClick={start}><FileDiff size={15} /> Check for amendments</Button>
          </div>
        </Card>
      ) : (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              { label: 'Later filings checked', value: s.amendments },
              { label: 'Action needed', value: s.by_tier.action },
              { label: 'Held for review', value: s.held_for_review },
              { label: 'Notices awaiting approval', value: awaiting },
            ].map((x) => (
              <Card key={x.label} className="p-4">
                <div className="text-xs font-medium text-slate-500">{x.label}</div>
                <div className="mt-1.5 text-2xl font-semibold tabular-nums text-navy-900">{x.value}</div>
              </Card>
            ))}
          </div>

          <DateAlerts base={base.filter(inSector)} value={dates} onChange={(v) => { setDates(v); reset() }} />

          <Card>
            <CardHeader
              title="Amendment queue"
              subtitle={`${rows.length} filing${rows.length === 1 ? '' : 's'}${dates !== 'all' || sectors.length ? ' (filtered)' : ''}`}
              action={
                <div className="flex flex-wrap items-center gap-2">
                  <SearchInput value={q} onChange={(v) => { setQ(v); reset() }} placeholder="Search event…" />
                  <select value={tier} onChange={(e) => { setTier(e.target.value as typeof tier); reset() }} className={select} aria-label="Tier">
                    <option value="all">All tiers</option>
                    {(Object.keys(TIER_LABEL) as AmendTier[]).map((t) => <option key={t} value={t}>{TIER_LABEL[t]}</option>)}
                  </select>
                  <select value={dates} onChange={(e) => { setDates(e.target.value as DateFilter); reset() }} className={select} aria-label="Date changes">
                    <option value="all">All filings</option>
                    <option value="any">Any deadline change</option>
                    <option value="earlier">Deadline moved earlier</option>
                    <option value="later">Deadline extended</option>
                    <option value="set">Deadline set</option>
                    <option value="stale">Date before filing</option>
                  </select>
                  <select value={action} onChange={(e) => { setAction(e.target.value as typeof action); reset() }} className={select} aria-label="Event type">
                    <option value="all">All event types</option>
                    {(Object.keys(ACTION_LABEL) as AmendAction[]).map((t) => <option key={t} value={t}>{ACTION_LABEL[t]}</option>)}
                  </select>
                  <Segmented value={view} onChange={(v) => { setView(v); reset() }} options={[{ id: 'queue', label: 'Awaiting decision' }, { id: 'decided', label: 'Decided' }, { id: 'all', label: 'All' }]} />
                  <span className="flex items-center gap-2 text-sm text-slate-600">
                    <Toggle checked={clientsOnly} onChange={(v) => { setClientsOnly(v); reset() }} label="Reaches our clients" /> Reaches our clients
                  </span>
                </div>
              }
            />
            <div className="flex flex-wrap items-center gap-1.5 border-b border-slate-100 px-5 py-3">
              <span className="mr-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Sector</span>
              <Chip active={sectors.length === 0} onClick={() => { setSectors([]); reset() }}>All</Chip>
              {SECTORS.map((sec) => {
                const n = sectorCounts.get(sec) ?? 0
                return (
                  <Chip key={sec} active={sectors.includes(sec)} muted={n === 0} onClick={() => toggleSector(sec)}>
                    {sec} <span className={`tabular-nums ${sectors.includes(sec) ? 'text-white/70' : 'text-slate-400'}`}>{n}</span>
                  </Chip>
                )
              })}
            </div>
            {rows.length === 0 ? (
              <Empty>No filings match the current filters.</Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>{['Filed', 'Event', 'What changed', 'Tier', 'Checks', 'Clients', 'Status'].map((h) => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}</tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {rows.slice(0, shown).map((a) => {
                      const shift = SHIFTS.get(a.id)
                      return (
                        <tr key={a.id} onClick={() => setSelected(a)} className={`cursor-pointer hover:bg-brand-50/50 ${shift?.kind === 'earlier' ? 'bg-rose-50/40' : ''}`}>
                          <td className={`whitespace-nowrap px-4 py-3 text-slate-600 ${shift?.kind === 'earlier' ? 'shadow-[inset_4px_0_0_#e11d48]' : ''}`}>{fmtDate(a.filed)}<div className="text-xs text-slate-400">{a.form}</div></td>
                          <td className="max-w-[240px] px-4 py-3"><div className="truncate font-medium text-navy-900">{a.title}</div><div className="text-xs text-slate-500">{ACTION_LABEL[a.action]} · {a.sector}</div></td>
                          <td className="max-w-[320px] px-4 py-3 text-slate-700">
                            {shift ? (
                              <div className="truncate"><DateChip shift={shift} /></div>
                            ) : (
                              <div className="truncate">
                                {headlineChange(a)?.decidedBy === 'llm' && <Bot size={13} className="mr-1 inline text-violet-600" />}
                                {changeSummary(a)}
                              </div>
                            )}
                          </td>
                          <td className="px-4 py-3"><Badge tone={TIER_TONE[a.tier]}>{TIER_LABEL[a.tier]}</Badge></td>
                          <td className="px-4 py-3">{a.review.length ? <Badge tone="pending"><AlertTriangle size={11} /> {a.review.length}</Badge> : <span className="text-slate-400">–</span>}</td>
                          <td className="px-4 py-3 tabular-nums text-slate-700">{a.notice?.recipients.length || <span className="text-slate-400">–</span>}</td>
                          <td className="px-4 py-3">{sendable(a) ? <Badge tone={STATUS_TONE[statusOf(a)]}>{STATUS_LABEL[statusOf(a)]}</Badge> : <span className="text-xs text-slate-400">Logged</span>}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
            <ShowMore shown={shown} total={rows.length} onMore={() => setShown((n) => n + PAGE)} />
          </Card>

          <Card className="mt-6">
            <CardHeader title="Audit log" subtitle="Every decision in this session, with who made it and when" />
            {audit.length === 0 ? (
              <Empty>No decisions yet. Open a filing in the queue to approve, edit or reject its notice.</Empty>
            ) : (
              <ul className="divide-y divide-slate-100 text-sm">
                {audit.map((e) => (
                  <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-2.5">
                    <span><span className="font-medium text-navy-900">{e.action}</span> · {e.itemId} · {e.title}</span>
                    <span className="text-xs text-slate-500">{e.detail} · you (operations) · {e.at}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </>
      )}

      <RunPanel />
      <ItemDrawer item={selected} onClose={() => setSelected(null)} />
    </>
  )
}
