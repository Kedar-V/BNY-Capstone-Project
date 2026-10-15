import { Bell, CheckCircle2, FileText, Home, Layers, LayoutDashboard, Star, type LucideIcon } from 'lucide-react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useApp } from '../state/AppState'
import { FetchPanel } from './FetchPanel'

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  badge?: number
}

export function Shell({ mode }: { mode: 'internal' | 'client' }) {
  const { toasts, notifications, readIds } = useApp()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const unread = notifications.filter((n) => !readIds.has(n.id)).length
  const internal = mode === 'internal'

  const nav: NavItem[] = internal
    ? [
        { to: '/internal/dashboard', label: 'Filings Monitor', icon: LayoutDashboard },
        { to: '/internal/events', label: 'Corporate Actions', icon: Layers },
      ]
    : [
        { to: '/client/home', label: 'Overview', icon: Home },
        { to: '/client/notifications', label: 'Notifications', icon: Bell, badge: unread },
        { to: '/client/watchlist', label: 'Watchlist', icon: Star },
      ]

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white px-5 py-2.5">
        <div className="flex items-center gap-4">
          <img src="/bny-logo.svg" alt="BNY" className="h-6 w-auto" />
          <span className="hidden h-6 w-px bg-slate-200 sm:block" />
          <div className="hidden sm:block">
            <div className="text-sm font-semibold leading-tight text-navy-900">Corporate Actions</div>
            <div className="text-[11px] leading-tight text-slate-500">Tender Offers &amp; Mergers</div>
          </div>
        </div>

        <div className="flex rounded-lg bg-slate-100 p-0.5 text-sm" role="tablist" aria-label="Experience">
          {(['internal', 'client'] as const).map((m) => (
            <button
              key={m}
              role="tab"
              aria-selected={mode === m}
              onClick={() => navigate(m === 'internal' ? '/internal/dashboard' : '/client/home')}
              className={`rounded-md px-4 py-1.5 font-medium transition-all ${mode === m ? 'bg-navy-900 text-white shadow-sm' : 'text-slate-500 hover:text-slate-900'}`}
            >
              {m === 'internal' ? 'Operations' : 'Client Portal'}
            </button>
          ))}
        </div>

        <div className="hidden items-center gap-2 text-xs text-slate-500 md:flex">
          <span className="h-2 w-2 rounded-full bg-emerald-500" /> Connected to SEC EDGAR
        </div>
      </header>

      <div className="flex flex-1 flex-col md:flex-row">
        <aside className={`shrink-0 md:w-60 ${internal ? 'bg-navy-900 text-navy-100' : 'border-r border-slate-200 bg-white text-slate-700'}`}>
          <div className={`px-5 pt-5 text-[11px] font-semibold uppercase tracking-wider ${internal ? 'text-navy-300' : 'text-slate-400'}`}>
            {internal ? 'Operations' : 'Client Portal'}
          </div>
          <nav className="flex gap-1 overflow-x-auto p-3 md:flex-col">
            {nav.map((n) => {
              const on = pathname.startsWith(n.to) || (n.to.endsWith('/events') && pathname.includes('/events/'))
              return (
                <NavLink
                  key={n.to}
                  to={n.to}
                  className={`flex items-center gap-3 whitespace-nowrap rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                    on ? (internal ? 'bg-white/15 text-white' : 'bg-brand-50 text-navy-900') : internal ? 'hover:bg-white/10' : 'hover:bg-slate-100'
                  }`}
                >
                  <n.icon size={17} />
                  <span className="flex-1">{n.label}</span>
                  {!!n.badge && <span className="rounded-full bg-rose-500 px-1.5 text-[11px] font-semibold text-white">{n.badge}</span>}
                </NavLink>
              )
            })}
          </nav>
        </aside>

        <main className="min-w-0 flex-1 p-5 md:p-8">
          <div key={pathname} className="fade-up mx-auto max-w-6xl">
            <Outlet />
          </div>
        </main>
      </div>

      <footer className="flex items-center justify-center gap-2 border-t border-slate-200 bg-white px-4 py-2.5 text-xs text-slate-500">
        <FileText size={12} /> Source: SEC EDGAR public filings · BNY Corporate Actions
      </footer>

      <FetchPanel />

      <div className="pointer-events-none fixed bottom-14 right-4 z-[60] flex flex-col gap-2">
        {toasts.map((t) => (
          <div key={t.id} className="fade-up pointer-events-auto flex items-center gap-2 rounded-lg bg-navy-900 px-4 py-2.5 text-sm text-white shadow-lg">
            <CheckCircle2 size={16} className="text-emerald-400" />
            {t.message}
          </div>
        ))}
      </div>
    </div>
  )
}
