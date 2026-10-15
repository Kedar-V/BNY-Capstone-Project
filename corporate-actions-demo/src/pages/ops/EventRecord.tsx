import { ArrowRight, Check, ExternalLink, FileText, Info, Minus, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { Badge, Button, Card, CardHeader, Drawer, Modal, PageHeader, StatusBadge, Tabs, TypeBadge, Value } from '../../components/ui'
import { FIELD_DEFS, fmtDate } from '../../data/store'
import { useApp } from '../../state/AppState'
import type { CorporateEvent, FieldChange, FieldDef } from '../../types'

type TabId = 'overview' | 'history' | 'sources'

function evidenceFor(event: CorporateEvent, key: string) {
  for (let i = event.versions.length - 1; i >= 0; i--) {
    const v = event.versions[i]
    if (v.filing.passages[key]?.length) return { version: v, quotes: v.filing.passages[key] }
  }
  return undefined
}

export function EventRecord({ mode }: { mode: 'internal' | 'client' }) {
  const { eventId } = useParams()
  const { eventById } = useApp()
  const [tab, setTab] = useState<TabId>('overview')
  const [field, setField] = useState<FieldDef | null>(null)
  const [linkOpen, setLinkOpen] = useState(false)
  const base = `/${mode}`
  const event = eventById(eventId ?? '')
  if (!event) return <p className="text-sm">Corporate action not found.</p>

  const defs = FIELD_DEFS[event.action]
  const sections = Array.from(new Set(defs.map((d) => d.section)))
  const populated = defs.filter((d) => event.fields[d.key]).length

  const tabs: { id: TabId; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'history', label: `Version History (${event.versions.length})` },
    ...(mode === 'internal' ? [{ id: 'sources' as TabId, label: 'Source Filings' }] : []),
  ]

  return (
    <>
      <PageHeader
        eyebrow={<Link to={mode === 'internal' ? '/internal/events' : '/client/watchlist'} className="hover:underline">{mode === 'internal' ? 'Corporate Actions' : 'Watchlist'}</Link>}
        title={event.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <TypeBadge action={event.action} />
            <StatusBadge label={event.status} />
            <span>Last updated {fmtDate(event.lastDate)}</span>
            <span>·</span>
            <span>Latest filing {event.current.filing.form}</span>
            <span>·</span>
            <span>{populated} of {defs.length} fields captured</span>
          </span>
        }
      />

      <Tabs tabs={tabs} value={tab} onChange={setTab} />

      <div className="mt-5">
        {tab === 'overview' && (
          <>
            <p className="mb-3 text-xs text-slate-500">Select any value to view the source passage in the filing.</p>
            <div className="grid gap-4 md:grid-cols-2">
              {sections.map((sec) => {
                const rows = defs.filter((d) => d.section === sec && event.fields[d.key])
                if (!rows.length) return null
                return (
                  <Card key={sec} className={sec === 'Status' || sec === 'Offer Terms' || sec === 'Consideration' || sec === 'Conditions & Dates' ? 'md:col-span-2' : ''}>
                    <CardHeader title={sec} />
                    <div className="divide-y divide-slate-50 p-2">
                      {rows.map((d) => (
                        <button key={d.key} onClick={() => setField(d)} className="flex w-full items-start justify-between gap-6 rounded-lg px-3 py-2.5 text-left transition-colors hover:bg-brand-50/60">
                          <span className="w-44 shrink-0 text-sm text-slate-500">{d.label}</span>
                          <span className="min-w-0 flex-1 text-sm font-medium text-slate-900">
                            <Value text={event.fields[d.key]} />
                          </span>
                        </button>
                      ))}
                    </div>
                  </Card>
                )
              })}
            </div>
          </>
        )}

        {tab === 'history' && (
          <>
          <div className="mb-4 flex items-center gap-2">
            <h2 className="text-sm font-semibold text-navy-900">Linked filings</h2>
            <button
              onClick={() => setLinkOpen(true)}
              aria-label="How these filings were linked"
              title="How these filings were linked"
              className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-brand-700 shadow-sm transition-colors hover:border-brand-300 hover:bg-brand-50"
            >
              <Info size={14} /> How were these linked?
            </button>
          </div>
          <ol className="relative space-y-4 border-l-2 border-slate-200 pl-7">
            {[...event.versions].reverse().map((v) => {
              const latest = v.number === event.current.number
              return (
                <li key={v.filing.id} className="relative">
                  <span className={`absolute -left-[37px] top-4 grid h-4 w-4 place-items-center rounded-full border-2 bg-white ${latest ? 'border-brand-600' : 'border-slate-300'}`}>
                    {latest && <span className="h-1.5 w-1.5 rounded-full bg-brand-600" />}
                  </span>
                  <Card>
                    <div className="flex flex-wrap items-center gap-3 px-5 py-3.5">
                      <span className="text-sm font-semibold text-navy-900">V{v.number}</span>
                      <Badge>{v.filing.form}</Badge>
                      <span className="text-sm text-slate-500">{fmtDate(v.filing.filedDate)}</span>
                      {latest && <Badge tone="brand">Current</Badge>}
                      {v.filing.link?.confidence && <Badge tone="completed"><Check size={11} /> Linked · {v.filing.link.confidence} confidence</Badge>}
                      <span className="flex-1" />
                      {mode === 'internal' && (
                        <Link to={`/internal/filings/${v.filing.id}`} className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-700 hover:underline">
                          <FileText size={14} /> View filing
                        </Link>
                      )}
                    </div>
                    <div className="border-t border-slate-100 px-5 py-4">
                      {v.number === 1 ? (
                        <p className="text-sm text-slate-600">Initial record created from this filing — {Object.keys(v.filing.fields).length} fields captured.</p>
                      ) : (
                        <ChangeList changes={v.changes} />
                      )}
                    </div>
                  </Card>
                </li>
              )
            })}
          </ol>
          </>
        )}

        {tab === 'sources' && (
          <Card>
            <ul className="divide-y divide-slate-100">
              {[...event.versions].reverse().map((v) => (
                <li key={v.filing.id}>
                  <Link to={`/internal/filings/${v.filing.id}`} className="flex items-center gap-3 px-5 py-3.5 hover:bg-brand-50/50">
                    <FileText size={16} className="text-slate-400" />
                    <div className="flex-1">
                      <div className="text-sm font-medium text-navy-900">{v.filing.form} · {v.filing.registrant ?? v.filing.subject}</div>
                      <div className="text-xs text-slate-500">{fmtDate(v.filing.filedDate)} · Accession {v.filing.accession}</div>
                    </div>
                    <Badge tone="brand">V{v.number}</Badge>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>

      <Modal open={linkOpen} onClose={() => setLinkOpen(false)} wide title="How these filings were linked">
        <LinkExplainer event={event} />
      </Modal>

      <Drawer open={!!field} onClose={() => setField(null)} title="Source evidence">
        {field && <Evidence event={event} def={field} mode={mode} base={base} />}
      </Drawer>
    </>
  )
}

function LinkExplainer({ event }: { event: CorporateEvent }) {
  const linked = event.versions.filter((v) => v.filing.link)
  return (
    <div className="max-h-[70vh] space-y-5 overflow-y-auto px-6 py-5 text-sm text-slate-700">
      {linked.length === 0 ? (
        <p>This record is built from a single filing, so there is nothing to link yet. When a related filing (an amendment, definitive proxy, or follow-up) arrives, it is attached here only if it passes the checks below.</p>
      ) : (
        <p>
          Filings are never grouped by company name alone. Each new filing is compared with the first filing of the event on the signals below, and it is attached only when a linking rule is satisfied.
        </p>
      )}

      {linked.map((v) => {
        const l = v.filing.link!
        return (
          <section key={v.filing.id} className="rounded-xl border border-slate-200">
            <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 bg-slate-50 px-4 py-3">
              <span className="font-semibold text-navy-900">{l.toForm} → {v.filing.form}</span>
              <span className="text-xs text-slate-500">{fmtDate(l.toDate)} → {fmtDate(v.filing.filedDate)}</span>
              <span className="flex-1" />
              {l.confidence && <Badge tone="completed">{l.confidence} confidence</Badge>}
            </div>
            <div className="space-y-3 px-4 py-3.5">
              <div className="text-xs">
                <span className="font-semibold uppercase tracking-wide text-slate-500">Rule applied</span>
                <div className="mt-0.5 text-sm font-medium text-navy-900">{l.rule}</div>
              </div>
              <ul className="divide-y divide-slate-100">
                {l.signals.map((sg) => (
                  <li key={sg.id} className="flex gap-3 py-2.5">
                    <span className={`mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full ${sg.ok ? 'bg-emerald-100 text-emerald-700' : 'bg-slate-100 text-slate-400'}`}>
                      {sg.ok ? <Check size={12} strokeWidth={3} /> : <Minus size={12} strokeWidth={3} />}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className={`font-medium ${sg.ok ? 'text-slate-900' : 'text-slate-500'}`}>
                        {sg.label}
                        {sg.strong && <span className="ml-2 text-[10px] font-semibold uppercase tracking-wide text-brand-700">strong signal</span>}
                      </div>
                      <div className="text-xs text-slate-500">{sg.detail}</div>
                      {sg.quotes?.map((q) => (
                        <blockquote key={q.source} className="mt-1.5 rounded-lg border-l-4 border-brand-500 bg-brand-50/60 p-2.5 text-xs leading-relaxed text-slate-700">
                          “{q.quote}”
                          <div className="mt-1 text-[11px] text-slate-500">{q.source}</div>
                        </blockquote>
                      ))}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          </section>
        )
      })}

      <section>
        <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Filings in this record</div>
        <ul className="divide-y divide-slate-100 rounded-xl border border-slate-200">
          {event.versions.map((v) => (
            <li key={v.filing.id} className="flex flex-wrap items-center gap-2 px-4 py-2.5">
              <Badge tone="brand">V{v.number}</Badge>
              <span className="font-medium text-slate-900">{v.filing.form}</span>
              <span className="text-xs text-slate-500">{v.filing.accession}</span>
              <span className="flex-1" />
              <span className="text-xs text-slate-500">File No. {v.filing.fileNo ?? 'n/a'}</span>
              <a href={v.filing.indexUrl} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline">
                <ExternalLink size={12} /> EDGAR
              </a>
            </li>
          ))}
        </ul>
      </section>

      <p className="rounded-lg bg-slate-50 p-3 text-xs text-slate-600">
        <strong className="font-semibold text-slate-800">Linking rules.</strong> High confidence: same SEC file number, or one filing cites the other's file number, or both reference the same merger agreement (date) and the same acquirer and target. Medium: same agreement with one matching party. Company name on its own never creates a link — two unrelated deals can share a name, and one deal's filings often carry different names and file numbers (as with a registration statement and a definitive proxy filed by different companies).
      </p>
    </div>
  )
}

function ChangeList({ changes }: { changes: FieldChange[] }) {
  const material = changes.filter((c) => c.kind !== 'reworded')
  const reworded = changes.filter((c) => c.kind === 'reworded')
  if (!material.length) {
    return (
      <p className="text-sm text-slate-600">
        No change to the terms.{reworded.length > 0 && ` ${reworded.map((c) => c.label).join(', ')} ${reworded.length > 1 ? 'were' : 'was'} re-extracted with different wording only.`}
      </p>
    )
  }
  return (
    <div className="space-y-3">
      {material.map((c) => (
        <div key={c.key} className="rounded-lg border border-slate-200 p-3.5">
          <div className="mb-2 flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{c.label}</span>
            <Badge tone={c.kind === 'added' ? 'new' : 'amended'}>{c.kind === 'added' ? 'Added' : 'Updated'}</Badge>
          </div>
          {c.kind === 'list' ? (
            <div className="flex flex-wrap gap-1.5">
              {c.addedItems?.map((x) => (
                <span key={'a' + x} className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-medium text-emerald-800 ring-1 ring-inset ring-emerald-200">+ {x}</span>
              ))}
              {c.removedItems?.map((x) => (
                <span key={'r' + x} className="rounded-md bg-rose-50 px-2 py-1 text-xs font-medium text-rose-800 ring-1 ring-inset ring-rose-200">− {x}</span>
              ))}
            </div>
          ) : c.kind === 'added' ? (
            <div className="text-sm font-medium text-slate-900"><Value text={c.current} /></div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-start">
              <div className="text-sm text-slate-500">{c.previous}</div>
              <ArrowRight size={16} className="mt-0.5 hidden text-slate-400 sm:block" />
              <div className="text-sm font-medium text-slate-900">{c.current}</div>
            </div>
          )}
        </div>
      ))}
      {reworded.length > 0 && (
        <p className="text-xs text-slate-500">
          Also re-extracted with different wording only (no change in substance): {reworded.map((c) => c.label).join(', ')}.
        </p>
      )}
    </div>
  )
}

function Evidence({ event, def, mode }: { event: CorporateEvent; def: FieldDef; mode: 'internal' | 'client'; base: string }) {
  const ev = evidenceFor(event, def.key)
  const filing = (ev?.version ?? event.current).filing
  return (
    <div className="space-y-5">
      <div>
        <div className="text-xs uppercase tracking-wide text-slate-500">{def.label}</div>
        <div className="mt-1 text-base font-semibold text-navy-900"><Value text={event.fields[def.key]} /></div>
      </div>
      {ev ? (
        <>
          <Badge tone="completed"><ShieldCheck size={12} /> Linked to source passage</Badge>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-xs text-slate-500">Source filing</dt><dd className="font-medium">{filing.form}</dd></div>
            <div><dt className="text-xs text-slate-500">Filing date</dt><dd className="font-medium">{fmtDate(filing.filedDate)}</dd></div>
            <div><dt className="text-xs text-slate-500">Version</dt><dd className="font-medium">V{ev.version.number}</dd></div>
            <div><dt className="text-xs text-slate-500">Accession no.</dt><dd className="break-all font-medium">{filing.accession}</dd></div>
          </dl>
          <div className="space-y-3">
            <div className="text-xs uppercase tracking-wide text-slate-500">Passage{ev.quotes.length > 1 ? 's' : ''}</div>
            {ev.quotes.map((q, i) => (
              <figure key={i}>
                <blockquote className="rounded-lg border-l-4 border-brand-500 bg-brand-50/60 p-3 text-sm leading-relaxed text-slate-800">“{q.quote}”</blockquote>
                {q.location && <figcaption className="mt-1 text-xs text-slate-500">{q.location}</figcaption>}
              </figure>
            ))}
          </div>
        </>
      ) : (
        <p className="text-sm text-slate-600">Extracted from {filing.form} filed {fmtDate(filing.filedDate)}. No single supporting passage was recorded for this field.</p>
      )}
      <div className="flex flex-wrap gap-2">
        {mode === 'internal' && (
          <Link to={`/internal/filings/${filing.id}`}><Button variant="primary"><FileText size={15} /> Open filing record</Button></Link>
        )}
        <a href={filing.indexUrl} target="_blank" rel="noreferrer"><Button><ExternalLink size={15} /> View on SEC EDGAR</Button></a>
      </div>
    </div>
  )
}
