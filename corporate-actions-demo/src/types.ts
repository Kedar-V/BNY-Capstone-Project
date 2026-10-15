export type ActionType = 'tender_offer' | 'merger'

export interface Quote {
  quote: string
  location: string
}

export interface LinkSignal {
  id: string
  label: string
  ok: boolean
  strong?: boolean
  detail: string
  quotes?: { source: string; quote: string }[]
}

export interface LinkEvidence {
  to: string
  toForm: string
  toDate: string
  rule: string | null
  confidence: 'High' | 'Medium' | null
  signals: LinkSignal[]
}

export interface Filing {
  id: string
  accession: string
  action: ActionType
  form: string
  filedDate: string
  subject: string
  counterparty: string | null
  registrant: string | null
  cik: string
  indexUrl: string
  docs: number
  sizeMb: number
  eventKey: string
  fields: Record<string, string>
  passages: Record<string, Quote[]>
  incoming: boolean
  fileNo: string | null
  agreement: { date: string; quote: string } | null
  cites: string[]
  link: LinkEvidence | null
}

export interface FieldChange {
  key: string
  label: string
  previous?: string
  current: string
  kind: 'added' | 'list' | 'changed' | 'reworded'
  addedItems?: string[]
  removedItems?: string[]
}

export interface Version {
  number: number
  filing: Filing
  fields: Record<string, string>
  changes: FieldChange[]
}

export interface CorporateEvent {
  id: string
  action: ActionType
  title: string
  subject: string
  counterparty: string | null
  versions: Version[]
  current: Version
  fields: Record<string, string>
  status: string
  firstDate: string
  lastDate: string
  headline: string
}

export interface FieldDef {
  key: string
  label: string
  section: string
}

export interface Notification {
  id: string
  eventId: string
  kind: 'New Tender Offer' | 'New Merger' | 'Amendment'
  title: string
  body: string
  date: string
  filing: Filing
}
