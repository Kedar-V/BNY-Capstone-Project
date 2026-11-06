import { AlertTriangle, Bot, Check, CheckCircle2, ExternalLink, FileDiff, FileText, Loader2, Pencil, RotateCcw, Send, XCircle } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, CardHeader, Drawer, Empty, Modal, PageHeader, SearchInput, Segmented, ShowMore, Toggle, type Tone } from '../../components/ui'
import {
  ACTION_LABEL, amendData, changeSummary, headlineChange, CHECK_LABEL, fieldLabel, noticeText, recordUpdates, REJECT_REASONS, TIER_HINT, TIER_LABEL,
  type AmendAction, type Amendment, type AmendTier, type ApprovalStatus,
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

  return (
    <Drawer open onClose={onClose} title={`Amendment ${item.id}`} wide>
      <div className="space-y-5">
        <div>
          <div className="text-sm font-semibold text-navy-900">{item.title}</div>
          <div className="mt-0.5 text-xs text-slate-500">{item.form} filed {fmtDate(item.filed)} · version {item.version} of the event</div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Badge tone={TIER_TONE[item.tier]}>{TIER_LABEL[item.tier]}</Badge>
            <Badge>{ACTION_LABEL[item.action]}</Badge>
            {sendable(item) && <Badge tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Badge>}
          </div>
          <p className="mt-2 text-sm text-slate-600">{TIER_HINT[item.tier]}</p>
        </div>

        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">What changed</div>
          {shown.length === 0 && <p className="text-sm text-slate-600">{item.why}.</p>}
          <div className="space-y-2.5">
            {shown.map((c) => (
              <div key={c.field} className="rounded-lg border border-slate-200 p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-semibold text-navy-900">{fieldLabel(c.field)}</span>
                  <span className="flex items-center gap-1.5">
                    {c.decidedBy === 'llm' && <Badge tone="amended"><Bot size={11} /> LLM judged</Badge>}
                    <Badge tone={TIER_TONE[c.tier]}>{TIER_LABEL[c.tier]}</Badge>
                  </span>
                </div>
                {c.kind === 'text' ? (
                  <div className="mt-2 grid gap-2 text-xs">
                    <div className="rounded bg-slate-50 p-2 text-slate-600"><span className="font-medium text-slate-500">Before: </span>{c.previous}</div>
                    <div className="rounded bg-brand-50/60 p-2 text-slate-800"><span className="font-medium text-slate-500">Now: </span>{c.current}</div>
                  </div>
                ) : (
                  <div className="mt-1.5 text-sm">
                    {c.previous && <><span className="text-slate-500 line-through">{c.previous}</span><span className="mx-1.5 text-slate-400">→</span></>}
                    <span className="font-semibold text-navy-900">{c.current}</span>
                  </div>
                )}
                <div className="mt-1.5 text-xs text-slate-500">{c.reason}</div>
                {c.quote && (
                  <blockquote className="mt-2 rounded border-l-4 border-brand-500 bg-brand-50/50 p-2 text-xs leading-relaxed text-slate-700">
                    “{c.quote}”{c.location && <div className="mt-0.5 text-slate-500">{c.location}</div>}
                  </blockquote>
                )}
              </div>
            ))}
          </div>
          {quiet.length > 0 && <p className="mt-2 text-xs text-slate-500">Also in this filing, no effect on holders: {quiet.map((c) => fieldLabel(c.field)).join(', ')}.</p>}
          {item.restated.length > 0 && <p className="mt-1 text-xs text-slate-500">Restated with no change: {item.restated.map(fieldLabel).join(', ')}.</p>}
        </div>

        {flagged && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
            <div className="flex items-center gap-1.5 text-sm font-semibold text-amber-900"><AlertTriangle size={15} /> Held for review</div>
            <ul className="mt-1.5 space-y-1 text-xs text-amber-900">
              {item.review.map((r, i) => <li key={i}><span className="font-medium">{CHECK_LABEL[r.code] ?? r.code}.</span> {r.detail}</li>)}
            </ul>
          </div>
        )}

        {item.holders.length > 0 && (
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Affected clients (simulated positions)</div>
            <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 text-sm">
              {item.holders.map((h) => (
                <li key={h.client + h.ticker} className="flex items-center justify-between px-3 py-2">
                  <span className="font-medium text-navy-900">{h.client}</span>
                  <span className="text-slate-600">{h.ticker} · {h.watchOnly ? 'watchlist' : `${h.shares.toLocaleString('en-US')} shares`}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {item.notice && (
          <div>
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">Draft notice{edited ? ' (edited)' : ''}</span>
              {status === 'pending' && !editing && <Button size="sm" variant="ghost" onClick={() => setEditing(true)}><Pencil size={13} /> Edit</Button>}
            </div>
            {editing ? (
              <>
                <textarea value={draft} onChange={(e) => setDraft(e.target.value)} rows={9} className="w-full rounded-lg border border-slate-300 p-3 font-mono text-xs leading-relaxed focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100" />
                <div className="mt-1.5 flex gap-2">
                  <Button size="sm" variant="primary" onClick={() => setEditing(false)}>Save edits</Button>
                  <Button size="sm" onClick={() => { setDraft(noticeText(item)); setEditing(false) }}>Discard</Button>
                </div>
              </>
            ) : (
              <pre className="whitespace-pre-wrap rounded-lg border border-slate-200 bg-slate-50 p-3 font-sans text-xs leading-relaxed text-slate-800">{decision?.notice ?? draft}</pre>
            )}
            <p className="mt-1.5 text-xs text-slate-500">
              {item.notice.recipients.length ? `Goes to ${item.notice.recipients.join(', ')}` : 'No client holds this security'}
              {item.notice.watchers.length ? `; watchlist alert to ${item.notice.watchers.join(', ')}` : ''}. Values come from the record, not the LLM.
            </p>
          </div>
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
              <p className="mt-2 text-xs text-slate-500">Nothing reaches a client until operations approves it. Rejecting keeps the filing on record with the reason.</p>
            </>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {event && <Link to={`/internal/events/${event.id}`}><Button size="sm"><FileText size={13} /> Corporate action record</Button></Link>}
            <a href={item.url} target="_blank" rel="noreferrer"><Button size="sm"><ExternalLink size={13} /> SEC EDGAR</Button></a>
          </div>
        </div>

        <details className="rounded-lg border border-slate-200 p-3 text-sm">
          <summary className="cursor-pointer font-medium text-navy-900">How this was decided</summary>
          <ol className="mt-2 space-y-1 text-xs text-slate-600">
            {item.trace.map((t) => <li key={t.step}><span className="font-medium text-slate-800">{t.step}:</span> {t.detail}</li>)}
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

type View = 'queue' | 'decided' | 'all'

export function AmendmentReview() {
  const { run, start, decisions, audit } = useAmend()
  const [view, setView] = useState<View>('queue')
  const [tier, setTier] = useState<'all' | AmendTier>('all')
  const [action, setAction] = useState<'all' | AmendAction>('all')
  const [clientsOnly, setClientsOnly] = useState(false)
  const [q, setQ] = useState('')
  const [shown, setShown] = useState(PAGE)
  const [selected, setSelected] = useState<Amendment | null>(null)
  const statusOf = (a: Amendment): ApprovalStatus => decisions[a.id]?.status ?? 'pending'

  const rows = useMemo(
    () =>
      items
        .filter(
          (a) =>
            (view === 'all' || (view === 'queue' ? sendable(a) && statusOf(a) === 'pending' : statusOf(a) !== 'pending')) &&
            (tier === 'all' || a.tier === tier) &&
            (action === 'all' || a.action === action) &&
            (!clientsOnly || a.holders.length > 0) &&
            a.title.toLowerCase().includes(q.toLowerCase()),
        )
        .sort((x, y) => y.filed.localeCompare(x.filed)),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [view, tier, action, clientsOnly, q, decisions],
  )
  const awaiting = items.filter((a) => a.notice && statusOf(a) === 'pending').length
  const reset = () => setShown(PAGE)
  const s = amendData.summary

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

          <Card>
            <CardHeader
              title="Amendment queue"
              subtitle={`${rows.length} filing${rows.length === 1 ? '' : 's'}`}
              action={
                <div className="flex flex-wrap items-center gap-2">
                  <SearchInput value={q} onChange={(v) => { setQ(v); reset() }} placeholder="Search event…" />
                  <select value={tier} onChange={(e) => { setTier(e.target.value as typeof tier); reset() }} className="rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm" aria-label="Tier">
                    <option value="all">All tiers</option>
                    {(Object.keys(TIER_LABEL) as AmendTier[]).map((t) => <option key={t} value={t}>{TIER_LABEL[t]}</option>)}
                  </select>
                  <select value={action} onChange={(e) => { setAction(e.target.value as typeof action); reset() }} className="rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm" aria-label="Event type">
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
            {rows.length === 0 ? (
              <Empty>No filings match the current filters.</Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>{['Filed', 'Event', 'What changed', 'Tier', 'Checks', 'Clients', 'Status'].map((h) => <th key={h} className="px-4 py-2.5 font-medium">{h}</th>)}</tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {rows.slice(0, shown).map((a) => (
                      <tr key={a.id} onClick={() => setSelected(a)} className="cursor-pointer hover:bg-brand-50/50">
                        <td className="whitespace-nowrap px-4 py-3 text-slate-600">{fmtDate(a.filed)}<div className="text-xs text-slate-400">{a.form}</div></td>
                        <td className="max-w-[240px] px-4 py-3"><div className="truncate font-medium text-navy-900">{a.title}</div><div className="text-xs text-slate-500">{ACTION_LABEL[a.action]}</div></td>
                        <td className="max-w-[280px] truncate px-4 py-3 text-slate-700">
                          {headlineChange(a)?.decidedBy === 'llm' && <Bot size={13} className="mr-1 inline text-violet-600" />}
                          {changeSummary(a)}
                        </td>
                        <td className="px-4 py-3"><Badge tone={TIER_TONE[a.tier]}>{TIER_LABEL[a.tier]}</Badge></td>
                        <td className="px-4 py-3">{a.review.length ? <Badge tone="pending"><AlertTriangle size={11} /> {a.review.length}</Badge> : <span className="text-slate-400">–</span>}</td>
                        <td className="px-4 py-3 tabular-nums text-slate-700">{a.notice?.recipients.length || <span className="text-slate-400">–</span>}</td>
                        <td className="px-4 py-3">{sendable(a) ? <Badge tone={STATUS_TONE[statusOf(a)]}>{STATUS_LABEL[statusOf(a)]}</Badge> : <span className="text-xs text-slate-400">Logged</span>}</td>
                      </tr>
                    ))}
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
