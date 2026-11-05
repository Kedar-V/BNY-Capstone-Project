import { Card, CardHeader, PageHeader } from '../../components/ui'
import { useBrief } from '../../state/BriefState'

const usd = (n: number) => n.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 })
const num = (n: number) => n.toLocaleString('en-US')
const signed = (n: number) => `${n >= 0 ? '+' : '−'}${usd(Math.abs(n))}`
const pct = (n: number) => `${n >= 0 ? '+' : '−'}${Math.abs(n).toFixed(1)}%`
const tone = (n: number) => (n >= 0 ? 'text-emerald-700' : 'text-rose-700')

export function Holdings({ embedded = false }: { embedded?: boolean }) {
  const { client } = useBrief()

  const rows = client.positions.map((p) => {
    const invested = p.shares * (p.avgCost ?? 0)
    const current = p.shares * (p.price ?? 0)
    return { ...p, invested, current, gain: current - invested, gainPct: invested ? ((current - invested) / invested) * 100 : 0 }
  })
  const total = rows.reduce((a, r) => ({ invested: a.invested + r.invested, current: a.current + r.current }), { invested: 0, current: 0 })
  const gain = total.current - total.invested
  const gainPct = total.invested ? (gain / total.invested) * 100 : 0

  const stats = [
    { label: 'Invested amount', value: usd(total.invested), cls: 'text-navy-900' },
    { label: 'Current value', value: usd(total.current), cls: 'text-navy-900' },
    { label: 'Unrealized gain / loss', value: `${signed(gain)} (${pct(gainPct)})`, cls: tone(gain) },
    { label: 'Positions', value: String(rows.length), cls: 'text-navy-900' },
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
        <CardHeader title="Positions" />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-100 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <th scope="col" className="px-5 py-2.5 text-left font-medium">Security</th>
                <th scope="col" className="px-3 py-2.5 text-left font-medium">Ticker</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Shares</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">On loan</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Invested amount</th>
                <th scope="col" className="px-3 py-2.5 text-right font-medium">Current value</th>
                <th scope="col" className="px-5 py-2.5 text-right font-medium">Gain / loss</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {rows.map((r) => (
                <tr key={r.ticker}>
                  <td className="px-5 py-2.5 font-medium text-navy-900">{r.name}</td>
                  <td className="px-3 py-2.5 text-slate-600">{r.ticker}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{num(r.shares)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums text-slate-600">{r.onLoan ? num(r.onLoan) : '–'}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{usd(r.invested)}</td>
                  <td className="px-3 py-2.5 text-right tabular-nums">{usd(r.current)}</td>
                  <td className={`px-5 py-2.5 text-right tabular-nums ${tone(r.gain)}`}>
                    {signed(r.gain)}
                    <span className="ml-1.5 text-xs">{pct(r.gainPct)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr className="border-t border-slate-200 bg-slate-50 font-semibold text-navy-900">
                <td className="px-5 py-3" colSpan={4}>Total</td>
                <td className="px-3 py-3 text-right tabular-nums">{usd(total.invested)}</td>
                <td className="px-3 py-3 text-right tabular-nums">{usd(total.current)}</td>
                <td className={`px-5 py-3 text-right tabular-nums ${tone(gain)}`}>
                  {signed(gain)}
                  <span className="ml-1.5 text-xs">{pct(gainPct)}</span>
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      </Card>
    </>
  )
}
