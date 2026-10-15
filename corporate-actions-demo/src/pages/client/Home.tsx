import { Bell, Layers, Star, TrendingUp, type LucideIcon } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, Card, CardHeader, PageHeader, StatusBadge, TypeBadge } from '../../components/ui'
import { fmtDate, isActive } from '../../data/store'
import { useApp } from '../../state/AppState'

function Stat({ icon: Icon, label, value, to }: { icon: LucideIcon; label: string; value: number; to: string }) {
  return (
    <Link to={to}>
      <Card className="h-full p-4 transition-shadow hover:shadow-md">
        <div className="flex items-center justify-between text-slate-400">
          <span className="text-xs font-medium text-slate-500">{label}</span>
          <Icon size={16} />
        </div>
        <div className="mt-1.5 text-3xl font-semibold tabular-nums text-navy-900">{value}</div>
      </Card>
    </Link>
  )
}

export function ClientHome() {
  const { events, subscribed, notifications, readIds } = useApp()
  const unread = notifications.filter((n) => !readIds.has(n.id))
  const watched = events.filter((e) => subscribed.has(e.id))
  const active = events.filter(isActive)
  const recent = notifications.slice(0, 6)

  return (
    <>
      <PageHeader title="Overview" subtitle="Tender offer and merger activity across your watchlist." />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat icon={TrendingUp} label="Active corporate actions" value={active.length} to="/client/watchlist" />
        <Stat icon={Star} label="On your watchlist" value={watched.length} to="/client/watchlist" />
        <Stat icon={Bell} label="Unread notifications" value={unread.length} to="/client/notifications" />
        <Stat icon={Layers} label="Total tracked" value={events.length} to="/client/watchlist" />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-5">
        <Card className="lg:col-span-3">
          <CardHeader title="Latest activity" action={<Link to="/client/notifications" className="text-xs font-medium text-brand-700 hover:underline">View all</Link>} />
          <ul className="divide-y divide-slate-100">
            {recent.map((n) => (
              <li key={n.id}>
                <Link to={`/client/events/${n.eventId}`} className="flex items-start gap-3 px-5 py-3.5 hover:bg-brand-50/50">
                  <Badge tone={n.kind === 'Amendment' ? 'amended' : 'brand'}>{n.kind}</Badge>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-navy-900">{n.title}</div>
                    <div className="truncate text-xs text-slate-500">{n.body}</div>
                  </div>
                  <span className="whitespace-nowrap text-xs text-slate-500">{fmtDate(n.date)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title="Your watchlist" action={<Link to="/client/watchlist" className="text-xs font-medium text-brand-700 hover:underline">Manage</Link>} />
          <ul className="divide-y divide-slate-100">
            {watched.map((e) => (
              <li key={e.id}>
                <Link to={`/client/events/${e.id}`} className="flex items-center gap-3 px-5 py-3 hover:bg-brand-50/50">
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-navy-900">{e.subject}</div>
                    <div className="mt-0.5 flex gap-1.5"><TypeBadge action={e.action} /></div>
                  </div>
                  <StatusBadge label={e.status} />
                </Link>
              </li>
            ))}
            {!watched.length && <li className="px-5 py-6 text-sm text-slate-500">Nothing on your watchlist yet.</li>}
          </ul>
        </Card>
      </div>
    </>
  )
}
