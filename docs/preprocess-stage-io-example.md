# Preprocess stage I/O example (Tender Offer)

Companion to the design doc: [`lld-preprocess-pipeline.md`](lld-preprocess-pipeline.md).

Illustrative walkthrough for one preferred TO event (`event_id = 005-88347`, Dermira-style).
Values are representative of the planned artifact contracts; real filings will be longer.

Pipeline:

`inventory → download → cleanup → segment → gliner → assemble → load_db`

---

## 0. Catalog input (already in parquet / DB)

```text
event_id: 005-88347
mvp_event_type: tender_offer
forms: SC TO-T, SC 14D9, …
documents rows with: accession, filename, file_type, file_description, edgar_url
```

---

## 1. `inventory` → `inventory.json`

**In:** `data/processed/events.parquet`, `data/processed/documents.parquet`  
**Out:** which docs matter + cohort

```json
{
  "event_id": "005-88347",
  "cohort": "gold",
  "has_cover": true,
  "has_otp": true,
  "otp_method": "file_description",
  "has_lot": false,
  "has_14d9": true,
  "n_amendments": 0,
  "download_ready": true,
  "docs": [
    {
      "role": "cover",
      "accession": "0001193125-20-011457",
      "filename": "d859616dsctot.htm",
      "form": "SC TO-T",
      "hit_id": "hit-cover-001"
    },
    {
      "role": "otp",
      "accession": "0001193125-20-011457",
      "filename": "d859616dex99a1a.htm",
      "file_type": "EX-99.(A)(1)(A)",
      "file_description": "OFFER TO PURCHASE",
      "hit_id": "hit-otp-001"
    },
    {
      "role": "sc_14d9",
      "accession": "0001628280-20-000450",
      "filename": "dermirasc14d9.htm",
      "form": "SC 14D9",
      "hit_id": "hit-14d9-001"
    }
  ]
}
```

**Cohorts:** `gold` (cover + OTP + 14D9) | `needs_otp_resolve` | `incomplete`

---

## 2. `download` → `raw/` + download manifest

**In:** inventory  
**Out:** HTML bytes on disk

```text
data/preprocess/tender/events/005-88347/raw/
  0001193125-20-011457__d859616dsctot.htm
  0001193125-20-011457__d859616dex99a1a.htm
  0001628280-20-000450__dermirasc14d9.htm
```

**Raw OTP HTML snippet** (what lands on disk):

```html
<DOCUMENT>
<TYPE>EX-99.(A)(1)(A)
<FILENAME>d859616dex99a1a.htm
<TEXT>
<html><body>
<a name="toc">TABLE OF CONTENTS</a>
<a href="#sts">SUMMARY TERM SHEET</a>
<a href="#intro">INTRODUCTION</a>
…
<a name="sts"><b>SUMMARY TERM SHEET</b></a>
<p><b>Who is offering to buy my shares?</b></p>
<p>Eli Lilly and Company, through its subsidiary, is offering to purchase
all outstanding shares of Dermira, Inc.</p>
<p><b>How much are they offering to pay?</b></p>
<p>We are offering to pay $18.75 per Share, net to you in cash…</p>
<p><b>When does the Offer expire?</b></p>
<p>The Offer expires at 12:00 midnight, New York City time,
on February 19, 2020…</p>
<a name="intro"><b>INTRODUCTION</b></a>
<p>…</p>
</body></html>
</TEXT>
</DOCUMENT>
```

**Download manifest excerpt:**

```json
{
  "event_id": "005-88347",
  "docs": [
    {
      "role": "otp",
      "filename": "d859616dex99a1a.htm",
      "url": "https://www.sec.gov/Archives/edgar/data/…/d859616dex99a1a.htm",
      "status": "ok",
      "bytes": 412000,
      "sha1": "abc123…"
    }
  ]
}
```

Idempotent: re-run with matching sha1 → `status: skipped`.

---

## 3. `cleanup` → `clean/*.txt` + `*.meta.json`

**In:** raw HTML  
**Out:** SEC wrapper stripped; plain text + metadata  
**Not:** field extraction

`clean/0001193125-20-011457__d859616dex99a1a.htm.txt` (abbreviated):

```text
TABLE OF CONTENTS
SUMMARY TERM SHEET
INTRODUCTION
…
Who is offering to buy my shares?
Eli Lilly and Company, through its subsidiary, is offering to purchase
all outstanding shares of Dermira, Inc.

How much are they offering to pay?
We are offering to pay $18.75 per Share, net to you in cash…

When does the Offer expire?
The Offer expires at 12:00 midnight, New York City time,
on February 19, 2020…
```

`*.meta.json`:

```json
{
  "doc_role": "otp",
  "source_hit_id": "hit-otp-001",
  "accession": "0001193125-20-011457",
  "sha1": "abc123…",
  "words": 48000,
  "bytes": 390000
}
```

`doc_role` comes from EDGAR metadata / inventory role, not body keyword search.

---

## 4. `segment` → `segments.json`

**In:** clean text + raw HTML (for TOC / FAQ DOM)  
**Out:** chunks only — **no field IE**

### How segments are found (DOM)

| Doc role | Method |
|----------|--------|
| **OTP** | TOC named anchors → section spans; bold/`<strong>` text ending in `?` → FAQ Q/A |
| **Cover / LoT / 14D9** | Usually one `full_doc` chunk |
| **No TOC** | Large clean-text windows (GLiNER length limit) |

**TOC algorithm (BeautifulSoup on raw HTML):**

1. Collect section anchors (`a[name]` / `a[id]`, or TOC `a[href^="#"]` targets).
2. Order by document position.
3. Text between `anchor_i` and `anchor_{i+1}` → one `toc_section`.

**FAQ algorithm (structure only):**

1. Find bold/strong nodes whose text ends with `?`.
2. Following sibling block(s) until next question → answer text.
3. Emit `kind: faq` — do **not** map question words to BNY fields.

**Fallback ladder:** TOC sections → else FAQ-only → else `full_doc` chunks.

### Example `segments.json`

```json
{
  "event_id": "005-88347",
  "segments": [
    {
      "segment_id": "otp:section:sts",
      "doc_role": "otp",
      "kind": "toc_section",
      "heading": "SUMMARY TERM SHEET",
      "text": "Who is offering… February 19, 2020…"
    },
    {
      "segment_id": "otp:faq:0",
      "doc_role": "otp",
      "kind": "faq",
      "question": "Who is offering to buy my shares?",
      "text": "Eli Lilly and Company, through its subsidiary, is offering to purchase all outstanding shares of Dermira, Inc."
    },
    {
      "segment_id": "otp:faq:1",
      "doc_role": "otp",
      "kind": "faq",
      "question": "How much are they offering to pay?",
      "text": "We are offering to pay $18.75 per Share, net to you in cash…"
    },
    {
      "segment_id": "otp:faq:2",
      "doc_role": "otp",
      "kind": "faq",
      "question": "When does the Offer expire?",
      "text": "The Offer expires at 12:00 midnight, New York City time, on February 19, 2020…"
    },
    {
      "segment_id": "otp:section:intro",
      "doc_role": "otp",
      "kind": "toc_section",
      "heading": "INTRODUCTION",
      "text": "…"
    },
    {
      "segment_id": "cover:full",
      "doc_role": "cover",
      "kind": "full_doc",
      "text": "SCHEDULE TO … Dermira, Inc. …"
    },
    {
      "segment_id": "sc_14d9:full",
      "doc_role": "sc_14d9",
      "kind": "full_doc",
      "text": "SCHEDULE 14D-9 …"
    }
  ]
}
```

---

## 5. `gliner` → `spans.json`

**In:** `segments.json`  
**Out:** zero-shot labeled spans only (`method` = gliner)  
**Forbidden:** regex / gazetteer field discovery

Labels requested (example set):  
`offeror`, `target`, `purchaser`, `security`, `cusip`, `isin`, `ticker`,  
`offer_price`, `expiration_date`, `withdrawal_deadline`, `effective_date`,  
`settlement_date`, `minimum_tender_condition`, `proration_terms`,  
`available_option`, `currency`

```json
{
  "event_id": "005-88347",
  "gliner_model": "urchade/gliner_large-v2.1",
  "spans": [
    {
      "segment_id": "otp:faq:0",
      "label": "offeror",
      "text": "Eli Lilly and Company",
      "score": 0.86,
      "start": 0,
      "end": 21,
      "passage": "Eli Lilly and Company, through its subsidiary, is offering to purchase all outstanding shares of Dermira, Inc."
    },
    {
      "segment_id": "otp:faq:0",
      "label": "target",
      "text": "Dermira, Inc.",
      "score": 0.84,
      "start": 95,
      "end": 108,
      "passage": "…outstanding shares of Dermira, Inc."
    },
    {
      "segment_id": "otp:faq:1",
      "label": "offer_price",
      "text": "$18.75",
      "score": 0.91,
      "start": 24,
      "end": 30,
      "passage": "We are offering to pay $18.75 per Share, net to you in cash…"
    },
    {
      "segment_id": "otp:faq:2",
      "label": "expiration_date",
      "text": "February 19, 2020",
      "score": 0.88,
      "start": 62,
      "end": 78,
      "passage": "The Offer expires at 12:00 midnight, New York City time, on February 19, 2020…"
    }
  ]
}
```

If model weights are unavailable: empty spans + `gliner_unavailable` — **no regex fallback**.

---

## 6. `assemble` → `concise/event_rep.json`

**In:** inventory + clean meta + segments + spans  
**Out:** Concise Rep (handoff object for Multi-Agent / DB load)

```json
{
  "schema_version": "1",
  "event_id": "005-88347",
  "mvp_event_type": "tender_offer",
  "cohort": "gold",
  "preprocess_status": "ok",
  "nlp_versions": {
    "pipeline": "to_preprocess_gliner",
    "gliner_model": "urchade/gliner_large-v2.1"
  },
  "doc_inventory": [
    {"role": "cover", "status": "ok", "sha1": "…"},
    {"role": "otp", "status": "ok", "sha1": "abc123…"},
    {"role": "sc_14d9", "status": "ok", "sha1": "…"}
  ],
  "entities": [
    {
      "label": "offeror",
      "text": "Eli Lilly and Company",
      "score": 0.86,
      "doc_role": "otp",
      "segment_id": "otp:faq:0",
      "faq_question": "Who is offering to buy my shares?"
    },
    {
      "label": "target",
      "text": "Dermira, Inc.",
      "score": 0.84,
      "doc_role": "otp",
      "segment_id": "otp:faq:0"
    }
  ],
  "candidate_facts": [
    {
      "field_hint": "offer_price",
      "raw": "$18.75",
      "passage": "We are offering to pay $18.75 per Share, net to you in cash…",
      "method": "gliner",
      "confidence": 0.91,
      "doc_role": "otp",
      "section": "SUMMARY TERM SHEET",
      "faq_question": "How much are they offering to pay?",
      "char_span": [24, 30],
      "source_hit_id": "hit-otp-001",
      "source_accession": "0001193125-20-011457"
    },
    {
      "field_hint": "expiration_date",
      "raw": "February 19, 2020",
      "passage": "The Offer expires at 12:00 midnight, New York City time, on February 19, 2020…",
      "method": "gliner",
      "confidence": 0.88,
      "doc_role": "otp",
      "faq_question": "When does the Offer expire?",
      "char_span": [62, 78]
    }
  ],
  "exception_flags": []
}
```

These are **candidates**, not final BNY `event_field_values`.

---

## 7. `load_db` → path-specific Postgres tables

**In:** `event_rep.json`  
**Out:** tender Concise Rep tables (other paths get their own table families)

| Table | Example |
|-------|---------|
| `tender_concise_reps` | `event_id=005-88347`, `schema_version=1`, `preprocess_status=ok`, `gliner_model=…` |
| `tender_concise_docs` | cover / otp / sc_14d9 rows with sha1, role, download status |
| `tender_concise_segments` | toc_section + faq rows (optional persistence) |
| `tender_concise_entities` | `offeror` / `target` spans |
| `tender_concise_facts` | `field_hint=offer_price`, `raw_text=$18.75`, `method=gliner`, `confidence=0.91` |

Stub paths (`exchange_*`, `rights_*`, `merger_*`, `conversion_*`) write header-only rows with `preprocess_status='stub_not_implemented'`.

Later Multi-Agent reads `{path}_concise_facts` → writes shared `event_field_values`.

---

## Mental model

| Stage | Transforms |
|-------|------------|
| inventory | catalog → which docs matter + cohort |
| download | URLs → raw HTML bytes |
| cleanup | HTML wrapper → clean text + meta |
| segment | clean/HTML DOM → TOC/FAQ chunks |
| gliner | chunks → labeled spans + scores |
| assemble | all artifacts → Concise Rep JSON |
| load_db | Concise Rep → path-specific tables |

## Visual QA (planned)

After each stage (or via `--viz-only`), generate:

- **PNGs** under `figures/preprocess/` — cohort mix, download status, segment rates, GLiNER label bars, pipeline funnel  
- **HTML inspect pages** under `outputs/preprocess_inspect/{event_id}/` — doc tables, clean-text preview, segment gallery, **GLiNER span highlights**, Concise Rep / DB fact tables  

See the preprocess plan section **Stage visualizations (visual QA)** for the full chart + inspect matrix.

---

## Explicitly out of this example

- Multi-Agent field resolution / conflict handling  
- Versioned BNY notification drafts  
- Update History / amendment diff UI  
- Full EO / RI / Merger / Conversion NLP (stubs only)
