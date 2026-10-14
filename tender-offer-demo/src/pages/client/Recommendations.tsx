import { AlertCircle, CalendarClock, CheckCheck, CheckCircle2, Undo2, X } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button, Card, Empty, PageHeader, Tabs } from '../../components/ui'
import { companyById } from '../../data/mock'
import { useApp } from '../../state/AppState'
import type { ActionStatus } from '../../types'

const ICON = {
  attention: <AlertCircle size={18} className="text-amber-600" />,
  deadline: <CalendarClock size={18} className="text-sky-600" />,
  clear: <CheckCircle2 size={18} className="text-emerald-600" />,
}

export function Recommendations() {
  const { actions, setActionStatus, amendmentProcessed } = useApp()
  const navigate = useNavigate()
  const [tab, setTab] = useState<ActionStatus>('open')
  const rows = actions.filter((a) => a.status === tab)

  return (
    <>
      <PageHeader
        title="Suggested Actions"
        subtitle="Items that may need your attention. These are prompts to review information, not investment advice or a recommendation to tender."
      />
      <Tabs
        tabs={(['open', 'reviewed', 'dismissed'] as const).map((s) => ({
          id: s,
          label: `${s[0].toUpperCase()}${s.slice(1)} (${actions.filter((a) => a.status === s).length})`,
        }))}
        value={tab}
        onChange={setTab}
      />
      <div className="mt-4 grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        {rows.length === 0 && (
          <Card className="md:col-span-2 lg:col-span-3">
            <Empty>Nothing here.</Empty>
          </Card>
        )}
        {rows.map((a) => (
          <Card key={a.id} className="fade-up flex flex-col p-4">
            <div className="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-slate-500">
              {ICON[a.tone]} {companyById(a.companyId).name}
            </div>
            <h3 className="text-base font-semibold text-navy-900">{amendmentProcessed && a.amendedTitle ? a.amendedTitle : a.title}</h3>
            <p className="mt-1 flex-1 text-sm text-slate-600">{amendmentProcessed && a.amendedBody ? a.amendedBody : a.body}</p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Button variant="primary" size="sm" onClick={() => navigate(`/client/tender-offers/${a.offerId}`)}>
                Open event
              </Button>
              {a.status === 'open' ? (
                <>
                  <Button size="sm" onClick={() => setActionStatus(a.id, 'reviewed')}>
                    <CheckCheck size={13} /> Mark reviewed
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setActionStatus(a.id, 'dismissed')}>
                    <X size={13} /> Dismiss
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="ghost" onClick={() => setActionStatus(a.id, 'open')}>
                  <Undo2 size={13} /> Restore
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>
    </>
  )
}
