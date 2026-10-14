import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, Card, Empty, PageHeader, SearchInput, Toggle } from '../../components/ui'
import { companyById, offers } from '../../data/mock'
import { useApp } from '../../state/AppState'
import type { AlertPrefs } from '../../types'

const PREFS: { key: keyof AlertPrefs; label: string }[] = [
  { key: 'announcements', label: 'New tender offer announcements' },
  { key: 'amendments', label: 'Amendments' },
  { key: 'deadlines', label: 'Deadline changes' },
  { key: 'actions', label: 'Suggested action updates' },
]

export function Watchlist() {
  const { subscriptions, toggleSubscription, setPref } = useApp()
  const [q, setQ] = useState('')
  const rows = subscriptions
    .filter((s) => companyById(s.companyId).name.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => Number(b.subscribed) - Number(a.subscribed))

  return (
    <>
      <PageHeader
        title="Watchlist & Subscriptions"
        subtitle="Notices for securities held in your custody accounts are delivered automatically. Subscribe to extend alerts to other companies."
        actions={<SearchInput value={q} onChange={setQ} placeholder="Search companies…" />}
      />
      <div className="space-y-3">
        {rows.length === 0 && (
          <Card>
            <Empty>No companies match “{q}”.</Empty>
          </Card>
        )}
        {rows.map((s) => {
          const c = companyById(s.companyId)
          const active = offers.find((o) => o.targetId === c.id && o.status === 'Pending')
          return (
            <Card key={s.companyId} className="p-4">
              <div className="flex flex-wrap items-center gap-3">
                <div className="flex-1">
                  <div className="text-sm font-semibold text-navy-900">
                    {c.name} <span className="ml-1 text-xs font-normal text-slate-400">{c.ticker}</span>
                  </div>
                  <div className="text-xs text-slate-500">
                    {c.sector}
                    {active && (
                      <>
                        {' · '}
                        <Link to={`/client/tender-offers/${active.id}`} className="text-navy-700 hover:underline">
                          Active tender offer
                        </Link>
                      </>
                    )}
                  </div>
                </div>
                <Button variant={s.subscribed ? 'secondary' : 'primary'} size="sm" onClick={() => toggleSubscription(s.companyId)}>
                  {s.subscribed ? 'Unsubscribe' : 'Subscribe'}
                </Button>
              </div>
              {s.subscribed && (
                <div className="mt-3 grid gap-x-6 gap-y-2.5 border-t border-slate-100 pt-3 sm:grid-cols-2">
                  {PREFS.map((p) => (
                    <label key={p.key} className="flex items-center justify-between gap-3 text-sm text-slate-700">
                      {p.label}
                      <Toggle label={`${c.name}: ${p.label}`} checked={s.prefs[p.key]} onChange={(v) => setPref(s.companyId, p.key, v)} />
                    </label>
                  ))}
                </div>
              )}
            </Card>
          )
        })}
      </div>
    </>
  )
}
