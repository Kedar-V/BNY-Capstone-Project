import { Info } from 'lucide-react'
import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { Badge, Card, CardHeader, PageHeader, type Tone } from '../../components/ui'
import type { BriefItem, Tier } from '../../data/briefs'
import { fmtDate } from '../../data/store'
import { useBrief } from '../../state/BriefState'

const TONE: Record<Tier, Tone> = { action: 'review', changed: 'amended', new: 'new', completed: 'completed', upcoming: 'neutral' }

function EventCell({ items }: { items: BriefItem[] }) {
  if (!items.length) return <span className="text-sm text-slate-400">No events</span>
  return (
    <div className="flex flex-col items-start gap-1">
      {items.map((i) => (
        <Link key={i.id} to="/client/brief" className="flex flex-wrap items-center gap-1.5 hover:underline">
          <Badge tone={TONE[i.tier]}>{i.tierLabel}</Badge>
          <span className="text-sm text-navy-900">{i.actionLabel}</span>
        </Link>
      ))}
    </div>
  )
}

export function Holdings() {
  const { client, asOf, visibleItems } = useBrief()
  const byTicker = useMemo(() => {
    const m = new Map<string, BriefItem[]>()
    for (const i of visibleItems) m.set(i.ticker, [...(m.get(i.ticker) ?? []), i])
    return m
  }, [visibleItems])
  const touched = client.positions.filter((p) => byTicker.has(p.ticker)).length

  return (
    <>
      <PageHeader
        eyebrow="Client profile"
        title="Holdings"
        subtitle={`${client.name} · ${client.type}`}
      />
      <p className="mb-5 flex items-start gap-1.5 text-xs text-slate-500">
        <Info size={13} className="mt-0.5 shrink-0" />
        Simulated positions for this demo. In production these would come from BNY custody records. Events shown are as of {fmtDate(asOf)}.
      </p>

      <Card>
        <CardHeader title={`${client.positions.length} positions · ${touched} with a corporate action in the brief`} />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 text-left text-xs font-medium text-slate-500">
                <th scope="col" className="px-5 py-2.5 font-medium">Security</th>
                <th scope="col" className="px-3 py-2.5 font-medium">Ticker</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Shares</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">On loan</th>
                <th scope="col" className="px-5 py-2.5 font-medium">In this brief</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {client.positions.map((p) => (
                <tr key={p.ticker}>
                  <td className="px-5 py-2.5 font-medium text-navy-900">{p.name}</td>
                  <td className="px-3 py-2.5 text-slate-600">{p.ticker}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{p.shares.toLocaleString('en-US')}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">{p.onLoan ? p.onLoan.toLocaleString('en-US') : '–'}</td>
                  <td className="px-5 py-2.5"><EventCell items={byTicker.get(p.ticker) ?? []} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {client.watchlist.length > 0 && (
        <Card className="mt-4">
          <CardHeader title="Watchlist" subtitle="No position held. Events are shown for information, with no calculated impact." />
          <ul className="divide-y divide-slate-100">
            {client.watchlist.map((w) => (
              <li key={w.ticker} className="flex flex-wrap items-center gap-3 px-5 py-2.5">
                <span className="min-w-0 flex-1 text-sm font-medium text-navy-900">{w.name}</span>
                <span className="text-sm text-slate-600">{w.ticker}</span>
                <EventCell items={byTicker.get(w.ticker) ?? []} />
              </li>
            ))}
          </ul>
        </Card>
      )}
    </>
  )
}
