import type {
  ClientNotification,
  Company,
  FieldKey,
  FieldValues,
  Filing,
  FilingKind,
  Paragraph,
  Subscription,
  SuggestedAction,
  TenderOffer,
} from '../types'

// All names, identifiers and filing text below are synthetic and for demonstration only.

export const companies: Company[] = [
  { id: 'blueriver', name: 'BlueRiver Inc.', ticker: 'BLUR', sector: 'Industrial Technology', watchable: true },
  { id: 'northstar', name: 'Northstar Holdings', ticker: 'NSTR', sector: 'Financial Services', watchable: true },
  { id: 'greenstone', name: 'GreenStone Biotech', ticker: 'GSBT', sector: 'Biotechnology', watchable: true },
  { id: 'summit', name: 'Summit Retail Group', ticker: 'SMRT', sector: 'Consumer Retail', watchable: true },
  { id: 'cedarpoint', name: 'Cedar Point Logistics', ticker: 'CPLG', sector: 'Transportation', watchable: true },
  { id: 'tidewater', name: 'Tidewater Energy Partners', ticker: 'TWEP', sector: 'Energy', watchable: true },
  { id: 'acme', name: 'Acme Capital Corp.', sector: 'Private Equity', watchable: false },
  { id: 'horizon', name: 'Horizon Holdings', sector: 'Holding Company', watchable: false },
  { id: 'pinecrest', name: 'Pinecrest Partners', sector: 'Private Equity', watchable: false },
]

export const companyById = (id: string) => companies.find((c) => c.id === id)!

// ---------------------------------------------------------------- Helpers

const seg = (text: string, ...fields: FieldKey[]) => ({ text, fields: fields.length ? fields : undefined })

const blank = (over: Partial<FieldValues>): FieldValues => ({
  offeror: '',
  target: '',
  security: '',
  cusip: '',
  offerPrice: '',
  expiration: '',
  withdrawal: 'Withdrawable until expiration',
  minCondition: 'More than 50% of outstanding shares',
  recommendation: 'Not yet issued',
  ...over,
})

const SENTENCES: Record<FieldKey, (f: FieldValues) => string> = {
  offeror: (f) => `${f.offeror} (the “Purchaser”) is making an offer to purchase outstanding shares of ${f.target}.`,
  target: (f) => `${f.target} (the “Company”) is the subject company of the Offer.`,
  security: (f) => `The securities subject to the Offer are ${f.security} (CUSIP ${f.cusip}) (the “Shares”).`,
  cusip: (f) => `The Shares are identified by CUSIP ${f.cusip}.`,
  offerPrice: (f) => `The Purchaser is offering a purchase price of ${f.offerPrice.replace('/share', ' per Share')}, net to the seller in cash.`,
  expiration: (f) => `The Offer is scheduled to expire at 11:59 p.m., Eastern Time, on ${f.expiration}, unless extended.`,
  withdrawal: () => 'Shares tendered pursuant to the Offer may be withdrawn at any time prior to the Expiration Date.',
  minCondition: () => 'The Offer is conditioned upon a majority of the outstanding Shares being validly tendered and not withdrawn.',
  recommendation: (f) => `The Board of Directors states its position on the Offer as follows: ${f.recommendation}.`,
}

interface AutoFilingArgs {
  id: string
  offerId: string
  companyId: string
  title: string
  form: string
  kind: FilingKind
  filedDate: string
  filedTime: string
  accession: string
  baseStatus?: Filing['baseStatus']
  arrivesOnFetch?: boolean
  fields: FieldValues
  surface: FieldKey[]
}

function autoFiling(a: AutoFilingArgs): Filing {
  const { fields, surface, ...rest } = a
  const paragraphs: Paragraph[] = [
    {
      heading: 'Item 1. Summary Term Sheet',
      segments: surface.map((k) => seg(SENTENCES[k](fields) + ' ', k)),
    },
  ]
  return {
    ...rest,
    baseStatus: a.baseStatus ?? 'Processed',
    extracted: Object.fromEntries(surface.map((k) => [k, fields[k]])),
    paragraphs,
  }
}

// ---------------------------------------------------------------- Acme / BlueRiver (main story)

const BR_SECURITY = 'BlueRiver Inc. Common Stock'
const BR_CUSIP = '09500X101'

const brV1: FieldValues = blank({
  offeror: 'Acme Capital Corp.',
  target: 'BlueRiver Inc.',
  security: BR_SECURITY,
  cusip: BR_CUSIP,
  offerPrice: '$42.50/share',
  expiration: 'Nov. 12, 2026',
  withdrawal: 'Withdrawable until expiration',
})
const brV2: FieldValues = { ...brV1, recommendation: 'Recommend tendering' }
const brV3: FieldValues = { ...brV2, offerPrice: '$45.00/share', expiration: 'Nov. 19, 2026' }

const filingV1: Filing = {
  id: 'f-acme-v1',
  offerId: 'to-acme-blueriver',
  companyId: 'blueriver',
  title: 'Acme / BlueRiver Tender Offer',
  form: 'SC TO-T',
  kind: 'Announcement',
  filedDate: 'Oct. 1, 2026',
  filedTime: '9:14 AM',
  accession: '0009999-26-001041',
  baseStatus: 'New',
  extracted: {
    offeror: 'Acme Capital Corp.',
    target: 'BlueRiver Inc.',
    security: BR_SECURITY,
    cusip: BR_CUSIP,
    offerPrice: '$42.50/share',
    expiration: 'Nov. 12, 2026',
    withdrawal: brV1.withdrawal,
    minCondition: brV1.minCondition,
  },
  paragraphs: [
    {
      heading: 'SCHEDULE TO — Tender Offer Statement',
      segments: [
        seg('Tender Offer Statement under Section 14(d)(1) or 13(e)(1) of the Securities Exchange Act of 1934. (Synthetic demonstration document.) '),
      ],
    },
    {
      heading: 'Item 1. Summary Term Sheet',
      segments: [
        seg(
          'Acme Capital Corp., a Delaware corporation (the “Purchaser”), is making an offer to purchase all outstanding shares of common stock of BlueRiver Inc. ',
          'offeror',
        ),
        seg(
          'BlueRiver Inc., a Delaware corporation (the “Company”), is the subject company of this Offer. ',
          'target',
        ),
        seg(
          'The securities subject to the Offer are the shares of BlueRiver Inc. common stock, par value $0.01 per share, CUSIP 09500X101 (the “Shares”). ',
          'security',
          'cusip',
        ),
      ],
    },
    {
      heading: 'Item 4. Terms of the Transaction',
      segments: [
        seg(
          'The Purchaser is offering to purchase all outstanding shares of BlueRiver Inc. common stock at a purchase price of $42.50 per Share, net to the seller in cash. ',
          'offerPrice',
        ),
        seg(
          'The Offer is scheduled to expire at 11:59 p.m., Eastern Time, on November 12, 2026, unless extended. ',
          'expiration',
        ),
        seg(
          'Shares tendered pursuant to the Offer may be withdrawn at any time prior to the Expiration Date, and, unless already accepted for payment, after the date that is 60 days from the commencement of the Offer. ',
          'withdrawal',
        ),
        seg(
          'The Offer is conditioned upon, among other things, there being validly tendered and not withdrawn a number of Shares that, together with Shares already owned by the Purchaser, represents more than 50% of the outstanding Shares (the “Minimum Condition”). ',
          'minCondition',
        ),
      ],
    },
    {
      heading: 'Item 7. Position of the Subject Company',
      segments: [
        seg(
          'BlueRiver Inc. has not yet stated its position on the Offer and is expected to file a Solicitation/Recommendation Statement on Schedule 14D-9 within ten business days.',
        ),
      ],
    },
  ],
}

const filingV2: Filing = {
  id: 'f-acme-v2',
  offerId: 'to-acme-blueriver',
  companyId: 'blueriver',
  title: 'BlueRiver Response',
  form: 'SC 14D-9',
  kind: 'Target Response',
  filedDate: 'Oct. 5, 2026',
  filedTime: '1:05 PM',
  accession: '0009998-26-000377',
  baseStatus: 'Processed',
  extracted: {
    target: 'BlueRiver Inc.',
    offeror: 'Acme Capital Corp.',
    recommendation: 'Recommend tendering',
  },
  paragraphs: [
    {
      heading: 'SCHEDULE 14D-9 — Solicitation/Recommendation Statement',
      segments: [seg('Solicitation/Recommendation Statement under Section 14(d)(4) of the Securities Exchange Act of 1934. (Synthetic demonstration document.) ')],
    },
    {
      heading: 'Item 1. Subject Company Information',
      segments: [
        seg('The name of the subject company is BlueRiver Inc., a Delaware corporation (the “Company”). ', 'target'),
        seg(
          'This Statement relates to the tender offer by Acme Capital Corp. (the “Purchaser”) disclosed in the Schedule TO filed on October 1, 2026. ',
          'offeror',
        ),
      ],
    },
    {
      heading: 'Item 4. The Solicitation or Recommendation',
      segments: [
        seg(
          'The Board of Directors recommends that stockholders accept the Offer and tender their Shares pursuant to the Offer. ',
          'recommendation',
        ),
        seg('The Board’s determination was made after consultation with its independent financial and legal advisors.'),
      ],
    },
  ],
}

const filingV3: Filing = {
  id: 'f-acme-v3',
  offerId: 'to-acme-blueriver',
  companyId: 'blueriver',
  title: 'Acme / BlueRiver Amendment',
  form: 'SC TO-T/A',
  kind: 'Amendment',
  filedDate: 'Oct. 14, 2026',
  filedTime: '11:42 AM',
  accession: '0009999-26-001187',
  baseStatus: 'New',
  extracted: {
    offeror: 'Acme Capital Corp.',
    target: 'BlueRiver Inc.',
    offerPrice: '$45.00/share',
    expiration: 'Nov. 19, 2026',
  },
  paragraphs: [
    {
      heading: 'SCHEDULE TO/A — Amendment No. 1',
      segments: [
        seg(
          'This Amendment No. 1 amends the Tender Offer Statement on Schedule TO filed on October 1, 2026 by Acme Capital Corp. (the “Purchaser”). (Synthetic demonstration document.) ',
          'offeror',
        ),
        seg('The subject company of the Offer is BlueRiver Inc. ', 'target'),
      ],
    },
    {
      heading: 'Items 1–11. Amended Terms',
      segments: [
        seg('The Offer Price has been increased from $42.50 to $45.00 per Share. ', 'offerPrice'),
        seg(
          'The expiration of the Offer has been extended to 11:59 p.m., Eastern Time, on November 19, 2026. ',
          'expiration',
        ),
        seg(
          'Except as specifically set forth in this Amendment, all other terms and conditions of the Offer remain unchanged, including the Minimum Condition and withdrawal rights.',
        ),
      ],
    },
  ],
}

// ---------------------------------------------------------------- Supporting events

const horizonFields = blank({
  offeror: 'Horizon Holdings',
  target: 'BlueRiver Inc.',
  security: BR_SECURITY,
  cusip: BR_CUSIP,
  offerPrice: '$38.00/share',
  expiration: 'Sep. 15, 2026',
})
const horizonFields2 = { ...horizonFields, recommendation: 'Recommend against tendering' }

const buybackFields = blank({
  offeror: 'BlueRiver Inc.',
  target: 'BlueRiver Inc.',
  security: BR_SECURITY,
  cusip: BR_CUSIP,
  offerPrice: '$31.00/share',
  expiration: 'Apr. 4, 2025',
  minCondition: 'No minimum condition',
  recommendation: 'Issuer tender offer',
})

const northstarFields = blank({
  offeror: 'Pinecrest Partners',
  target: 'Northstar Holdings',
  security: 'Northstar Holdings Class A Common Stock',
  cusip: '66700N108',
  offerPrice: '$27.25/share',
  expiration: 'Oct. 18, 2026',
  recommendation: 'Neutral — no recommendation',
})

const greenstoneFields = blank({
  offeror: 'GreenStone Biotech',
  target: 'GreenStone Biotech',
  security: 'GreenStone Biotech Common Stock',
  cusip: '39300G107',
  offerPrice: '$14.00–$16.50/share',
  expiration: 'Nov. 30, 2026',
  minCondition: 'No minimum condition',
  recommendation: 'Issuer tender offer',
})

const summitFields = blank({
  offeror: 'Summit Retail Group',
  target: 'Summit Retail Group',
  security: 'Summit Retail Group Common Stock',
  cusip: '86600S104',
  offerPrice: '$18.75/share',
  expiration: 'Nov. 20, 2026',
  minCondition: 'No minimum condition',
  recommendation: 'Issuer tender offer',
})

export const filings: Filing[] = [
  filingV1,
  filingV3,
  filingV2,
  autoFiling({
    id: 'f-northstar',
    offerId: 'to-pinecrest-northstar',
    companyId: 'northstar',
    title: 'Pinecrest / Northstar Tender Offer',
    form: 'SC TO-T',
    kind: 'Announcement',
    filedDate: 'Sep. 28, 2026',
    filedTime: '2:30 PM',
    accession: '0009997-26-000912',
    fields: northstarFields,
    surface: ['offeror', 'target', 'security', 'offerPrice', 'expiration', 'withdrawal', 'minCondition'],
  }),
  autoFiling({
    id: 'f-greenstone',
    offerId: 'to-greenstone-issuer',
    companyId: 'greenstone',
    title: 'GreenStone Issuer Tender Offer',
    form: 'SC TO-I',
    kind: 'Announcement',
    filedDate: 'Oct. 9, 2026',
    filedTime: '10:05 AM',
    accession: '0009996-26-000448',
    fields: greenstoneFields,
    surface: ['offeror', 'security', 'offerPrice', 'expiration', 'withdrawal'],
  }),
  autoFiling({
    id: 'f-summit',
    offerId: 'to-summit-issuer',
    companyId: 'summit',
    title: 'Summit Retail Issuer Tender Offer',
    form: 'SC TO-I',
    kind: 'Announcement',
    filedDate: 'Oct. 14, 2026',
    filedTime: '3:20 PM',
    accession: '0009995-26-000203',
    baseStatus: 'Needs Review',
    arrivesOnFetch: true,
    fields: summitFields,
    surface: ['offeror', 'security', 'offerPrice', 'expiration', 'withdrawal'],
  }),
  // Historical filings (linked to completed / withdrawn events)
  autoFiling({
    id: 'f-horizon-1',
    offerId: 'to-horizon-blueriver',
    companyId: 'blueriver',
    title: 'Horizon / BlueRiver Tender Offer',
    form: 'SC TO-T',
    kind: 'Announcement',
    filedDate: 'Aug. 3, 2026',
    filedTime: '8:50 AM',
    accession: '0009990-26-000611',
    fields: horizonFields,
    surface: ['offeror', 'target', 'offerPrice', 'expiration'],
  }),
  autoFiling({
    id: 'f-horizon-2',
    offerId: 'to-horizon-blueriver',
    companyId: 'blueriver',
    title: 'Horizon / BlueRiver Termination',
    form: 'SC TO-T/A',
    kind: 'Amendment',
    filedDate: 'Aug. 24, 2026',
    filedTime: '4:12 PM',
    accession: '0009990-26-000702',
    fields: horizonFields2,
    surface: ['offeror', 'recommendation'],
  }),
  autoFiling({
    id: 'f-buyback-1',
    offerId: 'to-blueriver-buyback',
    companyId: 'blueriver',
    title: 'BlueRiver Issuer Tender Offer',
    form: 'SC TO-I',
    kind: 'Announcement',
    filedDate: 'Mar. 6, 2025',
    filedTime: '9:02 AM',
    accession: '0009880-25-000144',
    fields: buybackFields,
    surface: ['offeror', 'security', 'offerPrice', 'expiration'],
  }),
  autoFiling({
    id: 'f-buyback-2',
    offerId: 'to-blueriver-buyback',
    companyId: 'blueriver',
    title: 'BlueRiver Final Results',
    form: 'SC TO-I/A',
    kind: 'Amendment',
    filedDate: 'Apr. 8, 2025',
    filedTime: '5:30 PM',
    accession: '0009880-25-000231',
    fields: buybackFields,
    surface: ['offeror', 'offerPrice'],
  }),
]

/** Filings shown in the daily dashboard (historical filings are linked from company/offer views only). */
export const DASHBOARD_FILING_IDS = [
  'f-acme-v1',
  'f-acme-v3',
  'f-acme-v2',
  'f-northstar',
  'f-greenstone',
  'f-summit',
]

export const filingById = (id: string) => filings.find((f) => f.id === id)!

// ---------------------------------------------------------------- Tender offers

export const offers: TenderOffer[] = [
  {
    id: 'to-acme-blueriver',
    title: 'Acme Capital Corp. Tender Offer for BlueRiver Inc.',
    offerorName: 'Acme Capital Corp.',
    targetId: 'blueriver',
    type: 'Third-Party Tender Offer',
    status: 'Pending',
    announced: 'Oct. 1, 2026',
    versions: [
      {
        id: 'v1',
        number: 1,
        date: 'Oct. 1, 2026',
        filingId: 'f-acme-v1',
        form: 'SC TO-T',
        summary: 'Initial offer at $42.50/share',
        fields: brV1,
        changes: [],
        unchanged: [],
      },
      {
        id: 'v2',
        number: 2,
        date: 'Oct. 5, 2026',
        filingId: 'f-acme-v2',
        form: 'SC 14D-9',
        summary: 'Board recommends tender',
        fields: brV2,
        changes: [{ field: 'recommendation', previous: 'Not yet issued', current: 'Recommend tendering' }],
        unchanged: ['Offer price', 'Expiration date', 'Minimum tender condition', 'Withdrawal rights'],
      },
      {
        id: 'v3',
        number: 3,
        date: 'Oct. 14, 2026',
        filingId: 'f-acme-v3',
        form: 'SC TO-T/A',
        summary: 'Price increased and deadline extended',
        fields: brV3,
        changes: [
          { field: 'offerPrice', previous: '$42.50/share', current: '$45.00/share' },
          { field: 'expiration', previous: 'Nov. 12, 2026', current: 'Nov. 19, 2026' },
        ],
        unchanged: ['Minimum tender condition', 'Withdrawal rights', 'Affected security', 'Board recommendation'],
        hiddenUntilProcessed: true,
      },
    ],
  },
  {
    id: 'to-horizon-blueriver',
    title: 'Horizon Holdings Tender Offer for BlueRiver Inc.',
    offerorName: 'Horizon Holdings',
    targetId: 'blueriver',
    type: 'Third-Party Tender Offer',
    status: 'Withdrawn',
    announced: 'Aug. 3, 2026',
    versions: [
      {
        id: 'v1',
        number: 1,
        date: 'Aug. 3, 2026',
        filingId: 'f-horizon-1',
        form: 'SC TO-T',
        summary: 'Initial offer at $38.00/share',
        fields: horizonFields,
        changes: [],
        unchanged: [],
      },
      {
        id: 'v2',
        number: 2,
        date: 'Aug. 24, 2026',
        filingId: 'f-horizon-2',
        form: 'SC TO-T/A',
        summary: 'Offer terminated; board recommended against',
        fields: horizonFields2,
        changes: [{ field: 'recommendation', previous: 'Not yet issued', current: 'Recommend against tendering' }],
        unchanged: ['Offer price', 'Expiration date', 'Security'],
      },
    ],
  },
  {
    id: 'to-blueriver-buyback',
    title: 'BlueRiver Inc. Issuer Tender Offer (2025)',
    offerorName: 'BlueRiver Inc.',
    targetId: 'blueriver',
    type: 'Issuer Tender Offer',
    status: 'Completed',
    announced: 'Mar. 6, 2025',
    versions: [
      {
        id: 'v1',
        number: 1,
        date: 'Mar. 6, 2025',
        filingId: 'f-buyback-1',
        form: 'SC TO-I',
        summary: 'Issuer buyback announced at $31.00/share',
        fields: buybackFields,
        changes: [],
        unchanged: [],
      },
      {
        id: 'v2',
        number: 2,
        date: 'Apr. 8, 2025',
        filingId: 'f-buyback-2',
        form: 'SC TO-I/A',
        summary: 'Final results reported; offer completed',
        fields: buybackFields,
        changes: [],
        unchanged: ['Offer price', 'Expiration date', 'Security'],
      },
    ],
  },
  {
    id: 'to-pinecrest-northstar',
    title: 'Pinecrest Partners Tender Offer for Northstar Holdings',
    offerorName: 'Pinecrest Partners',
    targetId: 'northstar',
    type: 'Third-Party Tender Offer',
    status: 'Pending',
    announced: 'Sep. 28, 2026',
    versions: [
      {
        id: 'v1',
        number: 1,
        date: 'Sep. 28, 2026',
        filingId: 'f-northstar',
        form: 'SC TO-T',
        summary: 'Initial offer at $27.25/share',
        fields: northstarFields,
        changes: [],
        unchanged: [],
      },
    ],
  },
  {
    id: 'to-greenstone-issuer',
    title: 'GreenStone Biotech Issuer Tender Offer',
    offerorName: 'GreenStone Biotech',
    targetId: 'greenstone',
    type: 'Issuer Tender Offer',
    status: 'Pending',
    announced: 'Oct. 9, 2026',
    versions: [
      {
        id: 'v1',
        number: 1,
        date: 'Oct. 9, 2026',
        filingId: 'f-greenstone',
        form: 'SC TO-I',
        summary: 'Issuer tender announced at $14.00–$16.50/share',
        fields: greenstoneFields,
        changes: [],
        unchanged: [],
      },
    ],
  },
  {
    id: 'to-summit-issuer',
    title: 'Summit Retail Group Issuer Tender Offer',
    offerorName: 'Summit Retail Group',
    targetId: 'summit',
    type: 'Issuer Tender Offer',
    status: 'Pending',
    announced: 'Oct. 14, 2026',
    versions: [
      {
        id: 'v1',
        number: 1,
        date: 'Oct. 14, 2026',
        filingId: 'f-summit',
        form: 'SC TO-I',
        summary: 'Issuer tender announced at $18.75/share',
        fields: summitFields,
        changes: [],
        unchanged: [],
      },
    ],
  },
]

export const offerById = (id: string) => offers.find((o) => o.id === id)!

// ---------------------------------------------------------------- Client-side seed state

export const initialNotifications: ClientNotification[] = [
  {
    id: 'n-blueriver-new',
    type: 'New Tender Offer',
    offerId: 'to-acme-blueriver',
    companyId: 'blueriver',
    title: 'New Tender Offer — BlueRiver Inc.',
    body: 'Acme Capital Corp. has commenced a tender offer for BlueRiver Inc. at **$42.50 per share**. Expiration: **November 12, 2026**.',
    date: 'Oct. 1, 2026 · 9:30 AM',
    read: false,
    cta: 'View Offer',
  },
  {
    id: 'n-northstar-deadline',
    type: 'Suggested Action',
    offerId: 'to-pinecrest-northstar',
    companyId: 'northstar',
    title: 'Upcoming Deadline — Northstar Holdings',
    body: 'The Pinecrest Partners tender offer for Northstar Holdings expires on **October 18, 2026**, in 4 days.',
    date: 'Oct. 14, 2026 · 8:00 AM',
    read: true,
    cta: 'View Offer',
  },
  {
    id: 'n-greenstone-watch',
    type: 'Watchlist Update',
    offerId: 'to-greenstone-issuer',
    companyId: 'greenstone',
    title: 'Watchlist Update — GreenStone Biotech',
    body: 'GreenStone Biotech, a company on your watchlist, has announced an issuer tender offer at **$14.00–$16.50 per share**.',
    date: 'Oct. 9, 2026 · 10:40 AM',
    read: true,
    cta: 'View Offer',
  },
]

export const amendmentNotifications: ClientNotification[] = [
  {
    id: 'n-blueriver-amend',
    type: 'Amendment',
    offerId: 'to-acme-blueriver',
    companyId: 'blueriver',
    title: 'Tender Offer Updated — BlueRiver Inc.',
    body: 'Two material changes were identified:',
    bullets: [
      'Offer price increased from **$42.50 to $45.00 per share**',
      'Expiration extended from **November 12 to November 19, 2026**',
    ],
    date: 'Oct. 14, 2026 · 11:50 AM',
    read: false,
    cta: 'View Changes',
  },
  {
    id: 'n-blueriver-deadline',
    type: 'Deadline Change',
    offerId: 'to-acme-blueriver',
    companyId: 'blueriver',
    title: 'Deadline Changed — BlueRiver Inc.',
    body: 'The expiration date of the Acme Capital Corp. tender offer moved from **November 12, 2026** to **November 19, 2026**.',
    date: 'Oct. 14, 2026 · 11:50 AM',
    read: false,
    cta: 'View Offer',
  },
]

const allPrefs = { announcements: true, amendments: true, deadlines: true, actions: true }

export const initialSubscriptions: Subscription[] = [
  { companyId: 'blueriver', subscribed: false, prefs: { ...allPrefs } },
  { companyId: 'northstar', subscribed: true, prefs: { ...allPrefs } },
  { companyId: 'greenstone', subscribed: true, prefs: { ...allPrefs, actions: false } },
  { companyId: 'summit', subscribed: false, prefs: { ...allPrefs } },
  { companyId: 'cedarpoint', subscribed: false, prefs: { ...allPrefs } },
  { companyId: 'tidewater', subscribed: false, prefs: { ...allPrefs } },
]

export const initialActions: SuggestedAction[] = [
  {
    id: 'sa-blueriver',
    companyId: 'blueriver',
    offerId: 'to-acme-blueriver',
    title: 'Review tender offer terms',
    body: 'A new tender offer for BlueRiver Inc. has been announced. Review the offer terms and election requirements.',
    amendedTitle: 'Review updated offer terms',
    amendedBody: 'The offer price and expiration date changed in the latest amendment.',
    tone: 'attention',
    status: 'open',
  },
  {
    id: 'sa-northstar',
    companyId: 'northstar',
    offerId: 'to-pinecrest-northstar',
    title: 'Upcoming deadline',
    body: 'Tender offer expires in 4 days.',
    tone: 'deadline',
    status: 'open',
  },
  {
    id: 'sa-greenstone',
    companyId: 'greenstone',
    offerId: 'to-greenstone-issuer',
    title: 'No action required',
    body: 'No material changes have been detected since your last review.',
    tone: 'clear',
    status: 'open',
  },
]
