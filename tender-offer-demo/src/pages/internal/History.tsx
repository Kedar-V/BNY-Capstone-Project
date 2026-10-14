import { CheckCircle2, Loader2, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { VersionTimeline } from '../../components/shared'
import { Badge, Button, Card, PageHeader } from '../../components/ui'
import { useApp, useOffer } from '../../state/AppState'

const STEPS = [
  'Retrieving SC TO-T/A from SEC EDGAR…',
  'Linking filing to the Acme / BlueRiver event…',
  'Comparing terms against the current record…',
  'Creating version V3 and client notifications…',
]
const AMENDMENT_OFFER = 'to-acme-blueriver'

export function History() {
  const { offerId } = useParams()
  const view = useOffer(offerId)
  const { amendmentProcessed, processAmendment } = useApp()
  const [step, setStep] = useState<number | null>(null)

  if (!view) return <p className="text-sm">Tender offer not found.</p>
  const canProcess = view.offer.id === AMENDMENT_OFFER

  const run = () => {
    setStep(0)
    let i = 0
    const tick = window.setInterval(() => {
      i++
      if (i >= STEPS.length) {
        window.clearInterval(tick)
        setStep(null)
        processAmendment()
      } else setStep(i)
    }, 650)
  }

  const processing = step !== null

  return (
    <>
      <PageHeader
        eyebrow={
          <Link to={`/internal/tender-offers/${view.offer.id}`} className="hover:underline">
            {view.offer.title}
          </Link>
        }
        title="Version History"
        subtitle="One tender offer can span several SEC filings. Each filing updates the event while preserving the full history."
        actions={
          canProcess &&
          (amendmentProcessed ? (
            <Badge tone="completed">
              <CheckCircle2 size={12} /> Amendment processed
            </Badge>
          ) : (
            <Button variant="primary" onClick={run} disabled={processing}>
              {processing ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              Process New Amendment
            </Button>
          ))
        }
      />

      {canProcess && !amendmentProcessed && !processing && (
        <div className="mb-4 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          A new amendment (SC TO-T/A) for this event has arrived and has not yet been processed.
        </div>
      )}

      {processing && (
        <Card className="mb-4 p-4">
          <ul className="space-y-2 text-sm">
            {STEPS.map((s, i) => (
              <li key={s} className={`flex items-center gap-2 ${i <= step ? 'text-slate-900' : 'text-slate-300'}`}>
                {i < step ? <CheckCircle2 size={15} className="text-emerald-600" /> : i === step ? <Loader2 size={15} className="animate-spin text-navy-600" /> : <span className="h-[15px] w-[15px]" />}
                {s}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {canProcess && amendmentProcessed && (
        <div className="fade-up mb-4 flex items-center gap-2 rounded-md border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
          <CheckCircle2 size={16} /> Amendment detected — two material changes recorded and client notifications created.{' '}
          <Link to="/client/notifications" className="font-medium underline">
            View in Client Portal
          </Link>
        </div>
      )}

      <VersionTimeline key={view.versions.length} view={view} flashLatest={canProcess && amendmentProcessed} />
    </>
  )
}
