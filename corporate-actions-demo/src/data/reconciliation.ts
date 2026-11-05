import raw from './reconciliation.json'
import { fmtDate } from './store'

export type TicketField = 'price' | 'expiry' | 'cusip'
export type TicketStatus = 'open' | 'confirmed' | 'dismissed'

export interface Ticket {
  id: string
  vendor: 'A' | 'B'
  vendorId: string
  issuer: string
  field: TicketField
  kind: 'value_mismatch' | 'missing_in_vendor'
  severity: 'high' | 'medium'
  filingValue: string | null
  vendorValue: string | null
  accession: string
  form: string
  filed: string
}

interface ReconData {
  vendors: { id: 'A' | 'B'; name: string; format: string; records: number }[]
  totals: { vendorRecords: number; matched: number }
  tickets: Ticket[]
}

export const reconData = raw as unknown as ReconData

export const FIELD_LABEL: Record<TicketField, string> = { price: 'Offer price', expiry: 'Expiration date', cusip: 'CUSIP' }
/** Key of the matching field in the extracted filing record. */
export const FILING_FIELD: Record<TicketField, string> = { price: 'offer_price', expiry: 'expiration_date', cusip: 'cusip' }

export function formatValue(field: TicketField, v: string | null): string {
  if (v === null || v === '') return 'Not provided'
  if (field === 'expiry') return fmtDate(v)
  if (field === 'price') return `$${Number(v).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
  return v
}

/** Plain-language size of the gap between the two values. */
export function describeGap(t: Ticket): string {
  if (t.kind === 'missing_in_vendor') return `The vendor has no ${FIELD_LABEL[t.field].toLowerCase()}; the filing states one.`
  if (t.field === 'expiry' && t.filingValue && t.vendorValue) {
    const d = Math.round((new Date(t.vendorValue).getTime() - new Date(t.filingValue).getTime()) / 86400000)
    return `Vendor date is ${Math.abs(d)} day${Math.abs(d) === 1 ? '' : 's'} ${d < 0 ? 'earlier' : 'later'} than the filing.`
  }
  if (t.field === 'price' && t.filingValue && t.vendorValue) {
    const f = Number(t.filingValue)
    const v = Number(t.vendorValue)
    const pct = ((v - f) / f) * 100
    return `Vendor price is ${Math.abs(pct).toFixed(1)}% ${pct < 0 ? 'lower' : 'higher'} than the filing.`
  }
  if (t.field === 'cusip') return 'The identifiers differ. The vendor CUSIP may have a transposed or incorrect character.'
  return 'Values differ.'
}
