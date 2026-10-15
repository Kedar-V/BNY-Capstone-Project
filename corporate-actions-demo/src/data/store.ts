import raw from './filings.json'
import type { ActionType, CorporateEvent, FieldChange, FieldDef, Filing, Notification, Version } from '../types'

export const allFilings = raw as unknown as Filing[]

export const ACTION_LABEL: Record<ActionType, string> = { tender_offer: 'Tender Offer', merger: 'Merger' }

const def = (section: string, pairs: [string, string][]): FieldDef[] => pairs.map(([key, label]) => ({ key, label, section }))

export const FIELD_DEFS: Record<ActionType, FieldDef[]> = {
  tender_offer: [
    ...def('Parties', [
      ['subject_company', 'Subject Company'],
      ['bidder', 'Bidder'],
      ['parent', 'Parent'],
      ['acquisition_subsidiary', 'Acquisition Subsidiary'],
      ['dealer_manager', 'Dealer Manager'],
      ['depositary', 'Depositary'],
      ['information_agent', 'Information Agent'],
    ]),
    ...def('Security', [
      ['security_description', 'Security'],
      ['ticker', 'Ticker'],
      ['cusip', 'CUSIP'],
      ['isin', 'ISIN'],
    ]),
    ...def('Offer Terms', [
      ['offer_price', 'Offer Price'],
      ['offer_price_type', 'Price Type'],
      ['offer_price_basis', 'Price Basis'],
      ['currency', 'Currency'],
      ['offer_price_qualifications', 'Price Qualifications'],
      ['mandatory_voluntary_indicator', 'Mandatory / Voluntary'],
      ['minimum_tender_condition', 'Minimum Tender Condition'],
      ['proration_terms', 'Proration Terms'],
      ['tendering_conditions', 'Tendering Conditions'],
      ['available_options', 'Available Options'],
      ['default_option', 'Default Option'],
      ['financial_terms', 'Financial Terms'],
      ['conditions_restrictions', 'Conditions & Restrictions'],
    ]),
    ...def('Key Dates', [
      ['expiration_date', 'Expiration'],
      ['withdrawal_deadline', 'Withdrawal Deadline'],
      ['settlement_date', 'Settlement'],
      ['effective_date', 'Effective Date'],
    ]),
    ...def('Status', [
      ['event_status', 'Event Status'],
      ['event_status_details', 'Status Details'],
    ]),
  ],
  merger: [
    ...def('Parties', [
      ['acquirer', 'Acquirer'],
      ['target', 'Target'],
    ]),
    ...def('Security', [['security_description', 'Security']]),
    ...def('Consideration', [
      ['consideration_type', 'Consideration Type'],
      ['cash_consideration', 'Cash Consideration'],
      ['stock_exchange_ratio', 'Exchange Ratio'],
      ['available_options', 'Available Options'],
      ['default_option', 'Default Option'],
      ['election_deadline', 'Election Deadline'],
    ]),
    ...def('Conditions & Dates', [
      ['closing_conditions', 'Closing Conditions'],
      ['shareholder_vote_date', 'Shareholder Vote'],
      ['effective_date', 'Effective Date'],
    ]),
    ...def('Status', [['event_status', 'Event Status']]),
  ],
}

const labelOf = (action: ActionType, key: string) => FIELD_DEFS[action].find((d) => d.key === key)?.label ?? key

export function shortStatus(s: string | undefined): string {
  if (!s) return 'Unknown'
  const t = s.split(/[;:.,(]/)[0].trim()
  return t.length > 32 ? t.slice(0, 30) + '…' : t
}

const slug = (key: string) => key.replace(/[^a-z0-9]+/gi, '-').toLowerCase()

function headline(action: ActionType, f: Record<string, string>): string {
  if (action === 'tender_offer') {
    const p = f.offer_price
    if (!p) return 'Terms not stated in this filing'
    return p.length > 70 ? p.slice(0, 68) + '…' : p
  }
  const c = f.consideration_type
  const cash = f.cash_consideration
  return [c, cash].filter(Boolean).join(' · ') || 'Terms not stated in this filing'
}

/** Groups visible filings into corporate events with a version per filing and field-level changes. */
export function buildEvents(filings: Filing[]): CorporateEvent[] {
  const groups = new Map<string, Filing[]>()
  for (const f of filings) groups.set(f.eventKey, [...(groups.get(f.eventKey) ?? []), f])

  return [...groups.entries()].map(([key, group]) => {
    const sorted = [...group].sort((a, b) => a.filedDate.localeCompare(b.filedDate) || a.id.localeCompare(b.id))
    const action = sorted[0].action
    let acc: Record<string, string> = {}
    const versions: Version[] = sorted.map((filing, i) => {
      const changes: FieldChange[] = []
      if (i > 0) {
        for (const [k, v] of Object.entries(filing.fields)) {
          if (acc[k] !== v) changes.push({ key: k, label: labelOf(action, k), previous: acc[k], current: v })
        }
      }
      acc = { ...acc, ...filing.fields }
      return { number: i + 1, filing, fields: acc, changes }
    })
    const current = versions[versions.length - 1]
    const subject = sorted[0].subject
    const counterparty = current.fields.bidder ?? current.fields.acquirer ?? sorted[0].counterparty
    const title =
      counterparty && counterparty.toLowerCase() !== subject.toLowerCase() ? `${shorten(counterparty)} / ${subject}` : subject
    return {
      id: slug(key),
      action,
      title,
      subject,
      counterparty: counterparty ?? null,
      versions,
      current,
      fields: current.fields,
      status: shortStatus(current.fields.event_status),
      firstDate: versions[0].filing.filedDate,
      lastDate: current.filing.filedDate,
      headline: headline(action, current.fields),
    }
  })
}

function shorten(s: string, n = 48) {
  const first = s.split(/[,;(]/)[0].trim()
  return first.length > n ? first.slice(0, n - 1) + '…' : first
}

export function buildNotifications(events: CorporateEvent[], subscribed: Set<string>): Notification[] {
  const out: Notification[] = []
  for (const e of events) {
    if (!subscribed.has(e.id)) continue
    for (const v of e.versions) {
      const first = v.number === 1
      const kind = first ? (e.action === 'tender_offer' ? 'New Tender Offer' : 'New Merger') : 'Amendment'
      out.push({
        id: `${e.id}:${v.filing.id}`,
        eventId: e.id,
        kind,
        title: first ? `${e.title}` : `${e.title} — ${v.filing.form} filed`,
        body: first
          ? `${v.filing.form} filed. ${headline(e.action, v.fields)}`
          : v.changes.length
            ? `${v.changes.length} term${v.changes.length > 1 ? 's' : ''} updated: ${v.changes.slice(0, 3).map((c) => c.label).join(', ')}${v.changes.length > 3 ? '…' : ''}`
            : 'No term changes detected.',
        date: v.filing.filedDate,
        filing: v.filing,
      })
    }
  }
  return out.sort((a, b) => b.date.localeCompare(a.date) || b.id.localeCompare(a.id))
}

export function fmtDate(iso: string): string {
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
}

export function toneFor(status: string): 'new' | 'amended' | 'pending' | 'completed' | 'review' | 'neutral' {
  const s = status.toLowerCase()
  if (/complet|final|closed|consummat/.test(s)) return 'completed'
  if (/terminat|withdraw|cancel/.test(s)) return 'review'
  if (/amend/.test(s)) return 'amended'
  if (/commenc|announc|launch|open/.test(s)) return 'new'
  if (/pending/.test(s)) return 'pending'
  return 'neutral'
}

export const isActive = (e: CorporateEvent) => !['completed', 'review'].includes(toneFor(e.status)) && !/final/i.test(e.status)
