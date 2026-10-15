import { Star } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Card, CardHeader, Empty, PageHeader, SearchInput, Segmented, ShowMore, StatusBadge, TypeBadge } from '../../components/ui'
import { fmtDate } from '../../data/store'
import { useApp } from '../../state/AppState'
import type { ActionType } from '../../types'

const PAGE = 25

export function Watchlist() {
  const { events, subscribed, toggleSubscription, toast } = useApp()
  const [q, setQ] = useState('')
  const [type, setType] = useState<'all' | ActionType>('all')
  const [shown, setShown] = useState(PAGE)

  const rows = useMemo(
    () =>
      events
        .filter((e) => (type === 'all' || e.action === type) && `${e.title} ${e.subject}`.toLowerCase().includes(q.toLowerCase()))
        .sort((a, b) => Number(subscribed.has(b.id)) - Number(subscribed.has(a.id)) || b.lastDate.localeCompare(a.lastDate)),
    [events, q, type, subscribed],
  )

  return (
    <>
      <PageHeader title="Watchlist" subtitle="Follow companies to be notified when new filings or amendments change an event's terms." />
      <Card>
        <CardHeader
          title={`${subscribed.size} watched · ${events.length} available`}
          action={
            <div className="flex flex-wrap items-center gap-2">
              <SearchInput value={q} onChange={(v) => { setQ(v); setShown(PAGE) }} placeholder="Search company…" />
              <Segmented value={type} onChange={(v) => { setType(v); setShown(PAGE) }} options={[{ id: 'all', label: 'All' }, { id: 'tender_offer', label: 'Tender Offers' }, { id: 'merger', label: 'Mergers' }]} />
            </div>
          }
        />
        {rows.length === 0 ? (
          <Empty>No companies match your search.</Empty>
        ) : (
          <ul className="divide-y divide-slate-100">
            {rows.slice(0, shown).map((e) => {
              const on = subscribed.has(e.id)
              return (
                <li key={e.id} className="flex items-center gap-3 px-5 py-3 hover:bg-slate-50/70">
                  <button
                    aria-label={on ? `Unwatch ${e.subject}` : `Watch ${e.subject}`}
                    onClick={() => {
                      toggleSubscription(e.id)
                      toast(on ? `Removed ${e.subject} from watchlist` : `Watching ${e.subject}`)
                    }}
                    className="rounded p-1 transition-transform hover:scale-110"
                  >
                    <Star size={18} className={on ? 'fill-amber-400 text-amber-400' : 'text-slate-300'} />
                  </button>
                  <Link to={`/client/events/${e.id}`} className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-navy-900">{e.title}</div>
                    <div className="truncate text-xs text-slate-500">{e.headline}</div>
                  </Link>
                  <TypeBadge action={e.action} />
                  <StatusBadge label={e.status} />
                  <span className="hidden w-24 text-right text-xs text-slate-500 sm:block">{fmtDate(e.lastDate)}</span>
                </li>
              )
            })}
          </ul>
        )}
        <ShowMore shown={shown} total={rows.length} onMore={() => setShown((n) => n + PAGE)} />
      </Card>
    </>
  )
}
