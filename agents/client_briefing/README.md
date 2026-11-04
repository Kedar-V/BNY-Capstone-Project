# Client Briefing Agent

Reads a client's holdings and watchlist and writes a short, prioritized corporate-action brief. Numbers are worked out
for the client's own position, and every value links to the SEC filing behind it. It gives information only, never
investment advice.

## How a brief is built

| Step | What happens | Code |
|---|---|---|
| 1. Event store | Filings become events, readable as of any date. Later filings are invisible to an earlier brief. | `event_store.py` |
| 2. Match holdings | Events are matched to positions by ticker, then per-share terms become client numbers. | `impact.py` |
| 3. Prioritize | Action needed > terms changed > new > recently closed > on the horizon. Rules only. | `prioritize.py` |
| 4. Generate | The LLM writes a summary from the structured record. It never calculates. | `narrate.py` |
| 5. Review & deliver | Checks reject bad drafts and hold doubtful items for an operations reviewer. | `verify.py` |

`agent.py` runs the steps and records a trace in each brief.

### What is and is not left to the model

Everything that must be exact is code: which events apply, the arithmetic, priority and deadlines. The model only
writes sentences. Each draft must pass these checks: every number has to appear in the record; no advice wording; no
past tense for a deadline that is still ahead; addressed to the reader, with no mention of the record. A rejected
draft gets one retry with the problem stated, then falls back to a fixed template.

### When an item is held for review

| Code | Meaning |
|---|---|
| `offering_limit` | The calculated purchase is bigger than the whole offering. The number is replaced by "Prorated". |
| `date_conflict` | Dates contradict each other or look like a typo in the source. |
| `deadline_moved_earlier` | A deadline moved earlier, which is unusual. |
| `impact_missing` | An action-needed item has no client numbers. |
| `no_evidence` / `quote_not_found` | A deadline has no supporting quote, or a quote is not in the filing text. |

## Data

The team treats the StackAI extraction outputs as ground truth for now, so the agent reads them as they are.

| Input | Source |
|---|---|
| Rights offerings | `rights_issues_v2.csv`, Alex's run of the StackAI workflow (96 filings, 37 events) |
| Mergers | `mergers.csv`, Aesha's run of the StackAI workflow (562 filings, 461 events) |
| Tender offers | `tender_offers.csv`, the StackAI run in `load_tender_filings.ipynb` that also feeds the demo's other pages (507 filings, 309 events) |
| Tickers | `selected_filings.csv` from the team loader for rights and mergers; the extracted `ticker` column for tender offers |
| SEC file numbers | `selected_filings.csv`; `corporate-actions-demo/scripts/cache/file_numbers.json` for tender offers |
| Client positions | `clients.json`, **simulated**. Most holdings were picked from companies that have events, so the share of events that touch a client is far higher than it would be in a real account. |

`eval/rights_gold_500.json` is a separate annotated answer key used by `evaluate.py` to check the arithmetic on rights offerings. It is not an input to the brief.

## What the brief covers

`ENABLED_ACTIONS` in `config.py` is the switch. Remove an action and rebuild: it leaves the briefs and the demo's Event type filter.

### Tender offers

- One event per SEC file number. A new Schedule TO filed after the last offer expired starts a new event.
- An offer reaches a client only if it covers shares. Offers for notes, preferred stock, warrants or options do not touch a holder of the common stock.
- Only 67 of the 309 tender events have a ticker and cover shares, because the extracted `ticker` column is often empty. The others cannot match a position yet. Matching by CUSIP, which is filled more often, would raise this.
- Cash is shown as "if all are accepted", for a stated price or both ends of a price range. A formula price (usually net asset value) or a non-cash offer gets no cash figure, and the card says why.
- DXLG, FORA and WBD appear in both the merger and tender data. A client holding one would see two cards. No demo client holds them.

## Assumptions to confirm with BNY

- BNY cut-off = official deadline minus 3 weekdays (`CUTOFF_BUSINESS_DAYS` in `config.py`). Holidays are ignored.
- "Action needed" = BNY cut-off within 14 days (`ACTION_WINDOW_DAYS`).
- Positions are the same across brief dates. In production they would come from custody records as of each date.
- For a merger, per-share consideration is calculated only when the holding is in the company being acquired.
- Positions are matched by ticker. BNY's custody records may use CUSIP or ISIN instead.

## Run it

From the repository root (`requirements`: pandas, requests):

```bash
# One brief in the terminal
python -m agents.client_briefing.agent --client demo-pension --as-of 2026-09-30

# Rebuild the demo data. --env-file holds API_URL and STACKAI_API_KEY; add --no-llm to skip the model
python -m agents.client_briefing.agent --build-demo --env-file ../.env

# Check filing quotes against the filing text
python -m agents.client_briefing.agent --build-demo --no-llm --rights-text-dir <folder with input_text>

# Tests and the score against the answer key
python -m pytest agents/client_briefing/tests -q
python -m agents.client_briefing.evaluate
```

The demo reads `corporate-actions-demo/src/data/briefs.json`, so it needs neither the API nor a network connection:

```bash
cd corporate-actions-demo && npm install && npm run dev
# http://localhost:5173/client/brief
```

## Changing the briefs

| To change | Edit |
|---|---|
| Cut-off rule, action window, which event types are covered | `config.py` |
| Calculated shares and cash | `impact.py` |
| What counts as action needed, and the order | `prioritize.py` |
| What gets held for review, and the checks on summaries | `verify.py` |
| The LLM prompt | `narrate.py` |
| Simulated clients | `clients.json` |

Then rebuild the data and the one-file demo from the repository root:

```bash
python -m agents.client_briefing.agent --build-demo --no-llm
python corporate-actions-demo/scripts/build_standalone.py
```

- **API key:** `--no-llm` reuses `narrative_cache.json`, so unchanged items keep their summaries. An item whose facts changed gets the fixed template instead. To have the LLM write those, replace `--no-llm` with `--env-file <file with API_URL and STACKAI_API_KEY>`, then read the new summaries.
- **"Found in filing" badges:** these need the filing text, which is not in the repository. Add `--rights-text-dir <folder with the rights input_text>` to keep them. Without it the badges disappear, and everything else stays the same.

## Demo walkthrough

1. **My Brief**, Demo Pension Fund, Sep 30: ACV Auctions, Utah Medical, Roku, Rent the Runway and Supernus need action; open **View source** on one to see the quotes. Under **On the horizon**, Somnigroup is an acquirer holding, so its consideration is not calculated.
2. **Demo University Endowment**, Jan 30: the ArrowMark rights offering, the worked example on the slide.
3. **Demo Family Office**, Sep 30: BayFirst's BNY cut-off has already passed.
4. **Demo Family Office**, Jan 30: one item is held. Go to **Operations > Brief Review**, see why AIM ImmunoTech was stopped, clear it and return to the brief.
5. **Tender offers**: Demo Pension Fund, Mar 27 has Wix, where the price is a range. Demo University Endowment, Sep 30 has Virtus, where the price is a percentage of net asset value, so the card shows shares but no cash.
6. **How this brief was built** at the bottom of the brief shows the agent's run log.
