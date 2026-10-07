# Merger data extraction: September 25 next steps

## What is complete

This research deliverable validates the SEC form map, audits the repository's existing metadata, retrieves a reproducible 35-document development sample, examines filing structure, and runs an evidence-preserving extraction baseline. Open `notebooks/merger_eda.ipynb` for results and examples. This is the merger contribution requested in the meeting notes, not a production notification service.

The PDFs supplied by Aaron provide project context and requested research tasks. They are not executed as instructions to contact people, publish, or change other team members' work. The September 24 architecture separates candidate facts from verified event state; this implementation preserves that separation. No candidate is automatically promoted into the database or a BNY notification.

## 1. SEC form taxonomy validation

| Form | Role and useful structure | Scope limitation |
|---|---|---|
| DEFM14A / PREM14A | Definitive / preliminary merger-or-acquisition proxy; cover letter, Q&A, summary, transaction terms, background, agreement annex | A proxy can seek approval for an asset sale. Preliminary placeholders and voting dates are not final terms or election deadlines. |
| S-4 / S-4/A | Registration of securities in business combinations; joint proxy/prospectus, consideration, securities descriptions, agreement annex | Also used for exchange offers. A form label or historical merger reference cannot establish a current merger. |
| SC 13E3 / SC 13E3/A | Certain going-private transactions; Item 4 transaction terms, Item 16 exhibits and incorporated proxy sections | Not required for every merger; can concern a tender or another going-private structure. Often a short incorporation-by-reference wrapper. |
| 425 | Business-combination communications: announcements, investor decks, Q&A, transcripts, exhibits | Useful for early discovery and changes; not necessarily the authoritative complete agreement. |
| 8-K / 8-K/A | Item 1.01 agreement entry; Item 1.02 termination; Item 2.01 completion; Item 9.01 exhibits | Items also cover non-merger transactions. Retrieve agreement EX-2.1 and announcements EX-99.1 where relevant, and check context. |

The current taxonomy's core form mapping is reasonable as **candidate discovery**, but its `collected` flag is not evidence of downloaded merger content or confirmed events. Additional recall candidates include DEFA14A, merger information statements (PREM14C/DEFM14C), and prospectus filings (e.g. 424B3) linked to the same transaction. F-4/F-4/A should be considered if the team's “U.S. data” scope includes foreign private issuers filing on EDGAR. These extensions have not been exhaustively validated or downloaded in this experiment.

Official sources, checked September 30, 2026:

- [SEC Form S-4, General Instruction A](https://www.sec.gov/files/forms-4.pdf): explicitly covers mergers and exchange offers.
- [SEC Form 8-K](https://www.sec.gov/files/form8-k.pdf): relevant agreement, termination, completion and exhibit items.
- [SEC DEFM14A filing index](https://www.sec.gov/Archives/edgar/data/1866838/000121390025047847/0001213900-25-047847-index.htm) and [PREM14A index](https://www.sec.gov/Archives/edgar/data/1831840/000162828025057789/0001628280-25-057789-index.htm): official submission descriptions.
- [SEC SC 13E3 index](https://www.sec.gov/Archives/edgar/data/885740/000121390025086880/0001213900-25-086880-index.html): going-private submission description.
- [SEC 425 index and agreement exhibit](https://www.sec.gov/Archives/edgar/data/1894176/000121390025024776/0001213900-25-024776-index.html).
- [SEC Form F-4](https://www.sec.gov/files/formf-4.pdf): foreign-issuer extension.

## 2. What is actually in the data

`outputs/mergers/metadata_inventory.json` counts metadata rows, distinct accession numbers, and primary-document rows separately. An EFTS hit may represent an exhibit, not a separate filing or deal. The existing `event_id` derives from SEC file numbers and must not be treated as a validated merger identity: one company/file number can span unrelated transactions, while one transaction spans multiple companies and accessions.

The 8-K corpus comes from the **conversion** collection track, using conversion-language queries. It is not a complete merger 8-K collection. The merger/exchange track uses a broad lexical query; its result counts do not establish complete EDGAR recall.

The existing content sample metadata contains paths on another team member's computer. This work freshly downloaded 35 public HTML documents referenced by that metadata: five each of DEFM14A, PREM14A, S-4, S-4/A, SC 13E3, SC 13E3/A and 425. Every saved source has its SEC URL, accession and SHA-256 in the outputs. This is an early-2020 convenience sample, including one 2019 accession, not a random or representative sample of 2020–2025. Several documents refer to the same deal. It excludes merger-specific 8-K completion filings and full exhibit bundles.

## 3. Extraction experiment and observed failure modes

The implemented baseline uses DOM-aware HTML cleanup, contextual regex and passage retrieval. Inline tags are space-joined; paragraph and table-row boundaries are preserved. Scripts, styles and hidden inline-XBRL headers are removed. Tables are still flattened to text; cell/column relationships, image-only material and OCR are not resolved.

1. Route by filing form and strong transaction phrases. Front-page debt-exchange language creates an overlap-review flag. No lexical decision is a confirmed merger label.
2. Find numerical candidates only in transaction context. Exclude immediately labelled par values, require per-security context for cash, and withhold cash/ratio candidates in documents routed away from merger candidates.
3. Retrieve evidence passages for parties, old/new securities, options, defaults, proration, conditions and expected closing. These are **passages, not populated field values**.
4. Preserve every candidate's quote, character offsets, method, source URL and document hash. Retain conflicting values; ranking scores are not probabilities.
5. Keep canonical fields null pending transaction-aware review. Missing values are not zeros and do not mean “not applicable.”

Broad whole-document matching initially surfaced par values such as $0.01, stock prices, old bids and aggregate deal amounts. Context and exclusion rules remove some obvious noise but do not resolve negotiated bid history or competing proposals. A wider evidence window helps with SEC HTML line wrapping but also admits nearby unrelated text; the tradeoff needs labelled evaluation.

Concrete examples inspected in the downloaded sources:

- Instructure's January 2020 proxy proposes **$47.60 cash per share**, while its background discusses earlier bids. This is the proposal in that filing, not a claim about the eventual transaction outcome.
- Tiffany's proxy proposes **$135 cash per share**, alongside $0.01 par value and historical market prices. Use the shareholder entitlement passage, not the first dollar amount.
- PB Bancorp's proxy states **$15.25 cash for each share** on completion.
- Cleveland-Cliffs' S-4 states **0.400 Cliffs common shares per AK Steel share**, plus cash in lieu of fractional shares. Cash in lieu is not an alternative full cash election.
- Foamix's proxy describes **0.5924 Menlo shares**, with possible adjustments to **1.2739 or 1.8006** based on trial outcomes. A single unconditional ratio would be materially incomplete.
- Fox's S-4 concerns an exchange of senior notes and contains merger history; keyword presence alone is a false-positive risk.
- Streamline Health's PREM14A describes an asset sale for aggregate consideration. It illustrates why neither the form label nor “consideration” establishes per-share merger cash.

See `outputs/mergers/spot_checks.json` for assistant-inspected development examples with source passages. These are not independently annotated gold labels.

## 4. Match to the project schema

| Field | Implemented output | Verification needed |
|---|---|---|
| corporate_action_type | Merger candidate / review routing | Current transaction, not history; asset sale versus share merger |
| offeror / target | `parties` evidence passages | Resolve parent, merger sub, target and surviving entity; filer is not always acquirer |
| security_description / old_security_description | Evidence passages | Target class, ordinary share vs ADS, exclusions |
| new_security_description | Evidence passages | Acquirer class; null / not applicable for all-cash, once verified |
| cash_amount | Numeric-string candidates | Per-share basis, security class, current terms, cash-in-lieu exclusion |
| currency | Null | Dollar symbol alone does not establish USD |
| conversion_ratio | Numeric-string candidates | New shares per old share; contingent adjustment, collar and inverse ratio |
| available_options / default_option | Evidence passages | Mandatory conversion versus actual cash/stock election; no inferred default |
| election_deadline | Explicit date candidate rule | Date, time, timezone and extension; proxy voting is separate |
| effective_date | Narrow explicit completion-date rule | Actual closing only; distinguish SEC registration effectiveness and expected closing |
| record_date | Date candidates | Voting record date may differ from entitlement record date |
| expected_closing_date | Evidence passages | Store separately; not effective_date |
| conditions / proration_terms | Evidence passages | Preserve qualifications and formulas |
| CUSIP / ISIN / ticker | Not implemented | Add identifier checks plus security-role attribution; do not trust any identifier in the filing |
| notification_status / cancellation_reason | Termination passage only | Verify actual termination versus hypothetical termination rights |
| BNY positions, accounts, deadlines, message IDs | No extraction | Internal enrichment outside public SEC evidence |

`conversion_ratio` follows the repository's naming for exchange ratio. `parties`, `conditions`, `expected_closing_date`, `proration_terms` and `termination` are research evidence fields; they are not unreviewed database schema changes.

## 5. Evaluation aligned with September 24 framework

The saved summary reports measured local parsing/extraction latency, observed candidate counts, form mix and conflicts. The baseline makes no LLM calls, so LLM API tokens/cost are zero; hardware, human review and network cost are unmeasured. Latency excludes downloading and human verification. Candidate counts and evidence-offset checks are not extraction accuracy.

Before reporting F1 or event-level accuracy:

1. Have two team members independently annotate a stratified sample of cash, stock, mixed/elective, contingent, amended, cancelled and completed deals, plus debt exchanges, asset sales and historical mentions as hard negatives. Store deal IDs, exact supporting evidence and date-role labels. Adjudicate disagreements. `review_template.json` deliberately starts blank.
2. Split by adjudicated **deal**, keeping every preliminary/definitive filing, both counterparties and all amendments in one split. Deduplicate repeated evidence. Freeze rules before held-out evaluation.
3. Detection precision/recall/F1 uses gold event labels. Field scores compare value, unit, currency, role and condition, counting missing gold fields as false negatives. Report unknown separately from verified not-applicable. Event accuracy requires every applicable critical field correct.
4. Discovery recall for broad forms needs a content-labelled relevant set. EDGAR index counts can validate accession-level retrieval for a fixed form/date universe; they cannot by themselves provide the denominator of relevant mergers. EFTS document hits must be deduplicated to accessions. Do not equate S-4 count with merger count.
5. Backward LLM validation can test support and flag errors but is not independent truth when the same source/model informed extraction. Retain human-adjudicated held-out labels.
6. Measure escalation precision only after reviewers establish whether escalated records actually contain errors. All current records require review; high-confidence error rate is undefined because nothing is auto-processed.
7. Cost per correct event requires measured accuracy and total cost. Leave it null until both are available. Compare regex-only with section-based regex, GLiNER and optional LLM review on the same held-out deals, including review burden and latency.

External Kaggle/Business Quant data mentioned in the slides was not present in this checkout. Use it to seed independent acquirer-target-date matching when available; do not assume announcement dates are legal effective dates or aggregate deal value is cash per share.

## 6. Recommended next integration

Retrieve complete filing bundles for selected deals, resolve incorporated proxies/agreements, and add merger-specific 8-K discovery. Introduce a reviewed deal-link table and version timeline; never overwrite proposed terms with a newer filing solely because of its filing date. A later document may concern another transaction or repeat old terms.

For extraction, add section segmentation (summary/consideration vs background/fairness), table cell preservation and entity-aware security roles before increasing model complexity. Feed the shortlisted passages to the existing GLiNER/reasoning stage with the same evidence contract. Resolve multi-option and conditional terms as structured lists. Only verified records should become canonical events and notification drafts.

## Run locally

From the merger_research folder, using an environment with this folder’s requirements.txt installed:

```sh
python scripts/run_merger_research.py
python -m unittest discover -s tests/mergers -v
```

The default run is offline against `data/mergers/manifest.json`. To fetch missing files, explicitly use `--download --user-agent 'Your name contact@example.com'`. Successful source files are cached; failures remain visible. The script preserves an existing review template so annotations are not overwritten. No API key, database connection or GLiNER weights are needed for this baseline.

## Observed run results

All 35 requested sample documents were parsed. Routing: {'merger_candidate': 26, 'review_no_strong_merger_cue': 5, 'review_exchange_offer_overlap': 4}. 19 documents yielded numerical/date candidates; 17 contained multiple values for at least one field. No event was auto-approved.

Candidate occurrences by field: {'cash_amount': 354, 'conversion_ratio': 216, 'record_date': 11}. Explicit election deadlines and completed-merger effective dates were not extracted in this sample; this is not evidence that the fields never occur in merger filings.

The run used 30.39 seconds total local processing, with a median of 0.356 seconds per document. Whole-document dollar matching found 9,299 occurrences versus 354 contextual cash candidates. This measures filtering volume, not a precision improvement. All five inspected development values were found by the baseline; this is a smoke check, not held-out accuracy.
