import { CloudDownload, FileStack, Gavel, Handshake, Layers, RefreshCw } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Button, Card, CardHeader, Empty, PageHeader, SearchInput, Segmented, ShowMore, StatusBadge, TypeBadge } from '../../components/ui'
import { fmtDate, shortStatus } from '../../data/store'
import { useApp } from '../../state/AppState'
import type { ActionType } from '../../types'

const PAGE = 25

export function Dashboard() {
  const { filings, events, fetchedIds, runFetch, pipeline } = useApp()
  const navigate = useNavigate()
  const [type, setType] = useState<'all' | ActionType>('all')
  const [form, setForm] = useState('All')
  const [q, setQ] = useState('')
  const [shown, setShown] = useState(PAGE)

  const versionOf = useMemo(() => {
    const m = new Map<string, number>()
    events.forEach((e) => e.versions.forEach((v) => m.set(v.filing.id, v.number)))
    return m
  }, [events])

  const forms = useMemo(() => ['All', ...Array.from(new Set(filings.map((f) => f.form))).sort()], [filings])
  const rows = useMemo(
    () =>
      [...filings]
        .filter((f) => (type === 'all' || f.action === type) && (form === 'All' || f.form === form) && `${f.subject} ${f.counterparty ?? ''} ${f.registrant ?? ''}`.toLowerCase().includes(q.toLowerCase()))
        .sort((a, b) => Number(fetchedIds.has(b.id)) - Number(fetchedIds.has(a.id)) || b.filedDate.localeCompare(a.filedDate) || a.subject.localeCompare(b.subject)),
    [filings, type, form, q, fetchedIds],
  )

  const tender = filings.filter((f) => f.action === 'tender_offer').length
  const stats = [
    { label: 'Filings processed', value: filings.length, icon: FileStack },
    { label: 'Tender offer filings', value: tender, icon: Gavel },
    { label: 'Merger filings', value: filings.length - tender, icon: Handshake },
    { label: 'Corporate actions tracked', value: events.length, icon: Layers },
    { label: 'Amendments linked', value: filings.length - events.length, icon: RefreshCw },
  ]

  return (
    <>
      <PageHeader
        title="Filings Monitor"
        subtitle="SEC filings are retrieved from EDGAR, processed with language models and organized into tender offer and merger records."
        actions={
          <Button variant="primary" onClick={runFetch} disabled={pipeline.running}>
            <CloudDownload size={16} /> Fetch Latest Filings
          </Button>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-5">
        {stats.map((s) => (
          <Card key={s.label} className="p-4">
            <div className="flex items-center justify-between text-slate-400">
              <span className="text-xs font-medium text-slate-500">{s.label}</span>
              <s.icon size={16} />
            </div>
            <div className="mt-1.5 text-2xl font-semibold tabular-nums text-navy-900">{s.value}</div>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader
          title="Recent filings"
          subtitle={`${rows.length} filings`}
          action={
            <div className="flex flex-wrap items-center gap-2">
              <SearchInput value={q} onChange={(v) => { setQ(v); setShown(PAGE) }} placeholder="Search company…" />
              <select value={form} onChange={(e) => { setForm(e.target.value); setShown(PAGE) }} className="rounded-lg border border-slate-300 bg-white px-2.5 py-2 text-sm" aria-label="Form type">
                {forms.map((x) => (
                  <option key={x} value={x}>
                    {x === 'All' ? 'All forms' : x}
                  </option>
                ))}
              </select>
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
          <Empty>No filings match the current filters.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  {['Company', 'Counterparty', 'Type', 'Form', 'Filed', 'Record', 'Status'].map((h) => (
                    <th key={h} className="px-4 py-2.5 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {rows.slice(0, shown).map((f) => {
                  const v = versionOf.get(f.id) ?? 1
                  const isNew = fetchedIds.has(f.id)
                  return (
                    <tr key={f.id} onClick={() => navigate(`/internal/filings/${f.id}`)} className={`cursor-pointer hover:bg-brand-50/50 ${isNew ? 'row-new' : ''}`}>
                      <td className="max-w-[300px] px-4 py-3 font-medium text-navy-900">
                        <div className="flex items-center gap-2">
                          <span className="truncate">{f.subject}</span>
                          {isNew && <Badge tone="brand">New</Badge>}
                        </div>
                      </td>
                      <td className="max-w-[200px] truncate px-4 py-3 text-slate-600">{f.counterparty ?? '—'}</td>
                      <td className="px-4 py-3"><TypeBadge action={f.action} /></td>
                      <td className="px-4 py-3"><Badge>{f.form}</Badge></td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-600">{fmtDate(f.filedDate)}</td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-600">{v === 1 ? 'New event' : `Update · V${v}`}</td>
                      <td className="px-4 py-3"><StatusBadge label={shortStatus(f.fields.event_status)} /></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
        <ShowMore shown={shown} total={rows.length} onMore={() => setShown((n) => n + PAGE)} />
      </Card>
    </>
  )
}
