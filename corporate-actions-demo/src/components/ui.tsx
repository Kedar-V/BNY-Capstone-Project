import { X } from 'lucide-react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { toneFor } from '../data/store'

export type Tone = 'new' | 'amended' | 'pending' | 'completed' | 'review' | 'neutral' | 'brand'

const TONES: Record<Tone, string> = {
  new: 'bg-sky-50 text-sky-700 ring-sky-200',
  amended: 'bg-violet-50 text-violet-700 ring-violet-200',
  pending: 'bg-amber-50 text-amber-800 ring-amber-200',
  completed: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  review: 'bg-rose-50 text-rose-700 ring-rose-200',
  neutral: 'bg-slate-100 text-slate-600 ring-slate-200',
  brand: 'bg-brand-50 text-brand-700 ring-brand-200',
}

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}>
      {children}
    </span>
  )
}

export const StatusBadge = ({ label }: { label: string }) => <Badge tone={toneFor(label)}>{label}</Badge>

export function TypeBadge({ action }: { action: 'tender_offer' | 'merger' }) {
  return action === 'tender_offer' ? <Badge tone="brand">Tender Offer</Badge> : <Badge tone="amended">Merger</Badge>
}

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>{children}</div>
}

export function CardHeader({ title, action, subtitle }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
      <div>
        <h3 className="text-sm font-semibold text-navy-900">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  )
}

export function PageHeader({ title, subtitle, actions, eyebrow }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-500">{eyebrow}</div>}
        <h1 className="text-2xl font-semibold tracking-tight text-navy-900">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-slate-600">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

type Variant = 'primary' | 'secondary' | 'ghost'
const VARIANTS: Record<Variant, string> = {
  primary: 'bg-navy-800 text-white shadow-sm hover:bg-navy-700 disabled:bg-slate-300',
  secondary: 'border border-slate-300 bg-white text-slate-700 hover:bg-slate-50 disabled:text-slate-400',
  ghost: 'text-navy-700 hover:bg-navy-50',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  className = '',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: 'sm' | 'md' }) {
  return (
    <button
      {...rest}
      className={`inline-flex items-center justify-center gap-1.5 rounded-lg font-medium transition-colors disabled:cursor-not-allowed ${
        size === 'sm' ? 'px-2.5 py-1 text-xs' : 'px-4 py-2 text-sm'
      } ${VARIANTS[variant]} ${className}`}
    />
  )
}

export function Segmented<T extends string>({ options, value, onChange }: { options: { id: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg bg-slate-100 p-0.5 text-sm">
      {options.map((o) => (
        <button
          key={o.id}
          onClick={() => onChange(o.id)}
          className={`rounded-md px-3 py-1.5 font-medium transition-all ${value === o.id ? 'bg-white text-navy-900 shadow-sm' : 'text-slate-500 hover:text-slate-800'}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: ReactNode }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-slate-200">
      {tabs.map((t) => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`-mb-px whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-medium transition-colors ${
            value === t.id ? 'border-brand-600 text-navy-900' : 'border-transparent text-slate-500 hover:text-slate-800'
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  )
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={() => onChange(!checked)}
      className={`relative h-5 w-9 shrink-0 rounded-full transition-colors ${checked ? 'bg-brand-600' : 'bg-slate-300'}`}
    >
      <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${checked ? 'left-[18px]' : 'left-0.5'}`} />
    </button>
  )
}

export function Modal({ open, onClose, title, children, wide }: { open: boolean; onClose: () => void; title: ReactNode; children: ReactNode; wide?: boolean }) {
  if (!open) return null
  return (
    <div className="fade-in fixed inset-0 z-50 flex items-center justify-center bg-navy-950/50 p-4 backdrop-blur-[2px]" onClick={onClose}>
      <div className={`pop w-full ${wide ? 'max-w-2xl' : 'max-w-lg'} overflow-hidden rounded-2xl bg-white shadow-2xl`} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
          <h2 className="text-base font-semibold text-navy-900">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-slate-500 hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}

export function Drawer({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: ReactNode }) {
  if (!open) return null
  return (
    <div className="fade-in fixed inset-0 z-40 flex justify-end bg-navy-950/30" onClick={onClose}>
      <aside className="slide-in h-full w-full max-w-md overflow-y-auto bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-100 bg-white px-5 py-3.5">
          <h2 className="text-base font-semibold text-navy-900">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-slate-500 hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>
        <div className="px-5 py-5">{children}</div>
      </aside>
    </div>
  )
}

export function SearchInput({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <input
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-100 sm:w-64"
    />
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-12 text-center text-sm text-slate-500">{children}</div>
}

export function ShowMore({ shown, total, onMore }: { shown: number; total: number; onMore: () => void }) {
  if (shown >= total) return null
  return (
    <div className="border-t border-slate-100 p-3 text-center">
      <Button variant="ghost" onClick={onMore}>
        Show more ({total - shown} remaining)
      </Button>
    </div>
  )
}

/** Splits pipe-delimited lists into bullets, otherwise returns text. */
export function Value({ text }: { text: string }) {
  const parts = text.split(' | ')
  if (parts.length < 2) return <>{text}</>
  return (
    <ul className="list-disc space-y-0.5 pl-4 text-left">
      {parts.map((p, i) => (
        <li key={i}>{p}</li>
      ))}
    </ul>
  )
}
