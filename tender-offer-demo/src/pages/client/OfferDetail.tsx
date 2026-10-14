import { BellPlus, BellRing, CalendarDays, CheckCircle2, History as HistoryIcon, Mail } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ChangeCompare } from '../../components/shared'
import { Button, Card, CardHeader, Modal, PageHeader, StatusBadge } from '../../components/ui'
import { companyById } from '../../data/mock'
import { useApp, useOffer } from '../../state/AppState'

const STEPS = [
  'Review updated offer terms',
  'Note the revised expiration date',
  'Review your current position and election requirements',
  'Contact your BNY relationship team with questions',
  'Continue monitoring for amendments',
]

export function ClientOfferDetail() {
  const { offerId } = useParams()
  const view = useOffer(offerId)
  const { subscriptions, toggleSubscription, toast } = useApp()
  const [showHistory, setShowHistory] = useState(false)
  const [contactOpen, setContactOpen] = useState(false)
  const [message, setMessage] = useState('')

  if (!view) return <p className="text-sm">Tender offer not found.</p>
  const { offer, current, versions } = view
  const company = companyById(offer.targetId)
  const subscribed = !!subscriptions.find((s) => s.companyId === company.id)?.subscribed
  const changes = current.changes
  const hasAmendment = versions.some((v) => v.form.endsWith('/A'))
  const steps = hasAmendment ? STEPS : STEPS.filter((s) => !s.includes('revised'))

  const dates = [
    { label: 'Announced', value: versions[0].date },
    { label: 'Current expiration', value: current.fields.expiration },
    { label: 'Last update', value: current.date },
  ]

  return (
    <>
      <PageHeader
        eyebrow={company.name}
        title={offer.title}
        subtitle={offer.type}
        actions={
          <>
            <Button variant={subscribed ? 'secondary' : 'primary'} onClick={() => toggleSubscription(company.id)}>
              {subscribed ? <BellRing size={15} /> : <BellPlus size={15} />}
              {subscribed ? 'Subscribed' : 'Subscribe to Updates'}
            </Button>
            <Button onClick={() => setShowHistory(!showHistory)}>
              <HistoryIcon size={15} /> {showHistory ? 'Hide' : 'View'} Event History
            </Button>
            <Button onClick={() => setContactOpen(true)}>
              <Mail size={15} /> Contact BNY
            </Button>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Offer Summary" />
          <dl className="grid gap-4 p-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs text-slate-500">Offeror</dt>
              <dd className="text-sm font-medium">{current.fields.offeror}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Status</dt>
              <dd className="mt-0.5">
                <StatusBadge label={offer.status} />
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Current offer price</dt>
              <dd className="text-2xl font-semibold text-navy-900">{current.fields.offerPrice}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Current expiration</dt>
              <dd className="text-2xl font-semibold text-navy-900">{current.fields.expiration}</dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Security</dt>
              <dd className="text-sm font-medium">
                {current.fields.security} · {current.fields.cusip}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">Board recommendation</dt>
              <dd className="text-sm font-medium">{current.fields.recommendation}</dd>
            </div>
          </dl>
        </Card>

        <Card>
          <CardHeader title="Important Dates" />
          <ul className="divide-y divide-slate-100">
            {dates.map((d) => (
              <li key={d.label} className="flex items-center gap-3 px-4 py-3">
                <CalendarDays size={16} className="text-navy-600" />
                <div>
                  <div className="text-xs text-slate-500">{d.label}</div>
                  <div className="text-sm font-medium">{d.value}</div>
                </div>
              </li>
            ))}
          </ul>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader title="What Changed" subtitle={`Latest update: ${current.summary} (${current.date})`} />
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            {changes.length ? (
              changes.map((c) => <ChangeCompare key={c.field} change={c} />)
            ) : (
              <p className="text-sm text-slate-500">No changes since the original announcement.</p>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Suggested Next Steps" subtitle="For information only — not investment advice." />
          <ul className="space-y-2.5 p-4">
            {steps.map((s) => (
              <li key={s} className="flex gap-2 text-sm text-slate-700">
                <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-navy-500" />
                {s}
              </li>
            ))}
          </ul>
        </Card>

        {showHistory && (
          <Card className="fade-up lg:col-span-3">
            <CardHeader title="Event History" />
            <ol className="divide-y divide-slate-100">
              {versions.map((v) => (
                <li key={v.id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
                  <span className="w-20 text-slate-500">{v.date.replace(', 2026', '').replace(', 2025', ' ’25')}</span>
                  <span className="font-medium text-navy-800">{v.form}</span>
                  <span className="text-slate-700">{v.summary}</span>
                </li>
              ))}
            </ol>
          </Card>
        )}
      </div>

      <p className="mt-4 text-xs text-slate-500">
        Back to <Link to="/client/notifications" className="text-navy-700 hover:underline">notifications</Link>.
      </p>

      <Modal open={contactOpen} onClose={() => setContactOpen(false)} title="Contact your BNY relationship team">
        <p className="mb-3 text-sm text-slate-600">Demo only — no message is sent.</p>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={4}
          placeholder={`Questions about the ${company.name} tender offer…`}
          className="w-full rounded-md border border-slate-300 p-2.5 text-sm focus:border-navy-500 focus:outline-none focus:ring-2 focus:ring-navy-100"
        />
        <div className="mt-4 flex justify-end gap-2">
          <Button onClick={() => setContactOpen(false)}>Cancel</Button>
          <Button
            variant="primary"
            onClick={() => {
              setContactOpen(false)
              setMessage('')
              toast('Message queued for your BNY relationship team (demo)')
            }}
          >
            Send message
          </Button>
        </div>
      </Modal>
    </>
  )
}
