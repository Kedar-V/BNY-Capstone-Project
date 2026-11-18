import { CheckCircle2, ExternalLink, RotateCcw, ShieldAlert } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { Badge, Button, Card, CardHeader, Empty, PageHeader, Tabs } from '../../components/ui'
import { briefData, dueLabel, REASON_LABEL, type BriefClient } from '../../data/briefs'
import { fmtDate } from '../../data/store'
import { useApp } from '../../state/AppState'
import { useBrief, type ClientView } from '../../state/BriefState'
import { BriefView, DATE_OPTIONS, Select } from '../client/Brief'
import { Holdings } from '../client/Holdings'

type TabId = 'brief' | 'holdings' | 'review'

/** What a relationship manager needs to triage a client: how many instructions are due, how soon, and what is on hold. */
function triage(view: ClientView) {
  const actions = view.visibleItems.filter((i) => i.tier === 'action')
  const due = actions.filter((i) => i.cutoff && !i.cutoff.passed).sort((a, b) => a.cutoff!.daysAway - b.cutoff!.daysAway)
  return { actions: actions.length, passed: actions.filter((i) => i.cutoff?.passed).length, next: due[0]?.cutoff, held: view.heldCount }
}

function ClientTable({ selected, onSelect }: { selected: string; onSelect: (c: BriefClient) => void }) {
  const { asOf, viewOf } = useBrief()
  return (
    <Card className="mb-6">
      <CardHeader title="Your clients" subtitle={`Briefs as of ${fmtDate(asOf)}. Select a client to see the brief they receive and their holdings.`} />
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-100 bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <th scope="col" className="px-5 py-2.5 font-medium">Client</th>
              <th scope="col" className="px-3 py-2.5 font-medium">Brief</th>
              <th scope="col" className="px-3 py-2.5 font-medium">Action needed</th>
              <th scope="col" className="px-3 py-2.5 font-medium">Next BNY cut-off</th>
              <th scope="col" className="px-5 py-2.5 font-medium">On hold</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {briefData.clients.map((c) => {
              const t = triage(viewOf(c, asOf, c.cadence))
              const on = c.id === selected
              return (
                <tr
                  key={c.id}
                  onClick={() => onSelect(c)}
                  className={`cursor-pointer transition-colors ${on ? 'bg-brand-50 shadow-[inset_3px_0_0_#217f8f]' : 'hover:bg-slate-50'}`}
                >
                  <td className="px-5 py-3">
                    <button type="button" onClick={(e) => { e.stopPropagation(); onSelect(c) }} aria-pressed={on} className="text-left">
                      <span className="block font-medium text-navy-900">{c.name}</span>
                      <span className="block text-xs text-slate-500">{c.type}</span>
                    </button>
                  </td>
                  <td className="px-3 py-3 text-slate-600">{c.cadence === 'weekly' ? 'Weekly' : 'Daily'}</td>
                  <td className="px-3 py-3">
                    <span className={`text-base font-semibold tabular-nums ${t.actions ? 'text-rose-700' : 'text-slate-300'}`}>{t.actions}</span>
                    {t.passed > 0 && <span className="ml-2"><Badge tone="review">{t.passed} cut-off passed</Badge></span>}
                  </td>
                  <td className="px-3 py-3">
                    {t.next ? (
                      <>
                        <span className="block font-medium text-navy-900">{t.next.display}</span>
                        <span className={`block text-xs ${t.next.daysAway <= 2 ? 'font-medium text-rose-700' : 'text-slate-500'}`}>{dueLabel(t.next.daysAway)}</span>
                      </>
                    ) : (
                      <span className="text-slate-400">None due</span>
                    )}
                  </td>
                  <td className="px-5 py-3">{t.held ? <Badge tone="pending">{t.held} on hold</Badge> : <span className="text-slate-300">–</span>}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

/** Items the agent's checks held back. A client does not see them until someone approves. */
function ReviewQueue({ onView }: { onView: (client: BriefClient, asOf: string, itemId: string) => void }) {
  const { heldItems, approve, revoke } = useBrief()
  const { toast } = useApp()

  if (heldItems.length === 0) return <Card><Empty>Nothing is waiting for review.</Empty></Card>

  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-600">
        These items failed an automatic check, so no client sees them yet. Check each one against the filing, then approve it or keep it on hold. The queue covers every client.
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
                    <Button variant="primary" onClick={() => onView(client, asOf, item.id)}>View in the client's brief</Button>
                    <Button onClick={() => revoke(key)}><RotateCcw size={14} /> Put back on hold</Button>
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

/** Relationship manager workspace: see which clients need to act first, check the brief and holdings they see, and clear held items. */
export function ClientBriefs() {
  const { client, setClientId, asOf, setAsOf, setCadence, pendingCount, focus } = useBrief()
  const [params, setParams] = useSearchParams()
  const tab: TabId = params.get('tab') === 'review' ? 'review' : params.get('tab') === 'holdings' ? 'holdings' : 'brief'
  const setTab = (t: TabId) => setParams(t === 'brief' ? {} : { tab: t }, { replace: true })

  // A client's brief opens at the frequency that client receives it.
  const select = (c: BriefClient) => {
    setClientId(c.id)
    setCadence(c.cadence)
  }

  const viewInBrief = (c: BriefClient, day: string, itemId: string) => {
    select(c)
    setAsOf(day)
    focus(itemId)
    setTab('brief')
  }

  return (
    <>
      <PageHeader
        eyebrow="Relationship manager"
        title="Client Briefs"
        subtitle={`See what each client receives and who needs to act first. ${
          pendingCount > 0
            ? `${pendingCount} ${pendingCount > 1 ? 'items need' : 'item needs'} your approval before ${pendingCount > 1 ? 'they reach' : 'it reaches'} a client.`
            : 'Nothing is waiting for your approval.'
        }`}
        actions={<Select label="Brief date" value={asOf} onChange={setAsOf} options={DATE_OPTIONS} />}
      />

      <ClientTable selected={client.id} onSelect={select} />

      <div className="mb-2 flex flex-wrap items-baseline gap-x-2">
        <h2 className="text-lg font-semibold text-navy-900">{client.name}</h2>
        <span className="text-sm text-slate-500">{client.type}</span>
      </div>

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
        {tab === 'holdings' && <Holdings embedded onOpenBrief={() => setTab('brief')} />}
        {tab === 'review' && <ReviewQueue onView={viewInBrief} />}
      </div>
    </>
  )
}
