# EDA Summary — Multi-Type MVP (Datastore → Notification)

## Target event types

| MVP type | BNY-facing label | Corpus status | Primary public sources |
|----------|------------------|---------------|------------------------|
| **Tender offer** | TENDER OFFER | **Collected** | SC TO-T/I (+/A), SC 14D9 (+/A) |
| **Exchange offer** | EXCHANGE | Partial (inside some TO; need S-4) | SC TO-*, S-4, 14D9 |
| **Rights issue** | RIGHTS ISSUE | **Not collected** | 424B*, S-3 / S-3ASR, 8-K |
| **Merger** | MERGER | **Not collected** | DEFM14A, PREM14A, S-4, SC 13E-3 |
| **Conversion** | CONVERSION | **Not collected** | 8-K, 424B*, S-3 |

Do **not** invent coverage % for uncollected types. Use `outputs/mvp_corpus_gaps.csv`.

## Executable corpus (after EDGAR expansion)

| Metric | Value |
|--------|------:|
| Documents (EFTS hits) | **197,251** |
| Unique filings | **103,944** |
| Events (file_num / accession keys) | **14,518** |
| Date range | 2020-01-02 → 2025-12-31 |
| Tender MVP core (SC TO-T*) | **285** |
| Preferred (TO-T + 14D9) | **272** |

### Form coverage (collected)

| Track | Key forms present | Notes |
|-------|-------------------|-------|
| tender | SC TO-*, SC 14D9 | Unchanged |
| merger_exchange | S-4, DEFM14A, PREM14A, SC 13E3, 425 | Full primary-form coverage |
| rights | 424B2/3/5 (rights-language filter) | S-3/S-3ASR optional / not collected |
| conversion | 8-K (conversion-language filter) | Noisy; needs subtype labeling |

Primary-form readiness: tender / exchange / merger **100%**; rights / conversion **60%** (missing shelf S-3 only).


## Most relevant plots (use these)

| Figure | Why it matters |
|--------|----------------|
| `mvp_event_type_readiness.png` | Honest gap: which of the 5 types we can build now |
| `mvp_event_family_mix.png` | Event-centric mix (not exhibit-inflated form hits) |
| `mvp_selection_funnel.png` | Datastore pool gates for tender v1 |
| `mvp_field_relevance_by_event_type.png` | Which BNY fields each type needs |
| `mvp_schema_coverage_by_ownership.png` | Public vs internal → what to extract vs placeholder |
| `mvp_notification_field_roles.png` | Datastore column roles |
| `mvp_benchmark_field_coverage.png` | v1 extraction benchmark |
| `mvp_amendment_readiness.png` | Versioned history feasibility |

Demote raw “documents by form” hit counts for MVP decisions (exhibits inflate SC TO-I).

## Build order

1. **Tender** — ship datastore + extraction + notification draft on TO-T + 14D9  
2. **Exchange** — reclassify exchange language in TO; add S-4  
3. **Merger** — DEFM14A / S-4 / SC 13E-3 (election options)  
4. **Rights** — 424B* / S-3 (record/ex/subscription)  
5. **Conversion** — 8-K / prospectus (ratio/price)

See `outputs/mvp_build_order.csv`.

## Datastore field roles

From `outputs/datastore_field_catalog.csv`:

- **extract_from_public / derive_from_public** — populate from SEC docs  
- **annotate_then_store** — need manual GT (options, deadlines, ratios, CUSIP normalize)  
- **bny_placeholder** — position / processing / debit-credit (never score as extraction failure)  
- **exclude_or_investigate** — client cash/principal hybrids  

## v1 extraction benchmark

`corporate_action_type`, `security_description`, `cusip`, `ticker`, `election_deadline`, `response_deadline`, `notification_status`, `available_options`, `conversion_ratio`, `cash_amount` (consideration proxy only).

## Implications for MVP Design

1. **Types:** All five are in scope; **only tender is corpus-ready** for modeling now.  
2. **Public fields:** Event/security/election terms — yes (tender).  
3. **Internal:** Position/payment ledger fields — placeholders.  
4. **Manual GT:** Options, ratios, normalized IDs, amendment deltas, BNY `notification_type`.  
5. **Amendments:** Strong for tenders (~97% `/A`); reuse pattern when other types are collected.  
6. **Benchmark:** Fields above; add type-specific columns as corpus expands.  
7. **Sufficiency:** Tender extraction + grounding + amendment tracking — yes after annotation. Full 5-type notification MVP — **requires corpus expansion**.  
8. **Gaps:** Collect S-4, merger proxies, 424B*, conversion 8-Ks; subtype-label exchange offers inside Schedule TO.

**Bottom line:** Design the datastore around all five BNY event classes, but **build and evaluate v1 on third-party tenders (+ 14D9)** while the other four types are tracked as explicit collection gaps—not as zero-coverage extraction failures.
