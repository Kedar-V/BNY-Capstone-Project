import {
  Bell,
  Building2,
  CheckCircle2,
  FileText,
  Info,
  LayoutDashboard,
  Lightbulb,
  Star,
  RotateCcw,
  X,
  Home,
  type LucideIcon,
} from 'lucide-react'
import { useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useApp } from '../state/AppState'
import { Modal } from './ui'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  badge?: number
}

export function Shell({ mode }: { mode: 'internal' | 'client' }) {
  const { toasts, reset, notifications } = useApp()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [aboutOpen, setAboutOpen] = useState(false)
  const unread = notifications.filter((n) => !n.read).length

  const internalNav: NavItem[] = [
    { to: '/internal/dashboard', label: 'Daily Filings', icon: LayoutDashboard },
    { to: '/internal/filings', label: 'All Filings', icon: FileText },
    { to: '/internal/companies/blueriver', label: 'Companies', icon: Building2 },
    { to: '/internal/tender-offers/to-acme-blueriver', label: 'Tender Offer Record', icon: CheckCircle2 },
  ]
  const clientNav: NavItem[] = [
    { to: '/client/home', label: 'Home', icon: Home },
    { to: '/client/notifications', label: 'Notifications', icon: Bell, badge: unread },
    { to: '/client/watchlist', label: 'Watchlist', icon: Star },
    { to: '/client/recommendations', label: 'Suggested Actions', icon: Lightbulb },
  ]
  const nav = mode === 'internal' ? internalNav : clientNav
  const internal = mode === 'internal'

  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 bg-navy-900 px-4 py-2.5 text-white">
        <div className="flex items-center gap-3">
          <div className="grid h-8 w-8 place-items-center rounded bg-white/10 text-sm font-bold">TO</div>
          <div>
            <div className="text-sm font-semibold leading-tight">Tender Offer Intelligence</div>
            <div className="text-[11px] leading-tight text-navy-200">Concept demo · synthetic data</div>
          </div>
        </div>

        <div className="flex rounded-md bg-navy-950/60 p-0.5 text-sm" role="tablist" aria-label="Experience">
          {(['internal', 'client'] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => navigate(m === 'internal' ? '/internal/dashboard' : '/client/home')}
              className={`rounded px-3.5 py-1.5 font-medium transition-colors ${
                mode === m ? 'bg-white text-navy-900' : 'text-navy-200 hover:text-white'
              }`}
            >
              {m === 'internal' ? 'BNY Operations' : 'Client Portal'}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1 text-sm">
          <button onClick={() => setAboutOpen(true)} className="flex items-center gap-1.5 rounded px-2.5 py-1.5 text-navy-100 hover:bg-white/10">
            <Info size={15} /> About this demo
          </button>
          <button onClick={reset} className="flex items-center gap-1.5 rounded px-2.5 py-1.5 text-navy-100 hover:bg-white/10">
            <RotateCcw size={15} /> Reset demo
          </button>
        </div>
      </header>

      <div className="flex flex-1 flex-col md:flex-row">
        <aside
          className={`shrink-0 border-b md:w-56 md:border-b-0 md:border-r ${
            internal ? 'border-navy-800 bg-navy-800 text-navy-100' : 'border-slate-200 bg-white text-slate-700'
          }`}
        >
          <div className={`px-4 pt-4 text-[11px] font-semibold uppercase tracking-wider ${internal ? 'text-navy-300' : 'text-slate-400'}`}>
            {internal ? 'BNY Operations' : 'Client Portal'}
          </div>
          <nav className="flex gap-1 overflow-x-auto p-2 md:flex-col">
            {nav.map((n) => {
              const on = pathname.startsWith(n.to)
              return (
                <NavLink
                  key={n.to}
                  to={n.to}
                  className={`flex items-center gap-2.5 whitespace-nowrap rounded-md px-3 py-2 text-sm font-medium ${
                    on
                      ? internal
                        ? 'bg-white/15 text-white'
                        : 'bg-navy-50 text-navy-800'
                      : internal
                        ? 'hover:bg-white/10'
                        : 'hover:bg-slate-100'
                  }`}
                >
                  <n.icon size={16} />
                  <span className="flex-1">{n.label}</span>
                  {!!n.badge && <span className="rounded-full bg-rose-500 px-1.5 text-[11px] font-semibold text-white">{n.badge}</span>}
                </NavLink>
              )
            })}
          </nav>
        </aside>

        <main className="min-w-0 flex-1 p-4 md:p-6">
          <div key={pathname} className="fade-up mx-auto max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>

      <footer className="border-t border-slate-200 bg-white px-4 py-2 text-center text-xs text-slate-500">
        Concept demonstration using synthetic data. Not investment advice.{' '}
        <button onClick={() => setAboutOpen(true)} className="font-medium text-navy-700 underline-offset-2 hover:underline">
          What is real vs. conceptual?
        </button>
      </footer>

      <Modal open={aboutOpen} onClose={() => setAboutOpen(false)} title="What is real vs. conceptual">
        <div className="space-y-4 text-sm text-slate-700">
          <div>
            <h4 className="mb-1.5 font-semibold text-navy-900">Currently being built</h4>
            <ul className="list-disc space-y-1 pl-5">
              <li>SEC EDGAR data ingestion</li>
              <li>Tender-offer extraction</li>
              <li>Standardized reference / evaluation dataset</li>
              <li>Field-level evaluation</li>
              <li>Document / event linking</li>
            </ul>
          </div>
          <div>
            <h4 className="mb-1.5 font-semibold text-navy-900">This concept UI demonstrates potential downstream capabilities</h4>
            <ul className="list-disc space-y-1 pl-5">
              <li>Canonical tender-offer event records</li>
              <li>Amendment / change detection</li>
              <li>Version history</li>
              <li>Evidence review</li>
              <li>Client notifications</li>
              <li>Subscriptions / watchlists</li>
              <li>Suggested next steps</li>
            </ul>
          </div>
          <p className="rounded bg-slate-50 p-3 text-xs text-slate-600">
            All companies, filings, prices and dates shown are synthetic. These downstream capabilities are not production-ready.
          </p>
        </div>
      </Modal>

      <div className="pointer-events-none fixed bottom-14 right-4 z-[60] flex flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className="fade-up pointer-events-auto flex items-center gap-2 rounded-md bg-navy-900 px-4 py-2.5 text-sm text-white shadow-lg">
            <CheckCircle2 size={16} className="text-emerald-400" />
            {t.message}
          </div>
        ))}
      </div>
    </div>
  )
}

export function Drawer({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-slate-900/30" onClick={onClose}>
      <aside className="slide-in h-full w-full max-w-md overflow-y-auto bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="sticky top-0 flex items-center justify-between border-b border-slate-100 bg-white px-5 py-3">
          <h2 className="text-base font-semibold text-navy-900">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 text-slate-500 hover:bg-slate-100">
            <X size={18} />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </aside>
    </div>
  )
}
