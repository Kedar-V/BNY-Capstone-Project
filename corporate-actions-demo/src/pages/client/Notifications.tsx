import { CheckCheck } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Button, Card, Empty, PageHeader, Segmented } from '../../components/ui'
import { fmtDate } from '../../data/store'
import { useApp } from '../../state/AppState'

export function Notifications() {
  const { notifications, readIds, markRead, markAllRead } = useApp()
  const navigate = useNavigate()
  const [filter, setFilter] = useState<'all' | 'unread'>('all')
  const unread = notifications.filter((n) => !readIds.has(n.id)).length
  const rows = notifications.filter((n) => filter === 'all' || !readIds.has(n.id))

  return (
    <>
      <PageHeader
        title="Notifications"
        subtitle="Alerts for new events and amendments on companies you watch."
        actions={
          <>
            <Segmented value={filter} onChange={setFilter} options={[{ id: 'all', label: 'All' }, { id: 'unread', label: `Unread (${unread})` }]} />
            <Button onClick={markAllRead} disabled={!unread}><CheckCheck size={15} /> Mark all read</Button>
          </>
        }
      />
      <Card>
        {rows.length === 0 ? (
          <Empty>You're all caught up.</Empty>
        ) : (
          <ul className="divide-y divide-slate-100">
            {rows.map((n) => {
              const isUnread = !readIds.has(n.id)
              return (
                <li key={n.id}>
                  <button
                    onClick={() => { markRead(n.id); navigate(`/client/events/${n.eventId}`) }}
                    className={`flex w-full items-start gap-3 px-5 py-4 text-left transition-colors hover:bg-brand-50/50 ${isUnread ? 'bg-brand-50/30' : ''}`}
                  >
                    <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${isUnread ? 'bg-brand-500' : 'bg-transparent'}`} />
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={n.kind === 'Amendment' ? 'amended' : 'brand'}>{n.kind}</Badge>
                        <span className={`text-sm text-navy-900 ${isUnread ? 'font-semibold' : 'font-medium'}`}>{n.title}</span>
                      </div>
                      <p className="mt-1 text-sm text-slate-600">{n.body}</p>
                    </div>
                    <span className="whitespace-nowrap text-xs text-slate-500">{fmtDate(n.date)}</span>
                  </button>
                </li>
              )
            })}
          </ul>
        )}
      </Card>
    </>
  )
}
