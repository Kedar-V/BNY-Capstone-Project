import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import {
  amendmentNotifications,
  companyById,
  DASHBOARD_FILING_IDS,
  filingById,
  filings,
  initialActions,
  initialNotifications,
  initialSubscriptions,
  offerById,
  offers,
} from '../data/mock'
import type {
  ActionStatus,
  AlertPrefs,
  ClientNotification,
  FieldKey,
  Filing,
  Subscription,
  SuggestedAction,
  TenderOffer,
  TenderOfferVersion,
} from '../types'

interface Toast {
  id: number
  message: string
}

interface AppState {
  amendmentProcessed: boolean
  fetched: boolean
  fetching: boolean
  fetchMessage: string
  notifications: ClientNotification[]
  subscriptions: Subscription[]
  actions: SuggestedAction[]
  toasts: Toast[]
  dashboardFilings: Filing[]
  totalFetched: number
  toast: (message: string) => void
  fetchFilings: () => void
  processAmendment: () => void
  setNotificationRead: (id: string, read: boolean) => void
  markAllRead: () => void
  toggleSubscription: (companyId: string) => void
  setPref: (companyId: string, key: keyof AlertPrefs, value: boolean) => void
  setActionStatus: (id: string, status: ActionStatus) => void
  reset: () => void
  filingStatus: (f: Filing) => string
}

const Ctx = createContext<AppState | null>(null)

export function useApp() {
  const v = useContext(Ctx)
  if (!v) throw new Error('useApp must be used inside AppProvider')
  return v
}

const BASE_FETCHED = 148
const AMENDMENT_FILING_ID = 'f-acme-v3'

export function AppProvider({ children }: { children: ReactNode }) {
  const [amendmentProcessed, setAmendmentProcessed] = useState(false)
  const [fetched, setFetched] = useState(false)
  const [fetching, setFetching] = useState(false)
  const [fetchMessage, setFetchMessage] = useState('Last fetched from SEC EDGAR at 8:00 AM ET')
  const [notifications, setNotifications] = useState(initialNotifications)
  const [subscriptions, setSubscriptions] = useState(initialSubscriptions)
  const [actions, setActions] = useState(initialActions)
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextToast = useRef(1)

  const toast = useCallback((message: string) => {
    const id = nextToast.current++
    setToasts((t) => [...t, { id, message }])
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3200)
  }, [])

  const fetchFilings = useCallback(() => {
    setFetching(true)
    setFetchMessage('Contacting SEC EDGAR…')
    window.setTimeout(() => {
      setFetching(false)
      if (fetched) {
        setFetchMessage('No new filings since 3:20 PM ET')
      } else {
        setFetched(true)
        setFetchMessage('Fetched 9 new filings · 1 tender-offer related · 1 needs review')
        toast('Fetched 9 new filings from SEC EDGAR')
      }
    }, 1600)
  }, [fetched, toast])

  const processAmendment = useCallback(() => {
    setAmendmentProcessed(true)
    setNotifications((n) => [...amendmentNotifications, ...n])
    toast('Amendment detected — 2 client notifications created')
  }, [toast])

  const setNotificationRead = useCallback((id: string, read: boolean) => {
    setNotifications((n) => n.map((x) => (x.id === id ? { ...x, read } : x)))
  }, [])

  const markAllRead = useCallback(() => {
    setNotifications((n) => n.map((x) => ({ ...x, read: true })))
    toast('All notifications marked as read')
  }, [toast])

  const toggleSubscription = useCallback(
    (companyId: string) => {
      const next = !subscriptions.find((s) => s.companyId === companyId)?.subscribed
      setSubscriptions((subs) => subs.map((s) => (s.companyId === companyId ? { ...s, subscribed: next } : s)))
      const name = companyById(companyId).name
      toast(next ? `Subscribed to ${name}` : `Unsubscribed from ${name}`)
    },
    [subscriptions, toast],
  )

  const setPref = useCallback(
    (companyId: string, key: keyof AlertPrefs, value: boolean) => {
      setSubscriptions((subs) =>
        subs.map((s) => (s.companyId === companyId ? { ...s, prefs: { ...s.prefs, [key]: value } } : s)),
      )
      toast('Alert preference saved')
    },
    [toast],
  )

  const setActionStatus = useCallback(
    (id: string, status: ActionStatus) => {
      setActions((a) => a.map((x) => (x.id === id ? { ...x, status } : x)))
      toast(status === 'reviewed' ? 'Marked as reviewed' : status === 'dismissed' ? 'Action dismissed' : 'Action restored')
    },
    [toast],
  )

  const reset = useCallback(() => {
    setAmendmentProcessed(false)
    setFetched(false)
    setFetching(false)
    setFetchMessage('Last fetched from SEC EDGAR at 8:00 AM ET')
    setNotifications(initialNotifications)
    setSubscriptions(initialSubscriptions)
    setActions(initialActions)
    toast('Demo reset to starting state')
  }, [toast])

  const dashboardFilings = useMemo(
    () => DASHBOARD_FILING_IDS.map(filingById).filter((f) => fetched || !f.arrivesOnFetch),
    [fetched],
  )

  const filingStatus = useCallback(
    (f: Filing) => {
      if (f.id === AMENDMENT_FILING_ID) return amendmentProcessed ? '2 Changes' : 'Awaiting Processing'
      return f.baseStatus
    },
    [amendmentProcessed],
  )

  const value: AppState = {
    amendmentProcessed,
    fetched,
    fetching,
    fetchMessage,
    notifications,
    subscriptions,
    actions,
    toasts,
    dashboardFilings,
    totalFetched: BASE_FETCHED + (fetched ? 9 : 0),
    toast,
    fetchFilings,
    processAmendment,
    setNotificationRead,
    markAllRead,
    toggleSubscription,
    setPref,
    setActionStatus,
    reset,
    filingStatus,
  }

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

// ---------------------------------------------------------------- Offer view helper

export interface OfferView {
  offer: TenderOffer
  versions: TenderOfferVersion[]
  current: TenderOfferVersion
  previous?: TenderOfferVersion
}

export function useOffer(offerId: string | undefined): OfferView | undefined {
  const { amendmentProcessed } = useApp()
  const offer = offers.find((o) => o.id === offerId)
  if (!offer) return undefined
  const versions = offer.versions.filter((v) => !v.hiddenUntilProcessed || amendmentProcessed)
  return { offer, versions, current: versions[versions.length - 1], previous: versions[versions.length - 2] }
}

export interface Evidence {
  filing: Filing
  version: TenderOfferVersion
  text: string
}

/** Latest visible filing whose text contains a passage supporting this field. */
export function findEvidence(view: OfferView, field: FieldKey): Evidence | undefined {
  for (let i = view.versions.length - 1; i >= 0; i--) {
    const version = view.versions[i]
    const filing = filingById(version.filingId)
    for (const p of filing.paragraphs) {
      const s = p.segments.find((x) => x.fields?.includes(field))
      if (s) return { filing, version, text: s.text.trim() }
    }
  }
  return undefined
}

export const allOffersFor = (companyId: string) => offers.filter((o) => o.targetId === companyId)
export const offerForFiling = (f: Filing) => offerById(f.offerId)
export const filingsForOffer = (offerId: string) => filings.filter((f) => f.offerId === offerId)
