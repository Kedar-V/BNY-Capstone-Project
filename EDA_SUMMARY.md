# EDA Summary — BNY Client Notification Schema vs Public Corporate-Action Documents

## Scope and evidence rules

This EDA measures how well **public SEC tender-offer filings** can populate the **BNY client-notification schema**.

| Corpus | Value |
|--------|-------|
| Source | SEC EFTS (public EDGAR) |
| Forms | `SC TO-T`, `SC TO-T/A`, `SC TO-I`, `SC TO-I/A`, `SC 14D9`, `SC 14D9/A` |
| Window | 2020-01-02 → 2025-12-31 |
| Event key | SEC `file_num` (fallback `NO_FILE_NUM:<accession>`) |

**Evidence labels**

- **Observed** — EFTS metadata or successful document download
- **Inferred** — regex mention detection on a stratified text sample (38 events / 60 docs). This is *not* extraction accuracy
- **Internal** — definitionally unavailable from public documents (reported as 0% public coverage)
- **Assumption** — event-type relevance priors used only to separate “not applicable” from “missing but relevant”

Missing scalars are treated as `null`; missing lists (e.g. `available_options`) as `[]`.  
`notification_type` is kept separate from `corporate_action_type`.

Artifacts: `notebooks/eda.ipynb`, `src/eda/`, `outputs/schema_coverage.csv`, `outputs/event_type_coverage.csv`, `outputs/data_quality_report.csv`.

---

## 1. Dataset overview (observed)

| Metric | Value |
|--------|------:|
| Unique events (by SEC file number) | **893** |
| Source documents (EFTS hits: primary + exhibits) | **32,046** |
| Unique filings (accessions) | **9,364** |
| Date range | 2020-01-02 → 2025-12-31 |
| Events with >1 document | **99.0%** |
| Events with ≥1 amendment filing (`/A`) | **870 (97.4%)** |
| Median documents / event | 20 |
| Median filings / event | 6 |

### Corporate-action types represented (document counts)

| Form | Documents |
|------|----------:|
| SC TO-I | 17,893 |
| SC TO-I/A | 6,495 |
| SC TO-T | 2,844 |
| SC TO-T/A | 2,388 |
| SC 14D9/A | 1,474 |
| SC 14D9 | 952 |

### Event-family mix (observed)

| `primary_form_family` | Events | Note |
|-----------------------|-------:|------|
| issuer_tender | 607 | Mostly SC TO-I fund/issuer repurchases |
| mixed | 277 | Same file number spans TO + 14D9 (typical third-party deals) |
| third_party_tender | 9 | Pure TO-T without 14D9 in window |

**Bias:** document volume is dominated by **issuer self-tenders**; economically interesting change-of-control tenders often appear as **mixed** TO-T + 14D9 events.

Cancellations/withdrawals/replacements are **not** first-class EFTS form types here; they appear (when present) as amendment filings and/or narrative language. Do not treat `/A` alone as cancellation.

---

## 2. BNY schema coverage matrix

Text-field % = share of **sample events with downloaded text** where a conservative regex detected a mention.  
Metadata fields use the **full event table**.

| Field | Public coverage | Primary source | Explicit/Derived | Difficulty |
|-------|----------------:|----------------|------------------|------------|
| notification_family | 100%* | filing text / form family | derived | low |
| notification_type | 73.7%* | SC 14D9 sample text | derived | medium |
| notification_status | 97.4%* | `/A` + status language | derived | medium |
| processing_status | **0%** | internal BNY | internal | n/a |
| mandatory_voluntary_indicator | 5.3%* | narrative | explicit | medium |
| security_description | **100%** | EFTS entity name (proxy) | explicit | low |
| isin | 0%* | rarely in sample | explicit | low |
| cusip | **97.4%*** | offer / 14D9 text | explicit | low |
| ticker | **51.2%** | EFTS display_names | explicit | low |
| currency | 13.2%* | narrative | explicit | low |
| coupon_rate | 2.6%* | debt contexts | explicit | medium |
| maturity_date | 0%* | debt contexts | explicit | medium |
| corporate_action_type | **100%** | EFTS form family | derived | low |
| event_subtype | 10.5%* | narrative | explicit | medium |
| effective_date | 18.4%* | narrative | explicit | medium |
| record_date | 18.4%* | narrative | explicit | medium |
| ex_date | 0%* | rarely applicable | derived | high |
| payment_date | 18.4%* | narrative | explicit | medium |
| settlement_date | 26.3%* | narrative | explicit | medium |
| old_security_description | 0%* | exchange offers | explicit | medium |
| old_security_isin | 0%* | exchange offers | explicit | medium |
| new_security_description | 26.3%* | exchange / issuer docs | explicit | medium |
| new_security_isin | 0%* | exchange offers | explicit | medium |
| conversion_ratio | 60.5%* | **noisy** (see note) | explicit | high |
| conversion_price | 0%* | convertibles | explicit | high |
| redemption_amount | 5.3%* | debt | explicit | medium |
| call_price | 2.6%* | debt | explicit | medium |
| election_required | 23.7%* | derived from language | derived | medium |
| available_options | 5.3%* | narrative | explicit | high |
| default_option | 0%* | narrative | explicit | high |
| election_deadline | **71.1%*** | expiration language | explicit | medium |
| response_deadline | **39.5%*** | expiration / withdrawal | explicit | medium |
| cancellation_reason | 18.4%* | termination language | explicit | high |
| eligible_quantity | **0%** | internal BNY | internal | n/a |
| position_quantity | **0%** | internal BNY | internal | n/a |
| principal_amount | 10.5%* | aggregate terms / internal | derived | high |
| interest_amount | 2.6%* | accrued interest / internal | derived | high |
| cash_amount | 73.7%* | offer-price **proxy only** | derived | high |
| debit_credit_indicator | **0%** | internal BNY | internal | n/a |

\*Inferred from 38-event text sample unless marked as metadata (ticker, security_description, corporate_action_type).

**Caveats**

- `conversion_ratio` is likely **inflated** by broad “per share” patterns — treat as weak signal, not usable GT.
- `cash_amount` detections are mostly **offer price / consideration mentions**, not client proceeds.
- `security_description` metadata coverage uses entity name as a **proxy**, not a normalized security master description.

Full machine-readable matrix: `outputs/schema_coverage.csv`.

---

## 3. Public vs internal classification

| Class | Fields |
|-------|--------|
| **Public-document extractable** | `security_description`, `isin`, `cusip`, `ticker`, `currency`, `coupon_rate`, `maturity_date`, `event_subtype`, date fields, conversion/exchange terms, election/option/deadline fields, `cancellation_reason`, `mandatory_voluntary_indicator` |
| **Derived from public** | `notification_family`, `notification_type`, `notification_status`, `corporate_action_type`, `election_required`, offer-price component of `cash_amount` |
| **BNY/internal-only** | `processing_status`, `eligible_quantity`, `position_quantity`, `debit_credit_indicator` |
| **Unclear / hybrid** | `ex_date`, client-level `principal_amount` / `interest_amount` / `cash_amount` (public terms × internal position) |

**MVP boundary:** public documents can support **event/security/election term extraction**. They cannot complete a full client notification without BNY position/account data.

---

## 4. Coverage by corporate-action type (sample)

From `outputs/event_type_coverage.csv` (sample events):

| Observation | Detail |
|-------------|--------|
| Richest public info | **mixed** TO-T + 14D9 events (target recommendation docs add CUSIP, deadlines, cash language) |
| Elections / options | Present but sparse; `available_options` ≈ 5% mention rate |
| Conversion/exchange | Weak in pure cash tenders; issuer/exchange subsets need separate sampling |
| Amendments | Extremely common (97% of events have `/A` filings) |
| Too simple? | Pure issuer fund repurchase TO-I can be repetitive boilerplate — useful for volume, weaker for reasoning diversity |

**MVP event types to start with:** third-party tenders (`SC TO-T`) **including mixed events with `SC 14D9`**. Hold issuer TO-I as a stretch track.

Observed MVP pool: **285** events with any `SC TO-T*` (**272** also have 14D9).

---

## 5. Document characteristics (observed + sample)

| Signal | Result |
|--------|--------|
| Formats | Mostly `.htm`/`.html` (HTML); PDF uncommon in this EFTS extract |
| Docs / event | Median 20; max 258 |
| Sample download | 60/60 OK in latest stratified sample |
| Length | Long HTML narratives + exhibit packages; tables common in Schedule TO HTML |
| Near-duplicates | Same exhibit filenames recur across amendments; content SHA1 dedupe available on sample |
| Multi-doc reality | Material facts are split across Schedule TO cover, Offer to Purchase, Letter of Transmittal, and 14D9 |

Example classes are exported under `outputs/simple_amendment_examples.csv`, `complex_amendment_examples.csv`, `unusual_document_volume.csv`.

---

## 6. Temporal / amendment analysis

Lifecycle used throughout:

`initial state → amendment(s) → final / completed / cancelled`

Earlier values are **not** overwritten; deltas are recorded separately.

| Metric | Observed |
|--------|----------|
| Events with amendments | 870 / 893 (97.4%) |
| MVP amendment-eval (simple: 1–5 amends, ≤60 docs) | **104** |
| MVP amendment-eval (complex) | **177** |

Field-level change detection on the text sample is **inferred presence-delta only** (see `outputs/amendment_field_deltas.csv`). Reliable amendment evaluation needs annotated value pairs for price, deadlines, options, and conditions.

Cancellations/withdrawals: detect via narrative + linked `/A` filings on the same `event_id`; not a separate structured EFTS label in this corpus.

---

## 7. Missingness taxonomy

| Missingness class | Examples |
|-------------------|----------|
| Internal BNY-only | `processing_status`, `position_quantity`, `eligible_quantity`, `debit_credit_indicator` |
| Not relevant for many cash equity tenders | `coupon_rate`, `maturity_date`, `ex_date`, conversion ISINs |
| Likely relevant but rarely/weakly detected | `available_options`, `default_option`, `isin`, `mandatory_voluntary_indicator` |
| Present as mentions; needs extraction/annotation | `cusip`, `election_deadline`, offer price / `cash_amount` proxy |
| Parsing/sample gap | Any text field outside the 38-event download sample — unmarked, not assumed present |

---

## 8. Ground-truth feasibility

| Class | Fields / notes |
|-------|----------------|
| **Strong automatic** | `corporate_action_type` (from form family), accession/file dates, amendment flag (`/A`), event_id |
| **Weak / heuristic** | `ticker` (metadata), `security_description` (entity proxy), `notification_status` (form suffix) |
| **Requires manual annotation** | `cusip`, deadlines, options, offer price/consideration, conditions, `notification_type` mapping |
| **Cannot evaluate from public data** | position/payment ledger fields; client `cash_amount` proceeds |

**First extraction benchmark subset (recommended):**  
`corporate_action_type`, `security_description`, `cusip`, `ticker`, `election_deadline`, `response_deadline`, `notification_status`, offer-price proxy (explicitly *not* client `cash_amount`).

---

## 9. Splits and leakage

**Rule:** split at **`event_id`** only. Keep all documents/amendments for an event in one split.

| Split | Target share | Approx. MVP events (n=285) |
|-------|-------------:|---------------------------:|
| train | 70% | 200 |
| validation | 15% | 43 |
| test | 15% | 43 |

**Leakage risks (observed):**

1. Document-level random splits would leak across the 99% multi-doc events  
2. Repeated issuers / fund families appear in many TO-I events — use CIK holdout for generalization tests  
3. Near-duplicate exhibits across amendments — another reason amendments must stay with the parent event  

---

# Implications for MVP Design

1. **Start with corporate-action types:** third-party tenders (`SC TO-T` / `SC TO-T/A`), preferring **mixed events that also include `SC 14D9`** (272 of 285 MVP events). Treat issuer `SC TO-I` as stretch / bias-aware secondary track.

2. **Fields realistically automatable from public data (with extraction + light mapping):**  
   `corporate_action_type`, `notification_status` (coarse), `security_description`, `cusip`, `ticker` (partial), `election_deadline` / expiration, offer price / consideration terms.

3. **Fields requiring BNY/internal data:**  
   `processing_status`, `eligible_quantity`, `position_quantity`, `debit_credit_indicator`, and **client-level** `cash_amount` / `principal_amount` / `interest_amount`.

4. **Fields needing manual ground-truth annotation:**  
   normalized CUSIP/security master fields, deadlines with timezones, `available_options` / `default_option`, material amendment value changes, BNY `notification_type` taxonomy labels.

5. **Best amendment/change examples:** MVP complex set (**177** events) for stress tests; simple set (**104**) for first amendment-detection eval. Represent as explicit state timelines, never silent overwrite.

6. **v1 extraction benchmark fields:**  
   `corporate_action_type`, `security_description`, `cusip`, `ticker`, `election_deadline`, `response_deadline`, `notification_status`, offer-price proxy.

7. **Is the dataset sufficient?**

| Capability | Verdict |
|------------|---------|
| Structured extraction | **Yes, for a bounded field subset** — after annotation of CUSIP/deadlines/price on the 285-event MVP pool |
| Full client-notification generation | **No** — blocked on internal position/payment fields |
| Amendment detection | **Yes** — dense `/A` histories; needs annotated field-level deltas |
| Source grounding | **Yes** — multi-doc HTML corpus with stable EDGAR URLs / accessions |

**Bottom line:** Public filings are sufficient to prototype **event-term extraction, grounding, and amendment tracking** for tender offers. They are **not** sufficient to populate a complete BNY client notification without internal account data. Design the MVP around that boundary explicitly.
