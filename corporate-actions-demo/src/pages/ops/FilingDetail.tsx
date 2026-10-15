import { ExternalLink } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { Badge, Button, Card, CardHeader, PageHeader, StatusBadge, TypeBadge, Value } from '../../components/ui'
import { FIELD_DEFS, fmtDate, shortStatus } from '../../data/store'
import { useApp } from '../../state/AppState'

export function FilingDetail() {
  const { filingId } = useParams()
  const { filings, events } = useApp()
  const filing = filings.find((f) => f.id === filingId)
  if (!filing) return <p className="text-sm">Filing not found.</p>
  const event = events.find((e) => e.versions.some((v) => v.filing.id === filing.id))!
  const version = event.versions.find((v) => v.filing.id === filing.id)!
  const defs = FIELD_DEFS[filing.action].filter((d) => filing.fields[d.key])

  return (
    <>
      <PageHeader
        eyebrow={<Link to="/internal/dashboard" className="hover:underline">Filings Monitor</Link>}
        title={`${filing.form} · ${filing.subject}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <TypeBadge action={filing.action} />
            <StatusBadge label={shortStatus(filing.fields.event_status)} />
            <span>Filed {fmtDate(filing.filedDate)}</span>
            <span>·</span>
            <span>Accession {filing.accession}</span>
          </span>
        }
        actions={
          <a href={filing.indexUrl} target="_blank" rel="noreferrer">
            <Button><ExternalLink size={15} /> View on SEC EDGAR</Button>
          </a>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[1fr_320px]">
        <Card>
          <CardHeader title="Extracted terms" subtitle={`${defs.length} fields captured with supporting passages`} />
          <div className="divide-y divide-slate-100">
            {defs.map((d) => {
              const quotes = filing.passages[d.key]
              return (
                <div key={d.key} className="px-5 py-3.5">
                  <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{d.label}</div>
                  <div className="mt-0.5 text-sm font-medium text-slate-900"><Value text={filing.fields[d.key]} /></div>
                  {quotes?.[0] && (
                    <details className="group mt-1.5">
                      <summary className="cursor-pointer text-xs font-medium text-brand-700 hover:underline">Source passage</summary>
                      <blockquote className="mt-1.5 rounded-lg border-l-4 border-brand-500 bg-brand-50/60 p-3 text-sm leading-relaxed text-slate-700">
                        “{quotes[0].quote}”
                        {quotes[0].location && <div className="mt-1 text-xs text-slate-500">{quotes[0].location}</div>}
                      </blockquote>
                    </details>
                  )}
                </div>
              )
            })}
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader title="Filing details" />
            <dl className="divide-y divide-slate-100 text-sm">
              {[
                ['Registrant', filing.registrant ?? '—'],
                ['CIK', filing.cik.replace(/^0+/, '')],
                ['Form', filing.form],
                ['Documents', `${filing.docs} (incl. exhibits)`],
                ['Text size', `${filing.sizeMb >= 1 ? filing.sizeMb.toFixed(1) : filing.sizeMb.toFixed(2)} MB`],
              ].map(([k, v]) => (
                <div key={k} className="flex justify-between gap-3 px-5 py-2.5">
                  <dt className="text-slate-500">{k}</dt>
                  <dd className="text-right font-medium text-slate-900">{v}</dd>
                </div>
              ))}
            </dl>
          </Card>
          <Card>
            <CardHeader title="Corporate action record" />
            <div className="space-y-3 p-5">
              <div className="text-sm font-medium text-navy-900">{event.title}</div>
              <div className="flex flex-wrap gap-1.5">
                <Badge tone="brand">V{version.number} of {event.versions.length}</Badge>
                <StatusBadge label={event.status} />
              </div>
              <Link to={`/internal/events/${event.id}`} className="block rounded-lg bg-navy-800 px-3 py-2 text-center text-sm font-medium text-white hover:bg-navy-700">
                Open record
              </Link>
            </div>
          </Card>
        </div>
      </div>
    </>
  )
}
