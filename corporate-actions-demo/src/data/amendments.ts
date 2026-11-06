import raw from './amendments.json'

export type AmendTier = 'action' | 'needs_review' | 'informational' | 'log_only'
export type AmendAction = 'tender_offer' | 'merger' | 'rights_issue'
export type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'reviewed'

export interface AmendChange {
  field: string
  kind: 'value' | 'text' | 'status'
  previous: string | null
  current: string | null
  tier: AmendTier
  reason: string
  quote: string | null
  location: string | null
  decidedBy: 'rules' | 'llm'
}

export interface Amendment {
  id: string
  eventId: string
  action: AmendAction
  title: string
  accession: string
  form: string
  filed: string
  url: string
  version: number
  tier: AmendTier
  why: string
  review: { code: string; detail: string }[]
  changes: AmendChange[]
  restated: string[]
  holders: { client: string; ticker: string; shares: number; watchOnly: boolean }[]
  notice: { subject: string; lines: string[]; source: string; recipients: string[]; watchers: string[] } | null
  trace: { step: string; detail: string }[]
}

interface AmendData {
  summary: {
    amendments: number
    events: number
    by_tier: Record<AmendTier, number>
    held_for_review: number
    review_reasons: Record<string, number>
    textChanges: number
    llmJudged: number
    llmMaterial: number
    notices: number
    reachingClients: number
  }
  items: Amendment[]
}

export const amendData = raw as unknown as AmendData

export const TIER_LABEL: Record<AmendTier, string> = {
  action: 'Action needed',
  needs_review: 'Needs review',
  informational: 'Informational',
  log_only: 'Log only',
}
export const TIER_HINT: Record<AmendTier, string> = {
  action: 'A deadline, price, ratio or condition changed, or the event ended. Holders may need to act.',
  needs_review: 'Wording changed and no one has judged it yet.',
  informational: 'Worth telling holders; nothing for them to do.',
  log_only: 'Nothing a holder acts on. Kept for the audit trail; nothing is sent.',
}
export const ACTION_LABEL: Record<AmendAction, string> = { tender_offer: 'Tender offer', merger: 'Merger', rights_issue: 'Rights offering' }

export const FIELD_LABEL: Record<string, string> = {
  expiration_date: 'Expiration', withdrawal_deadline: 'Withdrawal deadline', election_deadline: 'Election deadline',
  record_date: 'Record date', vote_date: 'Shareholder vote', offer_price: 'Offer price', price: 'Subscription price',
  ratio: 'Subscription ratio', cash_per_share: 'Cash consideration', exchange_ratio: 'Stock consideration',
  settlement_date: 'Settlement date', effective_date: 'Closing / issuance date', oversubscription: 'Over-subscription',
  transferable: 'Rights transferable', security_class: 'Security', event_status: 'Status',
  minimum_tender_condition: 'Minimum tender condition', proration_terms: 'Proration terms', tendering_conditions: 'How to tender',
  conditions_restrictions: 'Offer conditions', available_options: 'Holder options', default_option: 'If no election is made',
  consideration_type: 'Consideration type', closing_conditions: 'Closing conditions',
}
export const fieldLabel = (f: string) => FIELD_LABEL[f] ?? f

export const CHECK_LABEL: Record<string, string> = {
  price_change_window: 'Price changed with fewer than 10 business days left',
  deadline_moved_earlier: 'Deadline moved earlier',
  deadline_in_past: 'New deadline is before the filing date',
  no_evidence: 'No supporting quote for a change',
  quote_not_found: 'Quote not found in the filing text',
  text_not_assessed: 'Changed wording not yet judged',
}

export const REJECT_REASONS = [
  'Not a real change: extraction difference between filings',
  'Belongs to a different event (e.g. an earlier offer)',
  'Already notified from another filing',
  'Other',
]

/** The change the table row describes: the first one at the filing's tier. */
export const headlineChange = (a: Amendment): AmendChange | undefined => a.changes.find((c) => c.tier === a.tier) ?? a.changes[0]

/** One-line summary of what changed, for the table. */
export function changeSummary(a: Amendment): string {
  const shown = a.changes.filter((c) => c.tier === a.tier)
  const c = headlineChange(a)
  if (!c) return a.why
  const label = fieldLabel(c.field)
  let s: string
  if (c.kind === 'status') s = `${label}: now ${c.current}`
  else if (c.kind === 'text') s = `${label} wording changed`
  else s = c.previous ? `${label}: ${c.previous} → ${c.current}` : `${label}: ${c.current}`
  return shown.length > 1 ? `${s} (+${shown.length - 1} more)` : s
}

/** The notice as plain text, which operations can edit before approving. */
export function noticeText(a: Amendment): string {
  if (!a.notice) return ''
  return [a.notice.subject, '', ...a.notice.lines.map((l) => `• ${l}`), '', `Source: ${a.notice.source}`].join('\n')
}

/** What approving would update in the event record: dated and numeric terms that changed. */
export function recordUpdates(a: Amendment): string[] {
  return a.changes
    .filter((c) => c.kind !== 'text' && (c.tier === 'action' || c.tier === 'informational'))
    .map((c) => `${fieldLabel(c.field)} → ${c.current}`)
}
