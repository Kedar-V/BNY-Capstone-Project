# Tender Offer Intelligence — Concept Demo

An interactive React demo showing the business value of a tender-offer intelligence platform for BNY:

**SEC EDGAR filing → relevant passages identified → structured tender-offer record → version / change history → client notifications, subscriptions and suggested next steps**

Everything is synthetic and runs locally. There is no backend, authentication or external API call. The extraction pipeline itself is built separately; this UI shows what it could enable.

## Setup

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # type-check + production build
```

Stack: React 18, TypeScript, Vite, React Router, Tailwind CSS, Lucide icons.

## App structure

```
src/
  types.ts              Domain types (Filing, TenderOffer, TenderOfferVersion, FieldChange, ...)
  data/mock.ts          All synthetic data: companies, filings (with source passages),
                        offers + versions, notifications, subscriptions, suggested actions
  state/AppState.tsx    Local React state: amendment processing, fetch, notifications,
                        subscriptions, actions, toasts, Reset. Also useOffer() / findEvidence()
  components/           Layout (shell, mode switch, About modal, drawer, toasts),
                        ui primitives, shared pieces (filings table, timeline, before/after, evidence drawer)
  pages/internal/       BNY Operations: Dashboard, FilingDetail, OfferRecord, History, CompanyView
  pages/client/         Client Portal: Home, Notifications, OfferDetail, Watchlist, Recommendations
```

Routes: `/internal/{dashboard, filings, filings/:id, companies/:id, tender-offers/:id, tender-offers/:id/history}` and `/client/{home, notifications, notifications/:id, watchlist, tender-offers/:id, recommendations}`.

## Suggested demo flow (5–7 min, no typing)

1. **BNY Operations → Daily Filings.** Optionally click *Fetch Today's Filings* (simulated; surfaces one extra filing that needs review).
2. Open **Acme / BlueRiver Tender Offer** (SC TO-T). Click fields on the right to jump to the source passage; click highlighted passages to select the field. Use the V1/V2/V3 buttons to move across the event's filings.
3. *Open tender offer record*. Click any field (e.g. Offer Price) to open the evidence drawer. Note the record currently shows $42.50 and Nov. 12.
4. *Version history* → **Process New Amendment**. V3 appears with the price and expiration changes highlighted, and two client notifications are created.
5. Switch to **Client Portal** (top bar). Home shows the new notifications; open the **Tender Offer Updated** notification.
6. In the client event view, review What Changed and Suggested Next Steps; click **Subscribe to Updates**.
7. Visit **Suggested Actions** (mark reviewed / dismiss / open event).

Use **Reset demo** in the top bar to return to the starting state.

## Synthetic data

All companies, CUSIPs, prices, dates, accession numbers and filing text are fictional. The Acme Capital Corp. / BlueRiver Inc. event (V1 SC TO-T Oct. 1, V2 SC 14D-9 Oct. 5, V3 SC TO-T/A Oct. 14, 2026) drives the demo; Northstar, GreenStone, Summit, Horizon and the historical BlueRiver buyback fill out the tables. Filings are labelled as synthetic demonstration documents.

Design notes:
- BlueRiver starts **unsubscribed** so step 6 can be shown. Notices for securities held in custody are delivered regardless, so the client still receives BlueRiver notifications.
- "Suggested actions" never tell a client whether to tender.
- *About this demo* (top bar / footer) lists what is being built versus what is conceptual.
