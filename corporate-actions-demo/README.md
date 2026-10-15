# BNY Corporate Actions

An interactive React application for monitoring **tender offers** and **mergers** from SEC EDGAR filings:

**SEC EDGAR filings → document processing → model-based term extraction → corporate action records with version history → client notifications and watchlists**

Records are built from the extraction outputs in `notebooks/evaluation/` (`tender_offers.csv` and `data/merger_*/mergers.csv`), including the source passages behind each extracted field.

## Setup

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # type-check + production build
```

Refresh the data after the evaluation outputs change:

```bash
python3 scripts/build_data.py    # writes src/data/filings.json (requires pandas)
```

Stack: React 18, TypeScript, Vite, React Router, Tailwind CSS, Lucide icons.

## Experiences

- **Operations**
  - *Filings Monitor* — all processed filings with filters. **Fetch Latest Filings** walks through the pipeline (connect to SEC EDGAR → identify new filings → download → process → extract with models → link to events → store) and then adds the newly processed filings to the feed.
  - *Corporate Actions* — one record per tender offer or merger, with extracted terms, source-passage evidence, version history and source filings.
- **Client Portal** — overview, notifications for watched companies, and a watchlist.
