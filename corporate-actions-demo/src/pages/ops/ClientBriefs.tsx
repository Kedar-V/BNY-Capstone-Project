import { CheckCircle2, ExternalLink, RotateCcw, ShieldAlert } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { Badge, Button, Card, Empty, PageHeader, Tabs } from '../../components/ui'
import { briefData, REASON_LABEL } from '../../data/briefs'
import { fmtDate } from '../../data/store'
import { useApp } from '../../state/AppState'
import { useBrief } from '../../state/BriefState'
import { BriefView, Select } from '../client/Brief'
import { Holdings } from '../client/Holdings'

type TabId = 'brief' | 'holdings' | 'review'

const RELATIONSHIP_MANAGER = 'William'

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="min-w-[88px]">
      <dt className="text-xs text-slate-500">{label}</dt>
      <dd className="mt-0.5 text-sm font-semibold tabular-nums text-navy-900">{value}</dd>
    </div>
  )
}

/** Items the agent's checks held back. A client does not see them until someone approves. */
function ReviewQueue({ onOpenBrief }: { onOpenBrief: () => void }) {
  const { heldItems, approve, revoke, setClientId, setAsOf, setCadence } = useBrief()
  const { toast } = useApp()

  if (heldItems.length === 0) return <Card><Empty>Nothing is waiting for review.</Empty></Card>

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        These items failed an automatic check, so they are not in the client's brief yet. Check each one against the filing, then approve it or keep it on hold.
      </p>
      {heldItems.map(({ key, client, asOf, item, approved }) => {
        const latest = item.sources[item.sources.length - 1]
        return (
          <Card key={key} className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0 flex-1 basis-80">
                <div className="flex flex-wrap items-center gap-1.5">
                  {approved ? <Badge tone="completed"><CheckCircle2 size={11} /> Approved</Badge> : <Badge tone="pending"><ShieldAlert size={11} /> On hold</Badge>}
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
                <p className="mt-3 text-sm leading-relaxed text-slate-600">
                  <span className="font-medium text-slate-700">Wording the client would see:</span> {item.summary}
                </p>
                <a href={latest.url} target="_blank" rel="noreferrer" className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-brand-700 hover:underline">
                  Check {latest.form} on SEC.gov <ExternalLink size={11} />
                </a>
              </div>
              <div className="flex flex-col items-stretch gap-2">
                {approved ? (
                  <>
                    <Button onClick={() => revoke(key)}><RotateCcw size={14} /> Put back on hold</Button>
                    <button
                      onClick={() => {
                        setClientId(client.id)
                        setCadence(client.cadence)
                        setAsOf(asOf)
                        onOpenBrief()
                      }}
                      className="text-center text-xs font-medium text-brand-700 hover:underline"
                    >
                      View in the client's brief
                    </button>
                  </>
                ) : (
                  <Button variant="primary" onClick={() => { approve(key); toast(`Approved for ${client.name}`) }}>
                    <CheckCircle2 size={14} /> Approve for client
                  </Button>
                )}
              </div>
            </div>
          </Card>
        )
      })}
    </div>
  )
}

/** Relationship manager workspace: pick a client, review the brief and holdings they see, and clear held items. */
export function ClientBriefs() {
  const { client, setClientId, setCadence, heldCount, pendingCount } = useBrief()
  const [params, setParams] = useSearchParams()
  const tab: TabId = params.get('tab') === 'review' ? 'review' : params.get('tab') === 'holdings' ? 'holdings' : 'brief'
  const setTab = (t: TabId) => setParams(t === 'brief' ? {} : { tab: t }, { replace: true })

  const switchClient = (id: string) => {
    setClientId(id)
    const next = briefData.clients.find((c) => c.id === id)
    if (next) setCadence(next.cadence)
  }

  return (
    <>
      <PageHeader
        eyebrow="Relationship manager"
        title={`Hey ${RELATIONSHIP_MANAGER},`}
        subtitle={`Here are your clients' briefs. ${
          pendingCount > 0
            ? `${pendingCount} ${pendingCount > 1 ? 'items need' : 'item needs'} your review before ${pendingCount > 1 ? 'they go' : 'it goes'} to a client.`
            : 'Nothing is waiting for your review.'
        }`}
      />

      <Card className="mb-5 px-5 py-4">
        <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-4">
          <div className="min-w-[260px] flex-1 basis-72">
            <Select label="Client" value={client.id} onChange={switchClient} options={briefData.clients.map((c) => ({ id: c.id, label: c.name }))} />
          </div>
          <dl className="flex flex-wrap gap-x-8 gap-y-3">
            <Metric label="Brief frequency" value={client.cadence === 'weekly' ? 'Weekly' : 'Daily'} />
            <Metric label="Positions" value={client.positions.length} />
            <Metric label="Watchlist" value={client.watchlist.length} />
            <Metric label="On hold for this brief" value={heldCount} />
          </dl>
        </div>
        <p className="mt-3 border-t border-slate-100 pt-3 text-xs text-slate-500">{client.type}</p>
      </Card>

      <Tabs<TabId>
        tabs={[
          { id: 'brief', label: 'Brief' },
          { id: 'holdings', label: 'Holdings' },
          {
            id: 'review',
            label: (
              <span className="inline-flex items-center gap-2">
                Needs review
                {pendingCount > 0 && <span className="rounded-full bg-rose-500 px-1.5 text-[11px] font-semibold text-white">{pendingCount}</span>}
              </span>
            ),
          },
        ]}
        value={tab}
        onChange={setTab}
      />
      <div className="mt-5">
        {tab === 'brief' && <BriefView embedded />}
        {tab === 'holdings' && <Holdings embedded />}
        {tab === 'review' && <ReviewQueue onOpenBrief={() => setTab('brief')} />}
      </div>
    </>
  )
}
