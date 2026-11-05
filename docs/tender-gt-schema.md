# Tender ground-truth (GT) schema

CSV used by eval: [`notebooks/evaluation/tender_offers.csv`](../notebooks/evaluation/tender_offers.csv).

Scored columns and core set are defined in [`src/evaluation/tender.py`](../src/evaluation/tender.py) (`GT_VALUE_FIELDS`, `CORE_GT_FIELDS`).

## Row grain and join

| Rule | Detail |
|------|--------|
| **One row** | One security / offer variant under a filing (e.g. Class I vs Class A). Same `accession_number` may appear on multiple rows. |
| **Join key** | `accession_number` → pipeline Concise Rep docs / `source_accession`. Do **not** join on `event_id` for scoring (GT `event_id` is not the preprocess file-number event). |
| **Empty values** | Use blank or `N/A` / `n/a` / `none` / `-`. Eval treats these as absent. |
| **Multi-value** | Prefer `; `-separated tokens in one cell (e.g. two CUSIPs). Soft-match accepts any token overlap where applicable. |

## What we need for GLiNER (core)

These are the fields scored with `--fields core` and used for span fine-tune anchors. Prefer **short, copyable strings** that appear verbatim in the filing (OTP FAQ / cover), not long narrative.

| Column | Required for core eval | Description | Preferred format / examples |
|--------|------------------------|-------------|-----------------------------|
| `accession_number` | **yes** (join) | SEC accession of the filing this row describes. | `0001193125-20-007345` |
| `subject_company` | **yes** | Target / issuer whose securities are sought. | Legal name as on cover, e.g. `Dermira, Inc.` |
| `bidder` | **yes** | Offeror / bidder making the tender. Not counsel or dealer manager. | `Eli Lilly and Company` |
| `security_description` | **yes** | Security being tendered (class, series, share type). | `Common Stock, par value $0.001 per share` or fund class name |
| `cusip` | if present in filing | CUSIP identifier(s). | `24909P100` or `815789201; 815789102` |
| `isin` | if present | ISIN identifier(s). | `US24909P1000` |
| `ticker` | if present | Exchange ticker. | `DERM` |
| `offer_price` | if present | Consideration **per share / unit** (or the short formula label if no fixed cash). | `$18.75` or `$18.75 per share`; avoid bare par `$0.001` |
| `currency` | if present | ISO currency of the offer price. | `USD` |
| `expiration_date` | if present | Offer expiration date/time (as stated). | `February 19, 2020` or `5:00 p.m., New York City time, on February 19, 2020` |
| `withdrawal_deadline` | if present | Last time to withdraw tendered shares. | Same date style as expiration |
| `settlement_date` | if present | Expected settlement / payment date. | Calendar date or short phrase from FAQ |
| `effective_date` | if present | Effective / commencement date of the offer. | Calendar date |
| `minimum_tender_condition` | if present | Minimum tender / “Minimum Condition” threshold. | `a majority of the outstanding Shares` or `%` text as in FAQ |
| `proration_terms` | if present | Proration / acceptance priority rule (short). | Short clause from FAQ, not full prospectus prose |

## Full scored GT value fields (coverage / future)

Same CSV; scored with `--fields all`. Narrative / agent fields are **not** owned by default GLiNER pass.

### Parties

| Column | Description |
|--------|-------------|
| `subject_company` | Target / subject company (see core). |
| `bidder` | Offeror / bidder (see core). |
| `parent` | Parent of bidder / offeror, if disclosed. |
| `acquisition_subsidiary` | Purchaser / acquisition vehicle (often a shell sub). |
| `dealer_manager` | Dealer manager firm(s). |
| `depositary` | Depositary / exchange agent. |
| `information_agent` | Information agent. |
| `other_parties` | Other named parties not covered above (free text / list). |

### Security identifiers

| Column | Description |
|--------|-------------|
| `security_description` | Security name / class (see core). |
| `ticker` | Ticker symbol. |
| `cusip` | CUSIP(s). |
| `isin` | ISIN(s). |

### Status / offer type

| Column | Description |
|--------|-------------|
| `event_status` | High-level status label (e.g. announced, expired, completed). |
| `event_status_details` | Longer status narrative (amendments, extensions). |
| `mandatory_voluntary_indicator` | `mandatory` / `voluntary` (or equivalent). |
| `offer_price_type` | Nature of consideration (cash, stock, mixed, NAV, etc.). |
| `offer_price` | Price amount or short formula (see core). |
| `currency` | Currency code. |
| `offer_price_basis` | Basis for price (e.g. per share, NAV as of valuation date). |
| `offer_price_qualifications` | Caveats on price (adjustments, interest, etc.) — often long-form. |

### Dates and conditions

| Column | Description |
|--------|-------------|
| `expiration_date` | Expiration (see core). |
| `withdrawal_deadline` | Withdrawal deadline (see core). |
| `settlement_date` | Settlement date (see core). |
| `effective_date` | Effective / start date (see core). |
| `minimum_tender_condition` | Minimum condition (see core). |
| `proration_terms` | Proration terms (see core). |
| `tendering_conditions` | How / where to tender (procedures) — usually narrative. |
| `available_options` | Election options (cash vs stock, etc.). |
| `default_option` | Default election if shareholder is silent. |
| `financial_terms` | Broader financial terms blurb — narrative; not GLiNER-owned. |
| `conditions_restrictions` | Offer conditions / restrictions — narrative; not GLiNER-owned. |

## Provenance / corpus metadata (not scored as extraction)

Present on the current CSV for lineage; eval does not treat these as extraction targets.

| Column | Description |
|--------|-------------|
| `corporate_action_type` | Always tender (or equivalent) for this sheet. |
| `event_id` | GT-side event id (often `tender_offer_{accession}`); **not** the preprocess file-number id. |
| `passages` | Legacy catch-all; prefer the **evidence / segment** columns below. |
| `form` | SEC form type (e.g. `SC TO-T`, `SC TO-I`). |
| `filing_date` | Filing date. |
| `registrant_name` | Registrant on the filing. |
| `registrant_cik` | Registrant CIK. |
| `action` | Corpus action / pipeline tag. |
| `filing_id` | Internal filing id. |
| `filing_index_url` | EDGAR index URL. |
| `document_count` | Docs under the filing. |
| `text_byte_count` / `text_size_mb` | Size stats. |
| `input_hash` | Content hash. |
| `status` / `relevance` / `input_coverage` | Dataset QA flags. |
| `error` | Ingest error, if any. |

## Evidence segments (required for GT **and** extraction)

**Yes — per field, on both sides.**

| Side | Where it lives |
|------|----------------|
| **GT labels** | Span evidence file (below) so fine-tune has real offsets. |
| **Extraction output** | Each Concise Rep `candidate_facts[]` entry and eval’s `pipeline_field_evidence.csv` — same shape: value + source doc + segment + offsets. |

Field values alone are not enough. For every filled core field we need **where it appears in the original filing**.

Prefer one evidence object per `(accession_number, field)` (or a JSON list if a value appears in multiple places).

| Column / key | Required | Description |
|--------------|----------|-------------|
| `field` | yes | GT column name, e.g. `offer_price` (eval CSV). On Concise Rep facts use `field_hint` (e.g. `offer_price`). |
| `value` / `raw` | yes | Extracted or labeled string. |
| `accession_number` / `source_accession` | yes | Filing accession. |
| `source_filename` | yes | Doc within the filing (e.g. `ex-99a1d.htm`, `d123.htm`). |
| `doc_role` | recommended | Pipeline role if known: `otp_summary`, `otp_faq`, `cover`, `exhibit`, … |
| `segment_text` / `passage` | yes | Contiguous excerpt from the **cleaned** source that contains the value (ideally ≤ ~900 chars). |
| `char_start` | yes | Inclusive start offset of the value **inside `segment_text`** (0-based). |
| `char_end` | yes | Exclusive end offset of the value inside `segment_text`. |
| `segment_char_start` | recommended | Start of `segment_text` in the full cleaned doc (for audit). |
| `segment_char_end` | recommended | End of `segment_text` in the full cleaned doc. |

### Extraction fact shape (Concise Rep)

```json
{
  "field_hint": "offer_price",
  "raw": "$18.75 per Share",
  "segment_text": "… We are offering to pay $18.75 per Share in cash …",
  "passage": "… We are offering to pay $18.75 per Share in cash …",
  "char_start": 24,
  "char_end": 40,
  "segment_char_start": 4410,
  "segment_char_end": 4520,
  "source_accession": "0001193125-20-007345",
  "source_filename": "d845123ddef14a.htm",
  "doc_role": "otp_faq",
  "confidence": 0.91,
  "rank_score": 1.2,
  "method": "gliner"
}
```

Eval writes the top-1 evidence per GT field to `outputs/tender_eval/pipeline_field_evidence.csv`.

Rules:

1. `segment_text[char_start:char_end] == value` (byte/char exact after the same cleanup the pipeline uses).
2. Prefer FAQ / cover / summary segments; avoid counsel letterheads for `bidder`.
3. For money/dates, include enough context in `segment_text` that “offer price” / “expiration” cues are visible — not a bare `$0.001` from the par-value line.
4. Multiple securities on one accession ⇒ separate GT rows, each with their own evidence (e.g. Class I vs Class A `security_description`).

### Example (JSONL, one span)

```json
{
  "accession_number": "0001193125-20-007345",
  "field": "offer_price",
  "value": "$18.75 per Share",
  "source_filename": "d845123ddef14a.htm",
  "doc_role": "otp_faq",
  "segment_text": "… How much are you offering to pay? We are offering to pay $18.75 per Share in cash …",
  "char_start": 52,
  "char_end": 68,
  "segment_char_start": 4410,
  "segment_char_end": 4520
}
```

Optional CSV shape if you stay tabular: keep the wide value columns, plus a parallel evidence file `tender_gt_spans.jsonl` (above), keyed by `accession_number` + `field`. Putting huge `segment_text` into every wide CSV cell is awkward; JSONL (or a `passages`-style JSON column) is better.

## Ideal CSV header (value fields + join)

Minimal header for new GT **values** (core-capable + full value set):

```text
accession_number,subject_company,bidder,parent,acquisition_subsidiary,dealer_manager,depositary,information_agent,other_parties,security_description,ticker,cusip,isin,event_status,event_status_details,mandatory_voluntary_indicator,offer_price_type,offer_price,currency,offer_price_basis,offer_price_qualifications,expiration_date,withdrawal_deadline,settlement_date,effective_date,minimum_tender_condition,proration_terms,tendering_conditions,available_options,default_option,financial_terms,conditions_restrictions
```

Plus a **span evidence** file (recommended):

```text
tender_gt_spans.jsonl  # records as in the example above
```

`accession_number` is mandatory for scoring; span evidence is mandatory for fine-tune quality.

## Span fine-tune vs field-only GT

| Artifact | Enough for soft-match eval? | Enough for GLiNER fine-tune? |
|----------|----------------------------|------------------------------|
| Wide CSV values only | Yes | No (string search is noisy; truncates wrong) |
| Values + `segment_text` + offsets | Yes | **Yes** |

Building more free-text rows helps eval coverage; building **offset-accurate segments from the original doc** is what improves the model.
