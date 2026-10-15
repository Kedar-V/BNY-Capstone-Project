import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card, CardHeader, Empty, PageHeader, SearchInput, Segmented, ShowMore, StatusBadge, TypeBadge } from '../../components/ui'
import { fmtDate } from '../../data/store'
import { useApp } from '../../state/AppState'
import type { ActionType } from '../../types'

const PAGE = 25

export function Events() {
  const { events } = useApp()
  const navigate = useNavigate()
  const [type, setType] = useState<'all' | ActionType>('all')
  const [q, setQ] = useState('')
  const [shown, setShown] = useState(PAGE)

  const rows = useMemo(
    () =>
      events
        .filter((e) => (type === 'all' || e.action === type) && `${e.title} ${e.subject}`.toLowerCase().includes(q.toLowerCase()))
        .sort((a, b) => b.lastDate.localeCompare(a.lastDate) || a.title.localeCompare(b.title)),
    [events, type, q],
  )

  return (
    <>
      <PageHeader title="Corporate Actions" subtitle="Canonical tender offer and merger records built from linked SEC filings, with full version history." />
      <Card>
        <CardHeader
          title={`${rows.length} events`}
          action={
            <div className="flex flex-wrap items-center gap-2">
              <SearchInput value={q} onChange={(v) => { setQ(v); setShown(PAGE) }} placeholder="Search company…" />
              <Segmented
                value={type}
                onChange={(v) => { setType(v); setShown(PAGE) }}
                options={[
                  { id: 'all', label: 'All' },
                  { id: 'tender_offer', label: 'Tender Offers' },
                  { id: 'merger', label: 'Mergers' },
                ]}
              />
            </div>
          }
        />
        {rows.length === 0 ? (
          <Empty>No events match the current filters.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  {['Event', 'Type', 'Key terms', 'Status', 'Versions', 'Last filing'].map((h) => (
                    <th key={h} className="px-4 py-2.5 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.slice(0, shown).map((e) => (
                  <tr key={e.id} onClick={() => navigate(`/internal/events/${e.id}`)} className="cursor-pointer hover:bg-brand-50/50">
                    <td className="max-w-[280px] truncate px-4 py-3 font-medium text-navy-900">{e.title}</td>
                    <td className="px-4 py-3"><TypeBadge action={e.action} /></td>
                    <td className="max-w-[260px] truncate px-4 py-3 text-slate-600">{e.headline}</td>
                    <td className="px-4 py-3"><StatusBadge label={e.status} /></td>
                    <td className="px-4 py-3 tabular-nums text-slate-600">{e.versions.length}</td>
                    <td className="whitespace-nowrap px-4 py-3 text-slate-600">{fmtDate(e.lastDate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <ShowMore shown={shown} total={rows.length} onMore={() => setShown((n) => n + PAGE)} />
      </Card>
    </>
  )
}
