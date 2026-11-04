import raw from './briefs.json'

export type Tier = 'action' | 'changed' | 'new' | 'completed' | 'upcoming'
export type Cadence = 'weekly' | 'daily'
export type BriefAction = 'rights_issue' | 'merger' | 'tender_offer'

export interface ImpactLine {
  label: string
  value: string
  formula: string
}

export interface Evidence {
  key: string
  label: string
  value: string
  stated: string | null
  quote: string | null
  location: string
  form: string
  filed: string
  url: string
  verified: boolean | null
}

export interface BriefItem {
  id: string
  eventId: string
  action: BriefAction
  actionLabel: string
  tier: Tier
  tierLabel: string
  title: string
  issuer: string
  counterparty: string | null
  ticker: string
  role: string
  status: string
  summary: string
  summarySource: 'llm' | 'template'
  position: { name: string; shares: number; onLoan: number; watchOnly: boolean }
  impact: { lines: ImpactLine[]; caveats: string[]; reason: string | null }
  terms: { label: string; value: string }[]
  options: string | null
  changes: { label: string; from: string; to: string; text: string; form: string; filed: string; accession: string }[]
  evidence: Evidence[]
  sources: { form: string; filed: string; url: string; accession: string }[]
  latestFiled: string
  stageNote?: string
  review: { needed: boolean; reasons: { code: string; detail: string }[] }
  deadline?: { label: string; kind: string; date: string; display: string; daysAway: number; quote: string | null; form: string; url: string }
  cutoff?: { date: string; display: string; daysAway: number; passed: boolean }
}

export interface Brief {
  clientId: string
  asOf: string
  cadence: Cadence
  lookbackDays: number
  counts: Record<Tier, number>
  items: BriefItem[]
  heldForReview: number
  trace: { step: string; detail: string }[]
}

export interface BriefClient {
  id: string
  name: string
  type: string
  cadence: Cadence
  positions: { ticker: string; name: string; shares: number; onLoan?: number }[]
  watchlist: { ticker: string; name: string }[]
}

interface BriefData {
  generatedOn: string
  assumptions: { cutoffBusinessDays: number; actionWindowDays: number }
  asOfDates: string[]
  cadences: Cadence[]
  actions: { id: BriefAction; label: string }[]
  clients: BriefClient[]
  briefs: Record<string, Brief>
}

export const briefData = raw as unknown as BriefData

export const TIER_ORDER: Tier[] = ['action', 'changed', 'new', 'completed', 'upcoming']
export const TIER_TITLE: Record<Tier, string> = {
  action: 'Action needed',
  changed: 'Terms changed',
  new: 'New events',
  completed: 'Recently closed',
  upcoming: 'On the horizon',
}

export const briefKey = (clientId: string, asOf: string, cadence: Cadence) => `${clientId}|${asOf}|${cadence}`

/** Approval is per client, date and item, so a daily and a weekly brief for the same date stay in step. */
export const reviewKey = (clientId: string, asOf: string, itemId: string) => `${clientId}|${asOf}|${itemId}`

export const getBrief = (clientId: string, asOf: string, cadence: Cadence): Brief | undefined =>
  briefData.briefs[briefKey(clientId, asOf, cadence)]

export function periodLabel(asOf: string, lookbackDays: number): string {
  const end = new Date(asOf + 'T00:00:00')
  const fmt = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  if (lookbackDays <= 1) return `${fmt(end)}, ${end.getFullYear()}`
  const start = new Date(end)
  start.setDate(start.getDate() - (lookbackDays - 1))
  return `${fmt(start)} – ${fmt(end)}, ${end.getFullYear()}`
}

export function dueLabel(days: number): string {
  if (days < 0) return `${-days} day${days === -1 ? '' : 's'} ago`
  if (days === 0) return 'today'
  if (days === 1) return 'tomorrow'
  return `in ${days} days`
}

export const REASON_LABEL: Record<string, string> = {
  offering_limit: 'Exceeds offering limit',
  date_conflict: 'Dates conflict',
  deadline_moved_earlier: 'Deadline moved earlier',
  impact_missing: 'Client numbers missing',
  no_evidence: 'No supporting quote',
  quote_not_found: 'Quote not found in filing',
}
