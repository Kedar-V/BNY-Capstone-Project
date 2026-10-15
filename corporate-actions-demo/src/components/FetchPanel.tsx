import { Check, Circle, Loader2, MinusCircle } from 'lucide-react'
import { useApp } from '../state/AppState'
import { Button, Modal } from './ui'

export function FetchPanel() {
  const { pipeline: p, closePipeline } = useApp()
  const active = p.steps.find((s) => s.status === 'active')
  const showBar = active && (active.id === 'download' || active.id === 'process' || active.id === 'extract')

  return (
    <Modal open={p.open} onClose={closePipeline} wide title={p.finished ? (p.foundCount ? 'Filings processed' : 'Up to date') : 'Fetching filings from SEC EDGAR'}>
      <div className="px-6 py-5">
        <ol className="space-y-0">
          {p.steps.map((s, i) => {
            const last = i === p.steps.length - 1
            return (
              <li key={s.id} className="relative flex gap-4 pb-5 last:pb-0">
                {!last && <span className={`absolute left-[13px] top-7 h-[calc(100%-1.75rem)] w-0.5 transition-colors duration-500 ${s.status === 'done' ? 'bg-brand-500' : 'bg-slate-200'}`} />}
                <span
                  className={`relative z-10 grid h-7 w-7 shrink-0 place-items-center rounded-full transition-all duration-300 ${
                    s.status === 'done'
                      ? 'bg-brand-600 text-white'
                      : s.status === 'active'
                        ? 'bg-white text-brand-600 ring-2 ring-brand-500'
                        : s.status === 'skipped'
                          ? 'bg-slate-100 text-slate-400'
                          : 'bg-white text-slate-300 ring-1 ring-slate-200'
                  }`}
                >
                  {s.status === 'done' ? <Check size={15} strokeWidth={3} /> : s.status === 'active' ? <Loader2 size={15} className="animate-spin" /> : s.status === 'skipped' ? <MinusCircle size={15} /> : <Circle size={9} />}
                </span>
                <div className="min-w-0 flex-1 pt-0.5">
                  <div className={`text-sm font-semibold ${s.status === 'pending' || s.status === 'skipped' ? 'text-slate-400' : 'text-navy-900'}`}>{s.title}</div>
                  {s.status !== 'pending' && s.detail && <div className="fade-in mt-0.5 text-xs text-slate-500">{s.detail}</div>}
                  {s.id === 'found' && s.status === 'done' && p.chips.length > 0 && (
                    <div className="fade-in mt-2 flex flex-wrap gap-1.5">
                      {p.chips.map((c) => (
                        <span key={c.label} className="rounded-md bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                          {c.label} <span className="text-brand-700">×{c.count}</span>
                        </span>
                      ))}
                    </div>
                  )}
                  {s.status === 'active' && showBar && active?.id === s.id && (
                    <div className="fade-in mt-2">
                      <div className="h-1.5 overflow-hidden rounded-full bg-slate-100">
                        <div className="h-full rounded-full bg-brand-500 transition-all duration-200" style={{ width: `${Math.round(p.progress * 100)}%` }} />
                      </div>
                      {p.current && <div className="mt-1.5 truncate text-xs font-medium text-navy-700">{p.current}</div>}
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      </div>
      <div className="flex items-center justify-between border-t border-slate-100 bg-slate-50 px-6 py-3.5">
        <span className="text-xs text-slate-500">{p.running ? 'This usually takes about a minute…' : p.foundCount ? `${p.foundCount} new filings are now in the Filings Monitor.` : 'No action needed.'}</span>
        <Button variant="primary" onClick={closePipeline} disabled={p.running}>
          {p.finished && p.foundCount ? 'View new filings' : 'Close'}
        </Button>
      </div>
    </Modal>
  )
}
