import { AlertTriangle, ArrowRight, CheckCircle2, ChevronDown, ExternalLink, FileText, Info, Mail, ShieldCheck, Workflow } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Badge, Button, Card, CardHeader, Drawer, Empty, Modal, PageHeader, Segmented, type Tone } from '../../components/ui'
import { briefData, dueLabel, periodLabel, TIER_ORDER, TIER_TITLE, type BriefAction, type BriefItem, type Tier } from '../../data/briefs'
import { fmtDate } from '../../data/store'
import { useBrief } from '../../state/BriefState'

const TIER_TONE: Record<Tier, Tone> = { action: 'review', changed: 'amended', new: 'new', completed: 'completed', upcoming: 'neutral' }
const STAT_STYLE: Record<Tier, string> = {
  action: 'text-rose-700',
  changed: 'text-violet-700',
  new: 'text-sky-700',
  completed: 'text-emerald-700',
  upcoming: 'text-slate-600',
}

type Filter = 'all' | BriefAction

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: { id: string; label: string }[] }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-slate-500">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-navy-900 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100"
      >
        {options.map((o) => (
          <option key={o.id} value={o.id}>{o.label}</option>
        ))}
      </select>
    </label>
  )
}

function DeadlinePanel({ item }: { item: BriefItem }) {
  const { deadline, cutoff } = item
  if (!deadline) return null
  if (item.tier === 'action' && cutoff) {
    return (
      <div className={`w-full shrink-0 rounded-lg px-4 py-3 sm:w-56 ${cutoff.passed ? 'bg-rose-50 ring-1 ring-inset ring-rose-200' : 'bg-navy-50'}`}>
        <div className={`text-xs font-medium ${cutoff.passed ? 'text-rose-700' : 'text-slate-500'}`}>
          {cutoff.passed ? 'BNY cut-off passed' : 'Instructions due to BNY'}
        </div>
        <div className={`text-lg font-semibold ${cutoff.passed ? 'text-rose-800' : 'text-navy-900'}`}>{cutoff.display}</div>
        <div className={`text-xs ${cutoff.passed ? 'text-rose-700' : 'text-slate-600'}`}>{dueLabel(cutoff.daysAway)}</div>
        <div className="mt-2 border-t border-slate-200/70 pt-2 text-xs text-slate-600">
          {deadline.label}: <span className="font-medium text-slate-800">{deadline.display}</span>
        </div>
      </div>
    )
  }
  return (
    <div className="w-full shrink-0 rounded-lg bg-slate-50 px-4 py-3 sm:w-56">
      <div className="text-xs font-medium text-slate-500">{deadline.label}</div>
      <div className="text-base font-semibold text-navy-900">{deadline.display}</div>
      <div className="text-xs text-slate-600">{dueLabel(deadline.daysAway)}</div>
    </div>
  )
}

function ImpactTable({ item }: { item: BriefItem }) {
  const { lines, caveats, reason } = item.impact
  if (!lines.length && !reason) return null
  return (
    <div className="mt-4">
      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {item.position.watchOnly ? 'Your position' : `What this means for your ${item.position.shares.toLocaleString('en-US')} shares`}
      </h4>
      {lines.length > 0 && (
        <div className="overflow-hidden rounded-lg border border-slate-200">
          <table className="w-full text-sm">
            <tbody className="divide-y divide-slate-100">
              {lines.map((l) => (
                <tr key={l.label}>
                  <th scope="row" className="w-[42%] px-3 py-2 text-left font-normal text-slate-600">{l.label}</th>
                  <td className="whitespace-nowrap px-3 py-2 font-semibold tabular-nums text-navy-900">{l.value}</td>
                  <td className="hidden px-3 py-2 text-xs text-slate-500 md:table-cell">{l.formula}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {reason && <p className="text-sm text-slate-600">{reason}</p>}
      {caveats.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-slate-500">
          {caveats.map((c) => (
            <li key={c} className="flex gap-1.5"><Info size={12} className="mt-0.5 shrink-0" /> {c}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function SourceDrawer({ item, onClose }: { item: BriefItem | null; onClose: () => void }) {
  if (!item) return null
  const quoted = item.evidence.filter((e) => e.quote)
  const latest = item.sources[item.sources.length - 1]
  return (
    <Drawer open onClose={onClose} title="Source evidence">
      <p className="text-sm font-medium text-navy-900">{item.title}</p>
      <p className="mt-1 text-xs text-slate-500">
        Every value below comes from the SEC filing shown. {item.sources.length} filing{item.sources.length > 1 ? 's' : ''} linked to this event.
      </p>
      <ul className="mt-4 space-y-4">
        {quoted.map((e) => (
          <li key={e.key} className="border-t border-slate-100 pt-3">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{e.label}</span>
              <span className="text-right text-sm font-semibold text-navy-900">{e.value}</span>
            </div>
            <blockquote className="mt-2 rounded-lg bg-slate-50 px-3 py-2 text-sm leading-relaxed text-slate-700">“{e.quote}”</blockquote>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-slate-500">
              <span>{e.form} · filed {fmtDate(e.filed)}{e.location ? ` · ${e.location}` : ''}</span>
              {e.verified && <span className="inline-flex items-center gap-1 text-emerald-700"><CheckCircle2 size={12} /> Found in filing</span>}
              <a href={e.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 font-medium text-brand-700 hover:underline">
                SEC.gov <ExternalLink size={11} />
              </a>
            </div>
          </li>
        ))}
        {!quoted.length && <li className="text-sm text-slate-500">No quotes were captured for this event.</li>}
      </ul>
      <h4 className="mt-6 text-xs font-semibold uppercase tracking-wide text-slate-500">Linked filings</h4>
      <ul className="mt-2 divide-y divide-slate-100 text-sm">
        {[...item.sources].reverse().map((s) => (
          <li key={s.accession} className="flex items-center justify-between gap-3 py-2">
            <span>
              <span className="font-medium text-navy-900">{s.form}</span>
              <span className="text-slate-500"> · {fmtDate(s.filed)}{s === latest ? ' · latest' : ''}</span>
            </span>
            <a href={s.url} target="_blank" rel="noreferrer" aria-label={`Open ${s.form} on SEC.gov`} className="text-brand-700 hover:text-brand-800"><ExternalLink size={14} /></a>
          </li>
        ))}
      </ul>
    </Drawer>
  )
}

function ItemCard({ item, onSource }: { item: BriefItem; onSource: (i: BriefItem) => void }) {
  const [open, setOpen] = useState(false)
  return (
    <Card>
      <div className="p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge tone={TIER_TONE[item.tier]}>{item.tierLabel}</Badge>
              <Badge tone="brand">{item.actionLabel}</Badge>
              <Badge>{item.ticker}</Badge>
              <span className="text-xs text-slate-500">{item.status}</span>
              {item.review.needed && <Badge tone="completed"><ShieldCheck size={11} /> Reviewed by BNY Operations</Badge>}
            </div>
            <h3 className="mt-2 text-base font-semibold text-navy-900">{item.title}</h3>
            <p className="mt-1 text-sm leading-relaxed text-slate-700">{item.summary}</p>
          </div>
          <DeadlinePanel item={item} />
        </div>

        {item.cutoff?.passed && item.tier === 'action' && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-900">
            <AlertTriangle size={15} className="mt-0.5 shrink-0" />
            BNY's cut-off for this event has passed. Contact your relationship manager about late instructions.
          </div>
        )}

        {item.changes.length > 0 && (
          <div className="mt-4 rounded-lg bg-violet-50/60 px-3 py-2.5">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-violet-800">What changed</h4>
            <ul className="mt-1 space-y-0.5 text-sm text-slate-800">
              {item.changes.map((c) => (
                <li key={c.label + c.filed} className="flex flex-wrap items-center gap-x-1.5">
                  <ArrowRight size={13} className="text-violet-500" /> {c.text}
                  <span className="text-xs text-slate-500">({c.form}, {fmtDate(c.filed)})</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <ImpactTable item={item} />

        {open && (
          <div className="mt-4 border-t border-slate-100 pt-4">
            {item.options && (
              <div className="mb-3">
                <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Options described in the filing</h4>
                <p className="mt-1 text-sm text-slate-700">{item.options.split(' | ').join(' · ')}</p>
              </div>
            )}
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Terms as stated</h4>
            <dl className="mt-1 divide-y divide-slate-100">
              {item.terms.map((t) => (
                <div key={t.label} className="grid gap-1 py-2 sm:grid-cols-[10rem_1fr] sm:gap-3">
                  <dt className="text-sm text-slate-500">{t.label}</dt>
                  <dd className="text-sm text-slate-800">{t.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => onSource(item)}><FileText size={13} /> View source</Button>
          <Button size="sm" variant="ghost" onClick={() => setOpen(!open)} aria-expanded={open}>
            <ChevronDown size={13} className={`transition-transform ${open ? 'rotate-180' : ''}`} /> {open ? 'Hide' : 'Show'} all terms
          </Button>
          <span className="ml-auto text-xs text-slate-500">Latest filing {item.sources[item.sources.length - 1].form}, {fmtDate(item.latestFiled)}</span>
        </div>
      </div>
    </Card>
  )
}

function HorizonRow({ item, onSource }: { item: BriefItem; onSource: (i: BriefItem) => void }) {
  const [open, setOpen] = useState(false)
  const key = item.impact.lines[0]
  return (
    <li>
      <button onClick={() => setOpen(!open)} aria-expanded={open} className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3 text-left hover:bg-slate-50">
        <ChevronDown size={15} className={`shrink-0 text-slate-400 transition-transform ${open ? 'rotate-180' : ''}`} />
        <span className="min-w-0 flex-1 basis-60">
          <span className="block truncate text-sm font-medium text-navy-900">{item.title}</span>
          <span className="block text-xs text-slate-500">{item.ticker} · {item.actionLabel} · {item.status}{item.position.watchOnly ? ' · Watchlist' : ''}</span>
        </span>
        {key && <span className="text-sm font-semibold tabular-nums text-navy-900">{key.value}</span>}
        <span className="w-48 text-right text-xs text-slate-500">{item.deadline ? `${item.deadline.label} ${item.deadline.display}` : item.stageNote ?? 'No date set yet'}</span>
      </button>
      {open && <div className="border-t border-slate-100 bg-slate-50/60 p-3"><ItemCard item={item} onSource={onSource} /></div>}
    </li>
  )
}

function EmailPreview({ open, onClose, items }: { open: boolean; onClose: () => void; items: BriefItem[] }) {
  const { client, asOf, cadence, brief } = useBrief()
  return (
    <Modal open={open} onClose={onClose} wide title="Email preview">
      <div className="max-h-[70vh] overflow-y-auto px-6 py-5 text-sm text-slate-800">
        <div className="mb-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">Preview only. Nothing is sent from this demo.</div>
        <div className="border-b border-slate-200 pb-3 text-xs text-slate-500">
          <div><span className="font-medium text-slate-700">To:</span> {client.name}</div>
          <div><span className="font-medium text-slate-700">Subject:</span> Your {cadence} corporate actions brief, {periodLabel(asOf, brief?.lookbackDays ?? 7)}</div>
        </div>
        {items.filter((i) => i.tier !== 'upcoming').map((i) => (
          <div key={i.id} className="border-b border-slate-100 py-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{i.tierLabel}</div>
            <div className="mt-0.5 font-semibold text-navy-900">{i.title} ({i.ticker})</div>
            <p className="mt-1 leading-relaxed">{i.summary}</p>
            <a href={i.sources[i.sources.length - 1].url} target="_blank" rel="noreferrer" className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline">
              Source: {i.sources[i.sources.length - 1].form} <ExternalLink size={11} />
            </a>
          </div>
        ))}
        <p className="pt-3 text-xs text-slate-500">
          {items.filter((i) => i.tier === 'upcoming').length} more events on the horizon are in your portal. This brief provides information from public filings and is not investment advice.
        </p>
      </div>
    </Modal>
  )
}

export function ClientBrief() {
  const { client, setClientId, asOf, setAsOf, cadence, setCadence, brief, visibleItems, heldCount } = useBrief()
  const [filter, setFilter] = useState<Filter>('all')
  const [source, setSource] = useState<BriefItem | null>(null)
  const [emailOpen, setEmailOpen] = useState(false)
  const [traceOpen, setTraceOpen] = useState(false)

  const items = useMemo(() => visibleItems.filter((i) => filter === 'all' || i.action === filter), [visibleItems, filter])
  const count = (t: Tier) => visibleItems.filter((i) => i.tier === t).length

  return (
    <>
      <PageHeader
        eyebrow="Your corporate actions brief"
        title={client.name}
        subtitle={`${cadence === 'weekly' ? 'Weekly' : 'Daily'} brief · ${periodLabel(asOf, brief?.lookbackDays ?? 7)}`}
        actions={<Button onClick={() => setEmailOpen(true)}><Mail size={15} /> Email preview</Button>}
      />

      <div className="mb-3 flex flex-wrap items-end gap-3">
        <Select label="Client" value={client.id} onChange={setClientId} options={briefData.clients.map((c) => ({ id: c.id, label: c.name }))} />
        <Select label="Brief date" value={asOf} onChange={setAsOf} options={briefData.asOfDates.map((d) => ({ id: d, label: fmtDate(d) }))} />
        <div className="flex flex-col gap-1 text-xs font-medium text-slate-500">
          Frequency
          <Segmented value={cadence} onChange={setCadence} options={[{ id: 'weekly', label: 'Weekly' }, { id: 'daily', label: 'Daily' }]} />
        </div>
        <div className="flex flex-col gap-1 text-xs font-medium text-slate-500">
          Event type
          <Segmented<Filter> value={filter} onChange={setFilter} options={[{ id: 'all', label: 'All' }, ...briefData.actions]} />
        </div>
      </div>

      <div className="mb-3 flex items-start gap-2 rounded-lg bg-brand-50 px-3 py-2.5 text-sm text-navy-900">
        <ArrowRight size={15} className="mt-0.5 shrink-0 text-brand-700" />
        {count('action') > 0
          ? `Start with ${count('action') > 1 ? `the ${count('action')} items` : 'the item'} under Action needed. ${count('action') > 1 ? 'Each one shows' : 'It shows'} what it means for your shares and the date BNY needs your instruction. Use View source to see the filing behind any number.`
          : 'Nothing needs an instruction from you in this period. The items below are for information. Use View source to see the filing behind any number.'}
      </div>

      <p className="mb-5 flex items-start gap-1.5 text-xs text-slate-500">
        <Info size={13} className="mt-0.5 shrink-0" />
        Demo with simulated client positions. Terms come from SEC filings. BNY cut-offs are illustrative: {briefData.assumptions.cutoffBusinessDays} business days before the official deadline. Information only, not investment advice.
      </p>

      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        {TIER_ORDER.map((t) => (
          <Card key={t} className="px-4 py-3">
            <div className="text-xs font-medium text-slate-500">{TIER_TITLE[t]}</div>
            <div className={`mt-0.5 text-2xl font-semibold tabular-nums ${STAT_STYLE[t]}`}>{count(t)}</div>
          </Card>
        ))}
      </div>

      {heldCount > 0 && (
        <div className="mt-4 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <ShieldCheck size={16} className="mt-0.5 shrink-0" />
          {heldCount} item{heldCount > 1 ? 's are' : ' is'} with BNY Operations for review and will appear here once cleared.
        </div>
      )}

      {items.length === 0 && <Card className="mt-6"><Empty>Nothing to report for this client in this period.</Empty></Card>}

      {TIER_ORDER.filter((t) => t !== 'upcoming').map((t) => {
        const rows = items.filter((i) => i.tier === t)
        if (!rows.length) return null
        return (
          <section key={t} className="mt-6">
            <h2 className="mb-3 text-sm font-semibold text-navy-900">{TIER_TITLE[t]} <span className="font-normal text-slate-500">({rows.length})</span></h2>
            <div className="space-y-3">
              {rows.map((i) => <ItemCard key={i.id} item={i} onSource={setSource} />)}
            </div>
          </section>
        )
      })}

      {items.some((i) => i.tier === 'upcoming') && (
        <section className="mt-6">
          <h2 className="mb-3 text-sm font-semibold text-navy-900">{TIER_TITLE.upcoming} <span className="font-normal text-slate-500">({items.filter((i) => i.tier === 'upcoming').length})</span></h2>
          <Card>
            <ul className="divide-y divide-slate-100">
              {items.filter((i) => i.tier === 'upcoming').map((i) => <HorizonRow key={i.id} item={i} onSource={setSource} />)}
            </ul>
          </Card>
        </section>
      )}

      {brief && (
        <section className="mt-6">
          <Card>
            <button onClick={() => setTraceOpen(!traceOpen)} aria-expanded={traceOpen} className="flex w-full items-center gap-2 px-5 py-3.5 text-left">
              <Workflow size={16} className="text-brand-700" />
              <span className="flex-1 text-sm font-semibold text-navy-900">How this brief was built</span>
              <ChevronDown size={15} className={`text-slate-400 transition-transform ${traceOpen ? 'rotate-180' : ''}`} />
            </button>
            {traceOpen && (
              <>
                <CardHeader title="Agent run log" subtitle="Every step is recorded so a brief can be audited later." />
                <ol className="divide-y divide-slate-100">
                  {brief.trace.map((t, n) => (
                    <li key={t.step} className="flex gap-3 px-5 py-3">
                      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-navy-800 text-xs font-semibold text-white">{n + 1}</span>
                      <div>
                        <div className="text-sm font-medium text-navy-900">{t.step}</div>
                        <div className="text-sm text-slate-600">{t.detail}</div>
                      </div>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </Card>
        </section>
      )}

      <SourceDrawer item={source} onClose={() => setSource(null)} />
      <EmailPreview open={emailOpen} onClose={() => setEmailOpen(false)} items={visibleItems} />
    </>
  )
}
