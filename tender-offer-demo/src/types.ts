export type FieldKey =
  | 'offeror'
  | 'target'
  | 'security'
  | 'cusip'
  | 'offerPrice'
  | 'expiration'
  | 'withdrawal'
  | 'minCondition'
  | 'recommendation'

export const FIELD_LABELS: Record<FieldKey, string> = {
  offeror: 'Offeror',
  target: 'Target',
  security: 'Security',
  cusip: 'CUSIP',
  offerPrice: 'Offer Price',
  expiration: 'Expiration',
  withdrawal: 'Withdrawal Rights',
  minCondition: 'Minimum Tender Condition',
  recommendation: 'Board Recommendation',
}

export type FieldValues = Record<FieldKey, string>

export interface Company {
  id: string
  name: string
  ticker?: string
  sector: string
  /** Appears in the client watchlist directory */
  watchable: boolean
}

export interface Segment {
  text: string
  /** Business fields this passage is the source of */
  fields?: FieldKey[]
}

export interface Paragraph {
  heading?: string
  segments: Segment[]
}

export type FilingKind = 'Announcement' | 'Amendment' | 'Target Response'

export interface Filing {
  id: string
  offerId: string
  companyId: string
  title: string
  form: string
  kind: FilingKind
  filedDate: string
  filedTime: string
  accession: string
  baseStatus: 'New' | 'Processed' | 'Needs Review'
  /** Fields surfaced from this filing, display-formatted */
  extracted: Partial<Record<FieldKey, string>>
  paragraphs: Paragraph[]
  /** Only appears after "Fetch Today's Filings" */
  arrivesOnFetch?: boolean
}

export interface FieldChange {
  field: FieldKey
  previous: string
  current: string
}

export interface TenderOfferVersion {
  id: string
  number: number
  date: string
  filingId: string
  form: string
  summary: string
  /** Full snapshot of the event after this version */
  fields: FieldValues
  changes: FieldChange[]
  unchanged: string[]
  /** Revealed by "Process New Amendment" */
  hiddenUntilProcessed?: boolean
}

export type OfferStatus = 'Pending' | 'Withdrawn' | 'Completed'

export interface TenderOffer {
  id: string
  title: string
  offerorName: string
  targetId: string
  type: string
  status: OfferStatus
  announced: string
  versions: TenderOfferVersion[]
}

export type NotificationType =
  | 'New Tender Offer'
  | 'Amendment'
  | 'Deadline Change'
  | 'Watchlist Update'
  | 'Suggested Action'

export interface ClientNotification {
  id: string
  type: NotificationType
  offerId: string
  companyId: string
  title: string
  body: string
  bullets?: string[]
  date: string
  read: boolean
  cta: string
}

export interface AlertPrefs {
  announcements: boolean
  amendments: boolean
  deadlines: boolean
  actions: boolean
}

export interface Subscription {
  companyId: string
  subscribed: boolean
  prefs: AlertPrefs
}

export type ActionStatus = 'open' | 'reviewed' | 'dismissed'

export interface SuggestedAction {
  id: string
  companyId: string
  offerId: string
  title: string
  body: string
  /** Replacement copy once the BlueRiver amendment has been processed */
  amendedTitle?: string
  amendedBody?: string
  tone: 'attention' | 'deadline' | 'clear'
  status: ActionStatus
}
