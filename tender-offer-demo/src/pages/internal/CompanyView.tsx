import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { VersionTimeline } from '../../components/shared'
import { Card, Empty, PageHeader, StatusBadge } from '../../components/ui'
import { companies, companyById } from '../../data/mock'
import { allOffersFor, useOffer } from '../../state/AppState'

function OfferRow({ offerId }: { offerId: string }) {
  const view = useOffer(offerId)!
  const [open, setOpen] = useState(false)
  const { offer, current, versions } = view
  return (
    <>
      <tr className="cursor-pointer hover:bg-navy-50/60" onClick={() => setOpen(!open)}>
        <td className="px-4 py-3">
          <div className="flex items-center gap-2">
            {open ? <ChevronDown size={15} className="text-slate-400" /> : <ChevronRight size={15} className="text-slate-400" />}
            <div>
              <div className="font-medium text-navy-800">{offer.title}</div>
              <div className="text-xs text-slate-500">{offer.type}</div>
            </div>
          </div>
        </td>
        <td className="px-4 py-3">
          <StatusBadge label={offer.status} />
        </td>
        <td className="whitespace-nowrap px-4 py-3 text-slate-600">
          {offer.announced} → {current.fields.expiration}
        </td>
        <td className="px-4 py-3 text-slate-600">
          {current.summary}
          <div className="text-xs text-slate-400">{current.date}</div>
        </td>
        <td className="px-4 py-3 text-center">{versions.length}</td>
      </tr>
      {open && (
        <tr>
          <td colSpan={5} className="bg-slate-50 px-6 py-4">
            <VersionTimeline view={view} />
            <Link to={`/internal/tender-offers/${offer.id}`} className="mt-3 inline-block text-sm font-medium text-navy-700 hover:underline">
              Open tender offer record →
            </Link>
          </td>
        </tr>
      )}
    </>
  )
}

export function CompanyView() {
  const { companyId } = useParams()
  const navigate = useNavigate()
  const company = companies.find((c) => c.id === companyId)
  if (!company) return <p className="text-sm">Company not found.</p>
  const rows = allOffersFor(company.id)
  const withOffers = companies.filter((c) => allOffersFor(c.id).length)

  return (
    <>
      <PageHeader
        eyebrow="Company view"
        title={company.name}
        subtitle={`${company.ticker ? company.ticker + ' · ' : ''}${company.sector} · ${rows.length} tender offer${rows.length === 1 ? '' : 's'} on record`}
        actions={
          <select
            value={company.id}
            onChange={(e) => navigate(`/internal/companies/${e.target.value}`)}
            className="rounded-md border border-slate-300 bg-white px-2.5 py-2 text-sm"
            aria-label="Select company"
          >
            {withOffers.map((c) => (
              <option key={c.id} value={c.id}>
                {companyById(c.id).name}
              </option>
            ))}
          </select>
        }
      />
      <Card>
        {rows.length === 0 ? (
          <Empty>No tender offers on record.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  {['Tender offer', 'Status', 'Dates', 'Latest update', 'Versions'].map((h) => (
                    <th key={h} className="px-4 py-2.5 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.map((o) => (
                  <OfferRow key={o.id} offerId={o.id} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  )
}
