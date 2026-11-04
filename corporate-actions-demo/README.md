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

On Windows, if PowerShell refuses `npm` because running scripts is disabled, use `npm.cmd` instead, for example `npm.cmd run dev`.

`standalone/client_briefing_demo.html` is the whole demo in one file. Download it and double-click: no server or install needed. It does not update by itself, so rebuild it after the data changes:

```bash
python scripts/build_standalone.py    # --out to write it somewhere else
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
  - *Brief Review* — items the client briefing agent held back, with the reason, for a reviewer to clear.
- **Client Portal** — overview, notifications for watched companies, and a watchlist.
  - *My Brief* and *Holdings* — the client briefing agent's output for simulated clients, covering rights issues, mergers and tender offers. Built by [`agents/client_briefing`](../agents/client_briefing/README.md) into `src/data/briefs.json`.
