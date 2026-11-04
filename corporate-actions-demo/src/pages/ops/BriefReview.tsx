import { CheckCircle2, ExternalLink, RotateCcw, ShieldAlert } from 'lucide-react'
import { Link } from 'react-router-dom'
import { Badge, Button, Card, Empty, PageHeader } from '../../components/ui'
import { REASON_LABEL } from '../../data/briefs'
import { fmtDate } from '../../data/store'
import { useApp } from '../../state/AppState'
import { useBrief } from '../../state/BriefState'

export function BriefReview() {
  const { heldItems, pendingCount, approve, revoke, setClientId, setAsOf } = useBrief()
  const { toast } = useApp()

  return (
    <>
      <PageHeader
        title="Brief Review"
        subtitle="The agent's checks hold doubtful items here. Nothing reaches a client until a reviewer clears it."
        actions={<Badge tone={pendingCount ? 'pending' : 'completed'}>{pendingCount} awaiting review</Badge>}
      />
      {heldItems.length === 0 ? (
        <Card><Empty>No items are waiting for review.</Empty></Card>
      ) : (
        <div className="space-y-3">
          {heldItems.map(({ key, client, asOf, item, approved }) => {
            const latest = item.sources[item.sources.length - 1]
            return (
              <Card key={key} className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1 basis-80">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {approved ? <Badge tone="completed"><CheckCircle2 size={11} /> Cleared</Badge> : <Badge tone="pending"><ShieldAlert size={11} /> Held</Badge>}
                      <Badge tone="brand">{item.actionLabel}</Badge>
                      <Badge>{item.ticker}</Badge>
                      <span className="text-xs text-slate-500">{client.name} · brief of {fmtDate(asOf)}</span>
                    </div>
                    <h3 className="mt-2 text-base font-semibold text-navy-900">{item.title}</h3>
                    <ul className="mt-2 space-y-1.5">
                      {item.review.reasons.map((r) => (
                        <li key={r.code + r.detail} className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-950">
                          <span className="font-semibold">{REASON_LABEL[r.code] ?? r.code}.</span> {r.detail}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-3 text-sm leading-relaxed text-slate-600"><span className="font-medium text-slate-700">Draft for the client:</span> {item.summary}</p>
                    <a href={latest.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline">
                      Check {latest.form} on SEC.gov <ExternalLink size={11} />
                    </a>
                  </div>
                  <div className="flex flex-col items-stretch gap-2">
                    {approved ? (
                      <>
                        <Button onClick={() => revoke(key)}><RotateCcw size={14} /> Hold again</Button>
                        <Link
                          to="/client/brief"
                          onClick={() => { setClientId(client.id); setAsOf(asOf) }}
                          className="text-center text-xs font-medium text-brand-700 hover:underline"
                        >
                          See it in the client brief
                        </Link>
                      </>
                    ) : (
                      <Button variant="primary" onClick={() => { approve(key); toast(`Cleared for ${client.name}`) }}>
                        <CheckCircle2 size={14} /> Clear for client
                      </Button>
                    )}
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </>
  )
}
