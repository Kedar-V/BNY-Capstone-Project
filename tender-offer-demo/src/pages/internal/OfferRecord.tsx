import { FileText, History } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { EvidenceDrawer, VersionTimeline } from '../../components/shared'
import { Badge, Button, Card, CardHeader, PageHeader, StatusBadge, Tabs } from '../../components/ui'
import { companyById, filingById } from '../../data/mock'
import { filingsForOffer, useApp, useOffer } from '../../state/AppState'
import { FIELD_LABELS, type FieldKey } from '../../types'

const TABS = [
  { id: 'overview', label: 'Overview' },
  { id: 'terms', label: 'Terms' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'sources', label: 'Source Documents' },
  { id: 'notifications', label: 'Notifications' },
] as const
type TabId = (typeof TABS)[number]['id']

export function OfferRecord() {
  const { offerId } = useParams()
  const view = useOffer(offerId)
  const { notifications } = useApp()
  const [tab, setTab] = useState<TabId>('overview')
  const [field, setField] = useState<FieldKey | null>(null)

  if (!view) return <p className="text-sm">Tender offer not found.</p>
  const { offer, current, versions } = view
  const f = current.fields
  const first = versions[0]
  const lastAmendment = [...versions].reverse().find((v) => v.form.endsWith('/A'))

  const FieldRow = ({ k, label }: { k: FieldKey; label?: string }) => (
    <button
      onClick={() => setField(k)}
      className="flex w-full items-baseline justify-between gap-4 rounded px-2 py-2 text-left hover:bg-navy-50"
    >
      <span className="text-sm text-slate-500">{label ?? FIELD_LABELS[k]}</span>
      <span className="text-right text-sm font-medium text-slate-900">{f[k]}</span>
    </button>
  )
  const Static = ({ label, value }: { label: string; value: string }) => (
    <div className="flex items-baseline justify-between gap-4 px-2 py-2">
      <span className="text-sm text-slate-500">{label}</span>
      <span className="text-right text-sm font-medium text-slate-900">{value}</span>
    </div>
  )

  const related = notifications.filter((n) => n.offerId === offer.id)

  return (
    <>
      <PageHeader
        eyebrow={
          <span>
            <Link to={`/internal/companies/${offer.targetId}`} className="hover:underline">
              {companyById(offer.targetId).name}
            </Link>{' '}
            / Tender offer record
          </span>
        }
        title={offer.title}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            <StatusBadge label={offer.status} />
            <span>Last updated {current.date}</span>
            <span>·</span>
            <span>Latest filing {current.form}</span>
            <span>·</span>
            <span>{versions.length} versions</span>
          </span>
        }
        actions={
          <Link to={`/internal/tender-offers/${offer.id}/history`}>
            <Button variant="primary">
              <History size={15} /> Version history
            </Button>
          </Link>
        }
      />

      <Tabs tabs={TABS.map((t) => ({ ...t }))} value={tab} onChange={setTab} />

      <div className="mt-4">
        {tab === 'overview' && (
          <>
            <p className="mb-3 text-xs text-slate-500">Select any field to see the source passage that supports it.</p>
            <div className="grid gap-4 md:grid-cols-2">
              <Card>
                <CardHeader title="Parties & Security" />
                <div className="p-2">
                  <FieldRow k="offeror" />
                  <FieldRow k="target" />
                  <FieldRow k="security" />
                  <FieldRow k="cusip" />
                </div>
              </Card>
              <Card>
                <CardHeader title="Offer Terms" />
                <div className="p-2">
                  <FieldRow k="offerPrice" />
                  <FieldRow k="minCondition" />
                  <FieldRow k="withdrawal" />
                  <FieldRow k="recommendation" />
                </div>
              </Card>
              <Card>
                <CardHeader title="Important Dates" />
                <div className="p-2">
                  <Static label="Announcement" value={first.date} />
                  <FieldRow k="expiration" />
                  <Static label="Last amendment" value={lastAmendment ? lastAmendment.date : 'None'} />
                </div>
              </Card>
              <Card>
                <CardHeader title="Status" />
                <div className="space-y-2 p-4">
                  <StatusBadge label={offer.status} />
                  <p className="text-sm text-slate-700">
                    <span className="font-medium">Latest update (V{current.number}, {current.form}):</span> {current.summary}.
                  </p>
                  {current.changes.length > 0 && (
                    <ul className="space-y-1 text-sm text-slate-600">
                      {current.changes.map((c) => (
                        <li key={c.field}>
                          {FIELD_LABELS[c.field]}: <span className="line-through">{c.previous}</span> → <span className="font-semibold text-slate-900">{c.current}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </Card>
            </div>
          </>
        )}

        {tab === 'terms' && (
          <Card>
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Term</th>
                  <th className="px-4 py-2.5 font-medium">Current value</th>
                  <th className="px-4 py-2.5 font-medium">Previously</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {(Object.keys(FIELD_LABELS) as FieldKey[]).map((k) => {
                  const change = [...versions].reverse().flatMap((v) => v.changes).find((c) => c.field === k && c.current === f[k])
                  return (
                    <tr key={k} onClick={() => setField(k)} className="cursor-pointer hover:bg-navy-50/60">
                      <td className="px-4 py-2.5 text-slate-500">{FIELD_LABELS[k]}</td>
                      <td className="px-4 py-2.5 font-medium">{f[k]}</td>
                      <td className="px-4 py-2.5 text-slate-500">{change ? change.previous : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </Card>
        )}

        {tab === 'timeline' && <VersionTimeline view={view} />}

        {tab === 'sources' && (
          <Card>
            <ul className="divide-y divide-slate-100">
              {filingsForOffer(offer.id)
                .filter((fl) => versions.some((v) => v.filingId === fl.id))
                .map((fl) => {
                  const v = versions.find((x) => x.filingId === fl.id)!
                  return (
                    <li key={fl.id}>
                      <Link to={`/internal/filings/${fl.id}`} className="flex items-center gap-3 px-4 py-3 hover:bg-navy-50/60">
                        <FileText size={16} className="text-slate-400" />
                        <div className="flex-1">
                          <div className="text-sm font-medium text-navy-800">{filingById(fl.id).title}</div>
                          <div className="text-xs text-slate-500">
                            {fl.filedDate} · {fl.accession}
                          </div>
                        </div>
                        <Badge>{fl.form}</Badge>
                        <Badge tone="new">V{v.number}</Badge>
                      </Link>
                    </li>
                  )
                })}
            </ul>
          </Card>
        )}

        {tab === 'notifications' && (
          <Card>
            <CardHeader title="Client notifications generated for this event" />
            {related.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-slate-500">No notifications have been generated yet.</p>
            ) : (
              <ul className="divide-y divide-slate-100">
                {related.map((n) => (
                  <li key={n.id} className="flex items-center gap-3 px-4 py-3">
                    <Badge tone={n.type === 'Amendment' || n.type === 'Deadline Change' ? 'amended' : 'new'}>{n.type}</Badge>
                    <div className="flex-1 text-sm text-slate-800">{n.title}</div>
                    <span className="text-xs text-slate-500">{n.date}</span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        )}
      </div>

      <EvidenceDrawer view={view} field={field} onClose={() => setField(null)} />
    </>
  )
}
