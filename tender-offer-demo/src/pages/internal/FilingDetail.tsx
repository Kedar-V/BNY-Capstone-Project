import { ArrowRight, ShieldCheck } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Badge, Card, CardHeader, PageHeader, StatusBadge } from '../../components/ui'
import { companyById, filings } from '../../data/mock'
import { filingsForOffer, offerForFiling, useApp } from '../../state/AppState'
import { FIELD_LABELS, type FieldKey } from '../../types'

export function FilingDetail() {
  const { filingId } = useParams()
  const navigate = useNavigate()
  const { filingStatus, amendmentProcessed } = useApp()
  const filing = filings.find((f) => f.id === filingId)
  const [selected, setSelected] = useState<FieldKey | null>(null)
  const refs = useRef<Partial<Record<FieldKey, HTMLElement | null>>>({})

  useEffect(() => setSelected(null), [filingId])

  if (!filing) return <p className="text-sm">Filing not found.</p>
  const offer = offerForFiling(filing)
  const siblings = filingsForOffer(offer.id).filter(
    (f) => offer.versions.some((v) => v.filingId === f.id && (!v.hiddenUntilProcessed || amendmentProcessed || f.id === filing.id)),
  )
  const version = offer.versions.find((v) => v.filingId === filing.id)

  const select = (k: FieldKey) => {
    setSelected(k)
    refs.current[k]?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  const rows: [string, string][] = [
    ...(Object.keys(FIELD_LABELS) as FieldKey[]).filter((k) => filing.extracted[k]).map((k) => [k, filing.extracted[k]!] as [string, string]),
  ]

  return (
    <>
      <PageHeader
        eyebrow={
          <span>
            <Link to="/internal/dashboard" className="hover:underline">
              Daily Filings
            </Link>{' '}
            / {filing.form}
          </span>
        }
        title={filing.title}
        subtitle={`${companyById(filing.companyId).name} · filed ${filing.filedDate} at ${filing.filedTime} ET · Accession ${filing.accession}`}
        actions={<StatusBadge label={filingStatus(filing)} />}
      />

      {siblings.length > 1 && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-sm">
          <span className="text-slate-500">Filings in this event:</span>
          {siblings.map((s) => {
            const v = offer.versions.find((x) => x.filingId === s.id)!
            return (
              <button
                key={s.id}
                onClick={() => navigate(`/internal/filings/${s.id}`)}
                className={`rounded-md border px-3 py-1.5 font-medium ${
                  s.id === filing.id ? 'border-navy-700 bg-navy-800 text-white' : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
                }`}
              >
                V{v.number} · {s.form}
              </button>
            )
          })}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <Card>
          <CardHeader title={`${filing.form} — filing text`} action={<Badge tone="neutral">Synthetic demo document</Badge>} />
          <div className="max-h-[70vh] space-y-5 overflow-y-auto px-6 py-5 font-serif text-[15px] leading-relaxed text-slate-800">
            {filing.paragraphs.map((p, i) => (
              <section key={i}>
                {p.heading && <h4 className="mb-1.5 font-sans text-xs font-semibold uppercase tracking-wide text-slate-500">{p.heading}</h4>}
                <p>
                  {p.segments.map((s, j) => {
                    const fields = s.fields
                    if (!fields) return <span key={j}>{s.text}</span>
                    const active = !!selected && fields.includes(selected)
                    return (
                      <mark
                        key={j}
                        ref={(el) => {
                          fields.forEach((k) => (refs.current[k] = el))
                        }}
                        onClick={() => setSelected(selected && active ? null : fields[0])}
                        title={fields.map((k) => FIELD_LABELS[k]).join(' · ')}
                        className={`cursor-pointer rounded px-0.5 transition-colors ${
                          active ? 'bg-amber-300 ring-2 ring-amber-500' : 'bg-amber-100 hover:bg-amber-200'
                        }`}
                      >
                        {s.text}
                      </mark>
                    )
                  })}
                </p>
              </section>
            ))}
          </div>
        </Card>

        <Card className="h-fit">
          <CardHeader
            title="Extracted Terms"
            action={
              <Badge tone="completed">
                <ShieldCheck size={12} /> Source verified
              </Badge>
            }
          />
          <ul className="divide-y divide-slate-100">
            {rows.map(([k, value]) => {
              const key = k as FieldKey
              const on = selected === key
              return (
                <li key={k}>
                  <button
                    onClick={() => select(key)}
                    className={`flex w-full items-center justify-between gap-2 px-4 py-2.5 text-left ${on ? 'bg-amber-50' : 'hover:bg-slate-50'}`}
                  >
                    <div>
                      <div className="text-xs text-slate-500">{FIELD_LABELS[key]}</div>
                      <div className="text-sm font-medium text-slate-900">{value}</div>
                    </div>
                    <ArrowRight size={14} className={on ? 'text-amber-600' : 'text-slate-300'} />
                  </button>
                </li>
              )
            })}
            <li className="px-4 py-2.5">
              <div className="text-xs text-slate-500">Filing</div>
              <div className="text-sm font-medium">{filing.form}</div>
            </li>
            <li className="px-4 py-2.5">
              <div className="text-xs text-slate-500">Event Status</div>
              <div className="mt-0.5">
                <StatusBadge label={offer.status} />
              </div>
            </li>
          </ul>
          <div className="border-t border-slate-100 p-3">
            <Link
              to={`/internal/tender-offers/${offer.id}`}
              className="block rounded-md bg-navy-800 px-3 py-2 text-center text-sm font-medium text-white hover:bg-navy-700"
            >
              Open tender offer record{version ? ` (V${version.number})` : ''}
            </Link>
          </div>
        </Card>
      </div>
    </>
  )
}
