import { ArrowLeft, Bell, CalendarClock, FilePlus2, Lightbulb, MailOpen, Mail, Pencil, Star, type LucideIcon } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Badge, Button, Card, Empty, PageHeader, RichText, Tabs, type Tone } from '../../components/ui'
import { useApp } from '../../state/AppState'
import type { ClientNotification, NotificationType } from '../../types'

const ICONS: Record<NotificationType, LucideIcon> = {
  'New Tender Offer': FilePlus2,
  Amendment: Pencil,
  'Deadline Change': CalendarClock,
  'Watchlist Update': Star,
  'Suggested Action': Lightbulb,
}
const TONES: Record<NotificationType, Tone> = {
  'New Tender Offer': 'new',
  Amendment: 'amended',
  'Deadline Change': 'pending',
  'Watchlist Update': 'neutral',
  'Suggested Action': 'completed',
}

const FILTERS = [
  { id: 'all', label: 'All' },
  { id: 'New Tender Offer', label: 'Announcements' },
  { id: 'Amendment', label: 'Amendments' },
  { id: 'Deadline Change', label: 'Deadlines' },
  { id: 'Watchlist Update', label: 'Watchlist' },
  { id: 'Suggested Action', label: 'Suggested actions' },
] as const

function Body({ n }: { n: ClientNotification }) {
  return (
    <div className="text-sm text-slate-700">
      <p>
        <RichText text={n.body} />
      </p>
      {n.bullets && (
        <ul className="mt-1.5 list-disc space-y-1 pl-5">
          {n.bullets.map((b) => (
            <li key={b}>
              <RichText text={b} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function Notifications() {
  const { notifications, setNotificationRead, markAllRead } = useApp()
  const navigate = useNavigate()
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['id']>('all')
  const [unreadOnly, setUnreadOnly] = useState(false)
  const unread = notifications.filter((n) => !n.read).length
  const rows = notifications.filter((n) => (filter === 'all' || n.type === filter) && (!unreadOnly || !n.read))

  return (
    <>
      <PageHeader
        title="Notifications"
        subtitle="Alerts for tender offers affecting your custody holdings, plus updates for companies on your watchlist."
        actions={
          <>
            <label className="flex items-center gap-2 text-sm text-slate-600">
              <input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} /> Unread only
            </label>
            <Button onClick={markAllRead} disabled={!unread}>
              Mark all read
            </Button>
          </>
        }
      />
      <Tabs
        tabs={FILTERS.map((f) => ({
          id: f.id,
          label: (
            <>
              {f.label}
              <span className="ml-1.5 text-xs text-slate-400">
                {f.id === 'all' ? notifications.length : notifications.filter((n) => n.type === f.id).length}
              </span>
            </>
          ),
        }))}
        value={filter}
        onChange={setFilter}
      />
      <div className="mt-4 space-y-3">
        {rows.length === 0 && (
          <Card>
            <Empty>No notifications match this filter.</Empty>
          </Card>
        )}
        {rows.map((n) => {
          const Icon = ICONS[n.type]
          return (
            <Card key={n.id} className={`fade-up border-l-4 p-4 ${n.read ? 'border-l-transparent' : 'border-l-navy-600'}`}>
              <div className="flex items-start gap-3">
                <div className="mt-0.5 rounded-md bg-navy-50 p-2 text-navy-700">
                  <Icon size={16} />
                </div>
                <div className="min-w-0 flex-1 space-y-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <button
                      onClick={() => {
                        setNotificationRead(n.id, true)
                        navigate(`/client/notifications/${n.id}`)
                      }}
                      className={`text-left text-sm text-navy-900 hover:underline ${n.read ? 'font-medium' : 'font-semibold'}`}
                    >
                      {n.title}
                    </button>
                    <Badge tone={TONES[n.type]}>{n.type}</Badge>
                    {!n.read && <Badge tone="new">New</Badge>}
                  </div>
                  <Body n={n} />
                  <div className="flex flex-wrap items-center gap-2 pt-1">
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => {
                        setNotificationRead(n.id, true)
                        navigate(`/client/tender-offers/${n.offerId}`)
                      }}
                    >
                      {n.cta}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setNotificationRead(n.id, !n.read)}>
                      {n.read ? <Mail size={13} /> : <MailOpen size={13} />} Mark as {n.read ? 'unread' : 'read'}
                    </Button>
                    <span className="ml-auto text-xs text-slate-400">{n.date}</span>
                  </div>
                </div>
              </div>
            </Card>
          )
        })}
      </div>
    </>
  )
}

export function NotificationDetail() {
  const { notificationId } = useParams()
  const { notifications, setNotificationRead } = useApp()
  const navigate = useNavigate()
  const n = notifications.find((x) => x.id === notificationId)
  if (!n) return <p className="text-sm">Notification not found.</p>
  const Icon = ICONS[n.type]
  return (
    <>
      <Link to="/client/notifications" className="mb-3 inline-flex items-center gap-1.5 text-sm text-navy-700 hover:underline">
        <ArrowLeft size={14} /> Back to notifications
      </Link>
      <Card className="max-w-2xl p-6">
        <div className="mb-3 flex items-center gap-2">
          <Icon size={18} className="text-navy-700" />
          <Badge tone={TONES[n.type]}>{n.type}</Badge>
          <span className="ml-auto text-xs text-slate-400">{n.date}</span>
        </div>
        <h1 className="mb-3 text-xl font-semibold text-navy-900">{n.title}</h1>
        <Body n={n} />
        <div className="mt-5 flex flex-wrap gap-2">
          <Button variant="primary" onClick={() => navigate(`/client/tender-offers/${n.offerId}`)}>
            {n.cta}
          </Button>
          <Button onClick={() => setNotificationRead(n.id, !n.read)}>
            <Bell size={14} /> Mark as {n.read ? 'unread' : 'read'}
          </Button>
        </div>
      </Card>
    </>
  )
}
