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
  sector: string
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

/** Sectors in filter order (hand-labelled per event in scripts/sectors.json). */
export const SECTORS = ['Funds & BDCs', 'Financials', 'Health Care', 'Technology', 'Consumer', 'Energy', 'Real Estate', 'Materials', 'Industrials', 'Communication Services']

/** Dates a holder has to act by. Settlement and closing dates are dates too, but nobody acts on them. */
export const DEADLINE_FIELDS = ['expiration_date', 'withdrawal_deadline', 'election_deadline', 'vote_date', 'record_date']
const DATE_FIELDS = [...DEADLINE_FIELDS, 'settlement_date', 'effective_date']

const DAY = 86_400_000
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
/** Parses "Feb 8, 2026" or "2026-02-08" to a UTC day number. */
export function dayNum(s: string | null | undefined): number | null {
  if (!s) return null
  let m = s.match(/^(\d{4})-(\d{2})-(\d{2})$/)
  if (m) return Math.round(Date.UTC(+m[1], +m[2] - 1, +m[3]) / DAY)
  m = s.match(/^([A-Z][a-z]{2})[a-z]*\.? (\d{1,2}), (\d{4})$/)
  const mon = m ? MONTHS.indexOf(m[1]) : -1
  return mon < 0 ? null : Math.round(Date.UTC(+m![3], mon, +m![2]) / DAY)
}

export type ShiftKind = 'earlier' | 'later' | 'set' | 'stale'
export interface DateShift { change: AmendChange; kind: ShiftKind; days: number | null }

/** How a date field moved: earlier, later, or set for the first time. */
export function dateShift(c: AmendChange): DateShift | null {
  if (c.kind !== 'value' || !DATE_FIELDS.includes(c.field)) return null
  const now = dayNum(c.current)
  if (now === null) return null
  const before = dayNum(c.previous)
  if (before === null) return { change: c, kind: 'set', days: null }
  if (now === before) return null
  return { change: c, kind: now < before ? 'earlier' : 'later', days: now - before }
}

/**
 * The deadline change that matters most in a filing: moved earlier, extended, newly set, then stale. A new deadline
 * before the filing's own date is "stale": usually a previous offer round's date picked up by extraction, so it is
 * kept apart from real moves rather than raised as an urgent alert.
 */
export function deadlineShift(a: Amendment): DateShift | null {
  const filed = dayNum(a.filed)
  const shifts = a.changes
    .filter((c) => DEADLINE_FIELDS.includes(c.field) && c.tier !== 'log_only')
    .map(dateShift)
    .filter((x): x is DateShift => !!x)
    .map((x) => (filed !== null && dayNum(x.change.current)! < filed ? { ...x, kind: 'stale' as const } : x))
  const rank: Record<ShiftKind, number> = { earlier: 0, later: 1, set: 2, stale: 3 }
  return shifts.sort((x, y) => rank[x.kind] - rank[y.kind])[0] ?? null
}

/** Days between the filing and a date in it (negative: the date was already past). */
export const daysFromFiling = (a: Amendment, date: string | null) => {
  const d = dayNum(date), f = dayNum(a.filed)
  return d === null || f === null ? null : d - f
}

export const fmtDays = (n: number) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n)}d`

/** "+4.0%" for prices, "+0.05" for ratios; null when either side isn't a number. */
export function numericDelta(c: AmendChange): string | null {
  if (c.kind !== 'value' || DATE_FIELDS.includes(c.field)) return null
  const num = (s: string | null) => {
    const m = s?.replace(/,/g, '').match(/-?\d+(\.\d+)?/)
    return m ? parseFloat(m[0]) : null
  }
  const a = num(c.previous), b = num(c.current)
  if (a === null || b === null || a === b) return null
  if (c.previous?.includes('$') || c.current?.includes('$')) return a ? `${b > a ? '+' : '−'}${Math.abs(((b - a) / a) * 100).toFixed(1)}%` : null
  return `${b > a ? '+' : '−'}${+Math.abs(b - a).toFixed(4)}`
}

export type DiffPart = { t: 'same' | 'add' | 'del'; text: string }
/** Word-level diff of two passages (longest common subsequence), with runs merged. */
export function wordDiff(before: string, after: string): DiffPart[] {
  const a = before.split(/\s+/).filter(Boolean), b = after.split(/\s+/).filter(Boolean)
  const norm = (w: string) => w.toLowerCase().replace(/[^a-z0-9$%.]/g, '')
  const L = Array.from({ length: a.length + 1 }, () => new Uint16Array(b.length + 1))
  for (let i = a.length - 1; i >= 0; i--)
    for (let j = b.length - 1; j >= 0; j--) L[i][j] = norm(a[i]) === norm(b[j]) ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1])
  const out: DiffPart[] = []
  const push = (t: DiffPart['t'], w: string) => (out.length && out[out.length - 1].t === t ? (out[out.length - 1].text += ' ' + w) : out.push({ t, text: w }))
  let i = 0, j = 0
  while (i < a.length && j < b.length) {
    if (norm(a[i]) === norm(b[j])) { push('same', b[j]); i++; j++ }
    else if (L[i + 1][j] >= L[i][j + 1]) push('del', a[i++])
    else push('add', b[j++])
  }
  while (i < a.length) push('del', a[i++])
  while (j < b.length) push('add', b[j++])
  return out
}
