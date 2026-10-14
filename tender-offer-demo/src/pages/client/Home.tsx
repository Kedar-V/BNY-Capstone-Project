import { Bell, CalendarClock, Eye, Lightbulb, Star, TrendingUp } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Card, CardHeader, PageHeader, StatusBadge } from '../../components/ui'
import { companyById, offers } from '../../data/mock'
import { useApp, useOffer } from '../../state/AppState'

function Stat({ icon: Icon, label, value, lines, to }: { icon: LucideIcon; label: string; value: number; lines?: string[]; to: string }) {
  return (
    <Link to={to}>
      <Card className="h-full p-4 transition-shadow hover:shadow-md">
        <div className="flex items-center justify-between text-slate-500">
          <span className="text-xs font-medium uppercase tracking-wide">{label}</span>
          <Icon size={16} />
        </div>
        <div className="mt-1 text-3xl font-semibold text-navy-900">{value}</div>
        <div className="mt-1 min-h-[2.5rem] text-xs text-slate-500">{lines?.map((l) => <div key={l}>{l}</div>)}</div>
      </Card>
    </Link>
  )
}

function ActiveRow({ offerId }: { offerId: string }) {
  const v = useOffer(offerId)!
  return (
    <Link to={`/client/tender-offers/${offerId}`} className="flex items-center gap-3 px-4 py-3 hover:bg-navy-50/60">
      <div className="flex-1">
        <div className="text-sm font-medium text-navy-800">{companyById(v.offer.targetId).name}</div>
        <div className="text-xs text-slate-500">
          {v.offer.offerorName} · {v.current.fields.offerPrice} · expires {v.current.fields.expiration}
        </div>
      </div>
      <StatusBadge label={v.offer.status} />
    </Link>
  )
}

export function ClientHome() {
  const { notifications, subscriptions, actions } = useApp()
  const unread = notifications.filter((n) => !n.read)
  const count = (t: string) => unread.filter((n) => n.type === t).length
  const lines = [
    count('Amendment') && `${count('Amendment')} Amendment`,
    count('Deadline Change') && `${count('Deadline Change')} Deadline Changed`,
    count('New Tender Offer') && `${count('New Tender Offer')} New Tender Offer`,
    count('Suggested Action') && `${count('Suggested Action')} Suggested Action`,
  ].filter(Boolean) as string[]

  const active = offers.filter((o) => o.status === 'Pending' && o.id !== 'to-summit-issuer')
  const subscribed = subscriptions.filter((s) => s.subscribed)
  const openActions = actions.filter((a) => a.status === 'open')
  const watchUpdates = notifications.filter((n) => n.type === 'Watchlist Update').length

  return (
    <>
      <PageHeader title="Welcome back" subtitle="Tender offer activity affecting your holdings and watchlist." />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <Stat icon={TrendingUp} label="Active Tender Offers" value={active.length} to="/client/watchlist" lines={['Across holdings & watchlist']} />
        <Stat icon={Bell} label="New Notifications" value={unread.length} lines={lines} to="/client/notifications" />
        <Stat icon={CalendarClock} label="Upcoming Deadlines" value={active.length} lines={['Next: Northstar, Oct. 18']} to="/client/recommendations" />
        <Stat icon={Lightbulb} label="Suggested Actions" value={openActions.length} lines={['Awaiting your review']} to="/client/recommendations" />
        <Stat icon={Star} label="Watchlist Updates" value={watchUpdates} lines={['Last 30 days']} to="/client/watchlist" />
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Active tender offers" />
          <div className="divide-y divide-slate-100">
            {active.map((o) => (
              <ActiveRow key={o.id} offerId={o.id} />
            ))}
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardHeader title="Subscribed companies" action={<Link to="/client/watchlist" className="text-xs font-medium text-navy-700 hover:underline">Manage</Link>} />
            <ul className="divide-y divide-slate-100">
              {subscribed.map((s) => (
                <li key={s.companyId} className="px-4 py-2.5 text-sm">
                  {companyById(s.companyId).name}
                  <span className="ml-2 text-xs text-slate-400">{companyById(s.companyId).ticker}</span>
                </li>
              ))}
              {!subscribed.length && <li className="px-4 py-4 text-sm text-slate-500">No subscriptions yet.</li>}
            </ul>
          </Card>
          <Card>
            <CardHeader title="Recently viewed" />
            <ul className="divide-y divide-slate-100">
              {['to-acme-blueriver', 'to-pinecrest-northstar'].map((id) => (
                <li key={id}>
                  <Link to={`/client/tender-offers/${id}`} className="flex items-center gap-2 px-4 py-2.5 text-sm hover:bg-navy-50/60">
                    <Eye size={14} className="text-slate-400" />
                    {offers.find((o) => o.id === id)!.title}
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </>
  )
}
