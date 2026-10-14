import { ArrowRight, ChevronDown, ChevronRight, FileText, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { companyById } from '../data/mock'
import { findEvidence, useApp, type OfferView } from '../state/AppState'
import { FIELD_LABELS, type FieldChange, type FieldKey, type Filing } from '../types'
import { Drawer } from './Layout'
import { Badge, Button, Empty, StatusBadge } from './ui'

// ---------------------------------------------------------------- Filings table

const TYPE_LABEL: Record<Filing['kind'], string> = {
  Announcement: 'Announcement',
  Amendment: 'Amendment',
  'Target Response': 'Target Response',
}

export function FilingsTable({ rows }: { rows: Filing[] }) {
  const { filingStatus } = useApp()
  const navigate = useNavigate()
  if (!rows.length) return <Empty>No filings match the current filters.</Empty>
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {['Filing', 'Company', 'Form', 'Filed', 'Type', 'Status'].map((h) => (
              <th key={h} className="px-4 py-2.5 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((f) => (
            <tr key={f.id} onClick={() => navigate(`/internal/filings/${f.id}`)} className="cursor-pointer hover:bg-navy-50/60">
              <td className="px-4 py-3 font-medium text-navy-800">{f.title}</td>
              <td className="px-4 py-3">{companyById(f.companyId).name}</td>
              <td className="px-4 py-3">
                <Badge>{f.form}</Badge>
              </td>
              <td className="whitespace-nowrap px-4 py-3 text-slate-600">
                {f.filedDate.replace(', 2026', '').replace(', 2025', ' ’25')} · {f.filedTime}
              </td>
              <td className="px-4 py-3">{TYPE_LABEL[f.kind]}</td>
              <td className="px-4 py-3">
                <StatusBadge label={filingStatus(f)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------- Before/after

export function ChangeCompare({ change, flash }: { change: FieldChange; flash?: boolean }) {
  return (
    <div className={`rounded-md border border-amber-200 bg-amber-50/60 p-3 ${flash ? 'flash' : ''}`}>
      <div className="mb-2 text-sm font-semibold text-navy-900">{FIELD_LABELS[change.field]}</div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-500">Previous</div>
          <div className="text-slate-500 line-through decoration-slate-400">{change.previous}</div>
        </div>
        <ArrowRight size={16} className="text-amber-600" />
        <div>
          <div className="text-[11px] uppercase tracking-wide text-slate-500">Current</div>
          <div className="font-semibold text-slate-900">{change.current}</div>
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- Version timeline

export function VersionTimeline({ view, flashLatest, defaultOpenLatest = false }: { view: OfferView; flashLatest?: boolean; defaultOpenLatest?: boolean }) {
  const [open, setOpen] = useState<string | null>(defaultOpenLatest || flashLatest ? view.current.id : null)
  const latest = view.current.id

  return (
    <ol className="relative space-y-3 border-l-2 border-slate-200 pl-6">
      {view.versions.map((v) => {
        const isOpen = open === v.id
        const isLatest = v.id === latest
        return (
          <li key={v.id} className={`relative ${flashLatest && isLatest && view.versions.length > 2 ? 'fade-up' : ''}`}>
            <span
              className={`absolute -left-[33px] top-3 grid h-4 w-4 place-items-center rounded-full border-2 bg-white ${
                isLatest ? 'border-navy-700' : 'border-slate-300'
              }`}
            >
              {isLatest && <span className="h-1.5 w-1.5 rounded-full bg-navy-700" />}
            </span>
            <div className="rounded-lg border border-slate-200 bg-white shadow-sm">
              <button
                onClick={() => setOpen(open === v.id ? null : v.id)}
                className="flex w-full items-center gap-3 px-4 py-3 text-left"
                aria-expanded={isOpen}
              >
                {isOpen ? <ChevronDown size={16} className="text-slate-400" /> : <ChevronRight size={16} className="text-slate-400" />}
                <span className="w-8 text-sm font-semibold text-navy-800">V{v.number}</span>
                <span className="w-20 text-sm text-slate-500">{v.date.replace(', 2026', '').replace(', 2025', ' ’25')}</span>
                <Badge>{v.form}</Badge>
                <span className="flex-1 text-sm text-slate-800">{v.summary}</span>
                {isLatest && <Badge tone="new">Current</Badge>}
              </button>
              {isOpen && (
                <div className="space-y-4 border-t border-slate-100 px-4 py-4">
                  {v.changes.length > 0 ? (
                    <div>
                      <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Material Changes</h4>
                      <div className="grid gap-3 sm:grid-cols-2">
                        {v.changes.map((c) => (
                          <ChangeCompare key={c.field} change={c} flash={flashLatest && isLatest} />
                        ))}
                      </div>
                    </div>
                  ) : (
                    <p className="text-sm text-slate-600">Initial version of the event record — no prior terms to compare.</p>
                  )}
                  {v.unchanged.length > 0 && (
                    <div>
                      <h4 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">Unchanged</h4>
                      <div className="flex flex-wrap gap-1.5">
                        {v.unchanged.map((u) => (
                          <Badge key={u}>{u}</Badge>
                        ))}
                      </div>
                    </div>
                  )}
                  <Link
                    to={`/internal/filings/${v.filingId}`}
                    className="inline-flex items-center gap-1.5 text-sm font-medium text-navy-700 hover:underline"
                  >
                    <FileText size={14} /> View source filing ({v.form})
                  </Link>
                </div>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

// ---------------------------------------------------------------- Evidence drawer

export function EvidenceDrawer({ view, field, onClose }: { view: OfferView; field: FieldKey | null; onClose: () => void }) {
  const ev = field ? findEvidence(view, field) : undefined
  return (
    <Drawer open={!!field} onClose={onClose} title="Source evidence">
      {field && (
        <div className="space-y-4">
          <div>
            <div className="text-xs uppercase tracking-wide text-slate-500">{FIELD_LABELS[field]}</div>
            <div className="mt-0.5 text-lg font-semibold text-navy-900">{view.current.fields[field]}</div>
          </div>
          {ev ? (
            <>
              <Badge tone="completed">
                <ShieldCheck size={12} /> Source verified
              </Badge>
              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <dt className="text-xs text-slate-500">Source filing</dt>
                  <dd className="font-medium">{ev.filing.form}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Filing date</dt>
                  <dd className="font-medium">{ev.filing.filedDate}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Version</dt>
                  <dd className="font-medium">V{ev.version.number}</dd>
                </div>
                <div>
                  <dt className="text-xs text-slate-500">Accession no.</dt>
                  <dd className="font-medium">{ev.filing.accession}</dd>
                </div>
              </dl>
              <div>
                <div className="mb-1.5 text-xs uppercase tracking-wide text-slate-500">Passage</div>
                <blockquote className="rounded-md border-l-4 border-amber-400 bg-amber-50 p-3 text-sm leading-relaxed text-slate-800">
                  “{ev.text}”
                </blockquote>
              </div>
              <Link to={`/internal/filings/${ev.filing.id}`}>
                <Button variant="primary">
                  <FileText size={15} /> Open in filing viewer
                </Button>
              </Link>
            </>
          ) : (
            <p className="text-sm text-slate-600">No source passage is linked to this field yet.</p>
          )}
        </div>
      )}
    </Drawer>
  )
}
