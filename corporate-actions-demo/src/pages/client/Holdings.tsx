import { Info } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Card, CardHeader, PageHeader, Segmented } from '../../components/ui'
import type { BriefItem } from '../../data/briefs'
import { fmtDate } from '../../data/store'
import { useBrief } from '../../state/BriefState'
import { TIER_TONE } from './Brief'

const usd = (n: number) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const num = (n: number) => n.toLocaleString('en-US')
const short = (iso: string) => new Date(iso + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })

/** One corporate action on a position. Opens the brief at that item. */
function EventChip({ item, onOpen }: { item: BriefItem; onOpen: (i: BriefItem) => void }) {
  const action = item.tier === 'action' && item.cutoff
  const note = action ? (item.cutoff!.passed ? 'BNY cut-off passed' : `Instruct by ${short(item.cutoff!.date)}`) : item.tierLabel
  return (
    <button onClick={() => onOpen(item)} className="group flex items-center gap-1.5 text-left" title={item.title}>
      <Badge tone={TIER_TONE[item.tier]}>{item.actionLabel}</Badge>
      <span className={`whitespace-nowrap text-xs group-hover:underline ${action ? 'font-medium text-rose-700' : 'text-slate-500'}`}>{note}</span>
    </button>
  )
}

/** Positions and the corporate actions that touch them, so a holder can see at a glance what needs attention. */
export function Holdings({ embedded = false, onOpenBrief }: { embedded?: boolean; onOpenBrief?: () => void }) {
  const { client, asOf, visibleItems, focus } = useBrief()
  const navigate = useNavigate()
  const [show, setShow] = useState<'all' | 'affected'>('all')

  const byTicker = useMemo(() => {
    const m = new Map<string, BriefItem[]>()
    for (const i of visibleItems) if (!i.position.watchOnly) m.set(i.ticker, [...(m.get(i.ticker) ?? []), i])
    return m
  }, [visibleItems])

  const rows = client.positions.map((p) => ({ ...p, value: p.price ? p.shares * p.price : null, events: byTicker.get(p.ticker) ?? [] }))
  const affected = rows.filter((r) => r.events.length > 0)
  const shown = show === 'all' ? rows : affected
  const total = rows.reduce((a, r) => a + (r.value ?? 0), 0)
  const instructions = visibleItems.filter((i) => i.tier === 'action' && !i.position.watchOnly).length

  const open = (i: BriefItem) => {
    focus(i.id)
    if (onOpenBrief) onOpenBrief()
    else navigate('/client/brief')
  }

  const stats = [
    { label: 'Positions', value: num(rows.length), cls: 'text-navy-900' },
    { label: 'Market value (indicative)', value: total ? usd(total) : '–', cls: 'text-navy-900' },
    { label: 'With a corporate action', value: num(affected.length), cls: affected.length ? 'text-brand-700' : 'text-slate-300' },
    { label: 'Action needed', value: num(instructions), cls: instructions ? 'text-rose-700' : 'text-slate-300' },
  ]

  return (
    <>
      {!embedded && <PageHeader eyebrow="Holdings" title={client.name} prominent subtitle={client.type} />}

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-4">
        {stats.map((s) => (
          <Card key={s.label} className="px-4 py-3.5">
            <div className="text-xs font-medium text-slate-500">{s.label}</div>
            <div className={`mt-1 text-xl font-semibold tabular-nums ${s.cls}`}>{s.value}</div>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader
          title="Positions"
          subtitle={`Corporate actions as of ${fmtDate(asOf)}`}
          action={
            <Segmented
              value={show}
              onChange={setShow}
              options={[{ id: 'all', label: `All (${rows.length})` }, { id: 'affected', label: `With corporate actions (${affected.length})` }]}
            />
          }
        />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <th scope="col" className="px-5 py-2.5 text-left font-medium">Security</th>
                <th scope="col" className="px-3 py-2.5 text-left font-medium">Ticker</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Shares</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">On loan</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Market value</th>
                <th scope="col" className="px-5 py-2.5 text-left font-medium">Corporate actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {shown.map((r) => (
                <tr key={r.ticker} className={r.events.length ? 'bg-brand-50/30' : ''}>
                  <td className="px-5 py-2.5 font-medium text-navy-900">{r.name}</td>
                  <td className="px-3 py-2.5 text-slate-600">{r.ticker}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{num(r.shares)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">{r.onLoan ? num(r.onLoan) : '–'}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{r.value === null ? '–' : usd(r.value)}</td>
                  <td className="px-5 py-2">
                    {r.events.length ? (
                      <div className="flex flex-col items-start gap-1">
                        {r.events.map((i) => <EventChip key={i.id} item={i} onOpen={open} />)}
                      </div>
                    ) : (
                      <span className="text-slate-300">–</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-slate-200 bg-slate-50 font-semibold text-navy-900">
                <td className="px-5 py-3" colSpan={4}>Total</td>
                <td className="px-3 py-3 text-right tabular-nums">{total ? usd(total) : '–'}</td>
                <td className="px-5 py-3" />
              </tr>
            </tfoot>
          </table>
        </div>
      </Card>

      <p className="mt-4 flex items-start gap-1.5 text-xs leading-relaxed text-slate-500">
        <Info size={13} className="mt-0.5 shrink-0" />
        Positions are simulated and market values use placeholder prices for this demo. In production both would come from BNY custody records.
      </p>
    </>
  )
}
