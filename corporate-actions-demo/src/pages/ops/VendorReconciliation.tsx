import { Check, CheckCircle2, ExternalLink, FileText, GitCompare, Loader2, RotateCcw, XCircle } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, CardHeader, Drawer, Empty, Modal, PageHeader, SearchInput, Segmented, ShowMore, type Tone } from '../../components/ui'
import { describeGap, FIELD_LABEL, FILING_FIELD, formatValue, reconData, type Ticket, type TicketField, type TicketStatus } from '../../data/reconciliation'
import { fmtDate } from '../../data/store'
import { useApp } from '../../state/AppState'
import { useRecon } from '../../state/ReconState'

const PAGE = 20
const STATUS_TONE: Record<TicketStatus, Tone> = { open: 'pending', confirmed: 'review', dismissed: 'neutral' }
const STATUS_LABEL: Record<TicketStatus, string> = { open: 'Open', confirmed: 'Confirmed', dismissed: 'Dismissed' }
const vendorName = (id: string) => reconData.vendors.find((v) => v.id === id)?.name ?? id

function RunPanel() {
  const { run, close } = useRecon()
  const showBar = run.steps.some((s) => s.status === 'active' && ['normalize', 'match', 'compare'].includes(s.id))
  return (
    <Modal open={run.open} onClose={close} wide title={run.finished ? 'Reconciliation complete' : 'Reconciling vendor data with SEC filings'}>
      <div className="px-6 py-5">
        <ol>
          {run.steps.map((s, i) => (
            <li key={s.id} className="relative flex gap-4 pb-5 last:pb-0">
              {i < run.steps.length - 1 && <span className={`absolute left-[13px] top-7 h-[calc(100%-1.75rem)] w-0.5 transition-colors duration-500 ${s.status === 'done' ? 'bg-brand-500' : 'bg-slate-200'}`} />}
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
                {s.status === 'active' && showBar && (
                  <div className="fade-in mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full rounded-full bg-brand-500 transition-all duration-200" style={{ width: `${Math.round(run.progress * 100)}%` }} />
                  </div>
                )}
              </div>
            </li>
          ))}
        </ol>
      </div>
      <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50 px-6 py-3.5">
        <span className="text-xs text-slate-500">{run.running ? 'Comparing every vendor record with the filing it belongs to…' : `${reconData.tickets.length} discrepancies are ready for review.`}</span>
        <Button variant="primary" onClick={close} disabled={run.running}>{run.finished ? 'Review discrepancies' : 'Close'}</Button>
      </div>
    </Modal>
  )
}

function TicketDrawer({ ticket, onClose }: { ticket: Ticket | null; onClose: () => void }) {
  const { filings, events } = useApp()
  const { statuses, setStatus } = useRecon()
  const { toast } = useApp()
  if (!ticket) return null
  const status = statuses[ticket.id] ?? 'open'
  const filing = filings.find((f) => f.accession === ticket.accession)
  const quote = filing?.passages[FILING_FIELD[ticket.field]]?.[0]
  const event = events.find((e) => e.versions.some((v) => v.filing.accession === ticket.accession))

  const resolve = (s: TicketStatus) => {
    setStatus(ticket.id, s)
    toast(s === 'confirmed' ? `${ticket.id} confirmed. Raise with ${vendorName(ticket.vendor)}` : s === 'dismissed' ? `${ticket.id} dismissed` : `${ticket.id} reopened`)
  }

  return (
    <Drawer open onClose={onClose} title={`Discrepancy ${ticket.id}`}>
      <div className="space-y-5">
        <div>
          <div className="text-sm font-semibold text-navy-900">{ticket.issuer}</div>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <Badge tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Badge>
            <Badge tone={ticket.severity === 'high' ? 'review' : 'pending'}>{ticket.severity === 'high' ? 'High' : 'Medium'} severity</Badge>
            <Badge>{vendorName(ticket.vendor)} · {ticket.vendorId}</Badge>
          </div>
        </div>

        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{FIELD_LABEL[ticket.field]}</div>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-rose-200 bg-rose-50/50 p-3">
              <div className="text-xs text-slate-500">{vendorName(ticket.vendor)}</div>
              <div className="mt-1 text-base font-semibold text-navy-900">{formatValue(ticket.field, ticket.vendorValue)}</div>
            </div>
            <div className="rounded-lg border border-emerald-200 bg-emerald-50/50 p-3">
              <div className="text-xs text-slate-500">SEC filing</div>
              <div className="mt-1 text-base font-semibold text-navy-900">{formatValue(ticket.field, ticket.filingValue)}</div>
            </div>
          </div>
          <p className="mt-2 text-sm text-slate-600">{describeGap(ticket)}</p>
        </div>

        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Filing evidence</div>
          <dl className="mb-3 grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-xs text-slate-500">Source filing</dt><dd className="font-medium">{ticket.form}</dd></div>
            <div><dt className="text-xs text-slate-500">Filed</dt><dd className="font-medium">{fmtDate(ticket.filed)}</dd></div>
          </dl>
          {quote ? (
            <blockquote className="rounded-lg border-l-4 border-brand-500 bg-brand-50/60 p-3 text-sm leading-relaxed text-slate-800">
              “{quote.quote}”
              {quote.location && <div className="mt-1 text-xs text-slate-500">{quote.location}</div>}
            </blockquote>
          ) : (
            <p className="text-sm text-slate-600">No single passage was recorded for this field. See the filing record for the full extraction.</p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            {event && <Link to={`/internal/events/${event.id}`}><Button size="sm"><FileText size={13} /> Corporate action record</Button></Link>}
            {filing && <a href={filing.indexUrl} target="_blank" rel="noreferrer"><Button size="sm"><ExternalLink size={13} /> SEC EDGAR</Button></a>}
          </div>
        </div>

        <div className="border-t border-slate-100 pt-4">
          {status === 'open' ? (
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => resolve('confirmed')}><CheckCircle2 size={15} /> Confirm vendor error</Button>
              <Button onClick={() => resolve('dismissed')}><XCircle size={15} /> Dismiss</Button>
            </div>
          ) : (
            <Button onClick={() => resolve('open')}><RotateCcw size={14} /> Reopen</Button>
          )}
          <p className="mt-2 text-xs text-slate-500">Confirm when the filing is right and the vendor needs to correct its data. Dismiss when the difference is not a real error.</p>
        </div>
      </div>
    </Drawer>
  )
}

export function VendorReconciliation() {
  const { run, start, statuses } = useRecon()
  const [vendor, setVendor] = useState<'all' | 'A' | 'B'>('all')
  const [field, setField] = useState<'all' | TicketField>('all')
  const [state, setState] = useState<'all' | TicketStatus>('all')
  const [q, setQ] = useState('')
  const [shown, setShown] = useState(PAGE)
  const [selected, setSelected] = useState<Ticket | null>(null)

  const statusOf = (t: Ticket): TicketStatus => statuses[t.id] ?? 'open'
  const rows = useMemo(
    () =>
      reconData.tickets.filter(
        (t) =>
          (vendor === 'all' || t.vendor === vendor) &&
          (field === 'all' || t.field === field) &&
          (state === 'all' || statuses[t.id] === state || (state === 'open' && !statuses[t.id])) &&
          t.issuer.toLowerCase().includes(q.toLowerCase()),
      ),
    [vendor, field, state, q, statuses],
  )
  const open = reconData.tickets.filter((t) => statusOf(t) === 'open').length
  const reset = () => setShown(PAGE)

  return (
    <>
      <PageHeader
        title="Vendor Reconciliation"
        subtitle="Vendor tender offer data is compared with the terms extracted from SEC filings. Any difference is raised as a ticket with the filing passage that supports it."
        actions={
          <Button variant="primary" onClick={start} disabled={run.running}>
            {run.running ? <Loader2 size={15} className="animate-spin" /> : <GitCompare size={15} />}
            {run.hasRun ? 'Run again' : 'Run reconciliation'}
          </Button>
        }
      />

      {!run.hasRun ? (
        <Card>
          <div className="px-6 py-10 text-center">
            <div className="mx-auto grid h-11 w-11 place-items-center rounded-full bg-brand-50 text-brand-700"><GitCompare size={20} /></div>
            <h2 className="mt-3 text-base font-semibold text-navy-900">No reconciliation has been run yet</h2>
            <p className="mx-auto mt-1 max-w-xl text-sm text-slate-600">
              The agent loads each vendor feed, matches every record to its SEC filing and checks the offer price, expiration date and CUSIP. Differences come back as tickets to review.
            </p>
            <div className="mt-4 flex flex-wrap items-center justify-center gap-x-6 gap-y-1 text-xs text-slate-500">
              {reconData.vendors.map((v) => (
                <span key={v.id}>{v.name} · {v.format} · {v.records} records</span>
              ))}
            </div>
            <Button variant="primary" className="mt-5" onClick={start}><GitCompare size={15} /> Run reconciliation</Button>
          </div>
        </Card>
      ) : (
        <>
          <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            {[
              { label: 'Vendor records compared', value: reconData.totals.vendorRecords },
              { label: 'Matched to a filing', value: reconData.totals.matched },
              { label: 'Discrepancies raised', value: reconData.tickets.length },
              { label: 'Still open', value: open },
            ].map((s) => (
              <Card key={s.label} className="p-4">
                <div className="text-xs font-medium text-slate-500">{s.label}</div>
                <div className="mt-1.5 text-2xl font-semibold tabular-nums text-navy-900">{s.value}</div>
              </Card>
            ))}
          </div>

          <Card>
            <CardHeader
              title="Discrepancies"
              subtitle={`${rows.length} ticket${rows.length === 1 ? '' : 's'}`}
              action={
                <div className="flex flex-wrap items-center gap-2">
                  <SearchInput value={q} onChange={(v) => { setQ(v); reset() }} placeholder="Search issuer…" />
                  <select value={field} onChange={(e) => { setField(e.target.value as typeof field); reset() }} className="rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm" aria-label="Field">
                    <option value="all">All fields</option>
                    <option value="price">Offer price</option>
                    <option value="expiry">Expiration date</option>
                    <option value="cusip">CUSIP</option>
                  </select>
                  <Segmented value={vendor} onChange={(v) => { setVendor(v); reset() }} options={[{ id: 'all', label: 'All vendors' }, { id: 'A', label: 'Vendor A' }, { id: 'B', label: 'Vendor B' }]} />
                  <Segmented value={state} onChange={(v) => { setState(v); reset() }} options={[{ id: 'all', label: 'All' }, { id: 'open', label: 'Open' }, { id: 'confirmed', label: 'Confirmed' }, { id: 'dismissed', label: 'Dismissed' }]} />
                </div>
              }
            />
            {rows.length === 0 ? (
              <Empty>No tickets match the current filters.</Empty>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      {['Issuer', 'Vendor', 'Field', 'Vendor value', 'Filing value', 'Severity', 'Status'].map((h) => (
                        <th key={h} className="px-4 py-2.5 font-medium">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {rows.slice(0, shown).map((t) => (
                      <tr key={t.id} onClick={() => setSelected(t)} className="cursor-pointer hover:bg-brand-50/50">
                        <td className="max-w-[260px] truncate px-4 py-3 font-medium text-navy-900">{t.issuer}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-slate-600">{vendorName(t.vendor)}</td>
                        <td className="whitespace-nowrap px-4 py-3">{FIELD_LABEL[t.field]}</td>
                        <td className={`whitespace-nowrap px-4 py-3 ${t.vendorValue ? 'text-slate-800' : 'text-slate-400'}`}>{formatValue(t.field, t.vendorValue)}</td>
                        <td className="whitespace-nowrap px-4 py-3 text-slate-800">{formatValue(t.field, t.filingValue)}</td>
                        <td className="px-4 py-3"><Badge tone={t.severity === 'high' ? 'review' : 'pending'}>{t.severity === 'high' ? 'High' : 'Medium'}</Badge></td>
                        <td className="px-4 py-3"><Badge tone={STATUS_TONE[statusOf(t)]}>{STATUS_LABEL[statusOf(t)]}</Badge></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <ShowMore shown={shown} total={rows.length} onMore={() => setShown((n) => n + PAGE)} />
          </Card>
        </>
      )}

      <RunPanel />
      <TicketDrawer ticket={selected} onClose={() => setSelected(null)} />
    </>
  )
}
