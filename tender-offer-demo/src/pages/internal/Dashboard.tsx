import { CloudDownload, Loader2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { FilingsTable } from '../../components/shared'
import { Button, Card, CardHeader, PageHeader, SearchInput } from '../../components/ui'
import { companyById, filings } from '../../data/mock'
import { useApp } from '../../state/AppState'
import type { Filing } from '../../types'

type TypeFilter = 'All' | 'New' | 'Amendment' | 'Response'
const TYPE_MAP: Record<Exclude<TypeFilter, 'All'>, Filing['kind']> = {
  New: 'Announcement',
  Amendment: 'Amendment',
  Response: 'Target Response',
}

export function useFilingFilters(source: Filing[]) {
  const [form, setForm] = useState('All')
  const [type, setType] = useState<TypeFilter>('All')
  const [q, setQ] = useState('')
  const forms = useMemo(() => ['All', ...Array.from(new Set(source.map((f) => f.form)))], [source])
  const rows = source.filter(
    (f) =>
      (form === 'All' || f.form === form) &&
      (type === 'All' || f.kind === TYPE_MAP[type]) &&
      (`${f.title} ${companyById(f.companyId).name}`.toLowerCase().includes(q.toLowerCase())),
  )
  return { form, setForm, forms, type, setType, q, setQ, rows }
}

export function FilingFilters({ f }: { f: ReturnType<typeof useFilingFilters> }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SearchInput value={f.q} onChange={f.setQ} placeholder="Search company or filing…" />
      <select
        value={f.form}
        onChange={(e) => f.setForm(e.target.value)}
        className="rounded-md border border-slate-300 bg-white px-2.5 py-2 text-sm"
        aria-label="Form type"
      >
        {f.forms.map((x) => (
          <option key={x} value={x}>
            {x === 'All' ? 'All forms' : x}
          </option>
        ))}
      </select>
      <div className="flex overflow-hidden rounded-md border border-slate-300 text-sm">
        {(['All', 'New', 'Amendment', 'Response'] as TypeFilter[]).map((t) => (
          <button
            key={t}
            onClick={() => f.setType(t)}
            className={`px-3 py-2 ${f.type === t ? 'bg-navy-800 text-white' : 'bg-white text-slate-600 hover:bg-slate-50'}`}
          >
            {t}
          </button>
        ))}
      </div>
    </div>
  )
}

export function Dashboard() {
  const { dashboardFilings, totalFetched, fetchFilings, fetching, fetchMessage, filingStatus, amendmentProcessed } = useApp()
  const f = useFilingFilters(dashboardFilings)

  const newEvents = dashboardFilings.filter((x) => x.kind === 'Announcement' && x.baseStatus !== 'Processed').length
  const amendments = dashboardFilings.filter((x) => x.kind === 'Amendment').length
  const review =
    dashboardFilings.filter((x) => filingStatus(x) === 'Needs Review').length + (amendmentProcessed ? 0 : 1)

  const stats = [
    { label: 'Filings fetched', value: totalFetched },
    { label: 'Tender-offer related', value: dashboardFilings.length },
    { label: 'New events', value: newEvents },
    { label: 'Amendments', value: amendments },
    { label: 'Requiring review', value: review },
  ]

  return (
    <>
      <PageHeader
        title="Today's SEC Filings"
        subtitle="New filings arrive from SEC EDGAR and are organized into the relevant tender-offer workflow. Demo feed showing tender-offer activity for Oct. 1–14, 2026."
        actions={
          <Button variant="primary" onClick={fetchFilings} disabled={fetching}>
            {fetching ? <Loader2 size={15} className="animate-spin" /> : <CloudDownload size={15} />}
            Fetch Today’s Filings
          </Button>
        }
      />
      <p className="-mt-3 mb-4 text-xs text-slate-500" aria-live="polite">
        {fetchMessage}
      </p>

      <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-5">
        {stats.map((s) => (
          <Card key={s.label} className="px-4 py-3">
            <div className="text-2xl font-semibold text-navy-900">{s.value}</div>
            <div className="text-xs text-slate-500">{s.label}</div>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader title="Tender-offer related filings" action={<FilingFilters f={f} />} />
        <FilingsTable rows={f.rows} />
      </Card>
    </>
  )
}

export function AllFilings() {
  const f = useFilingFilters(filings)
  return (
    <>
      <PageHeader title="All Filings" subtitle="Every tender-offer filing linked to an event, including historical filings." />
      <Card>
        <CardHeader title={`${f.rows.length} filings`} action={<FilingFilters f={f} />} />
        <FilingsTable rows={f.rows} />
      </Card>
    </>
  )
}
