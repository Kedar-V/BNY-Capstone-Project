# Notification field schema (SEC-public only)

| Field | Value |
|-------|--------|
| **Status** | Active — capstone target schema |
| **Source of truth for field list** | Derived from [`DBSchema.pdf`](DBSchema.pdf), **restricted to public SEC** |
| **Upstream** | Concise Rep (`tender_concise_*` / `event_rep.json`) |
| **Downstream** | LLM agent → `event_field_values` + optional `notification_drafts.payload_json` |
| **Explicitly unavailable** | BNY internal systems, client email headers, account/position ledgers |

---

## 1. Scope

We only have **public SEC EDGAR** filings (Schedule TO, Offer to Purchase, LoT, 14D-9, amendments, etc.).

Therefore:

- Schema fields that require **BNY email, BaNCS, DTC location, client accounts, or positions** are **out of scope**.
- Agents must return **`null`** for those fields — never invent them.
- The useful product for this project is a **public-document-backed corporate-action notification draft**, not a byte-identical BNY email.

```text
SEC filings
  → preprocess Concise Rep (GLiNER candidates + evidence)
  → LLM agent (select / normalize / map)
  → this schema (public fields filled; internal fields null)
  → Postgres event_field_values / notification_drafts
```

---

## 2. Field classes

| Class | Meaning | Agent behavior |
|-------|---------|----------------|
| **A — public extractable** | Usually present in OTP / cover / 14D9 | Fill from Concise Rep (+ segments if needed); cite evidence |
| **B — public derived** | Not a literal span; inferable from forms/docs | Derive with rule or LLM; record method `derived` |
| **C — out of scope (SEC-only)** | Needs BNY internal / email | Always `null`; do not prompt the model to guess |

---

## 3. In-scope fields (fill when evidence exists)

### 3.1 Event identity & classification

| Field | Class | SEC basis | Notes |
|-------|-------|-----------|-------|
| `event_id` | B | SEC `file_num` | Already on Concise Rep / `events` |
| `notification_family` | B | — | Default `"Corporate Action Notification"` for this MVP (not Income) |
| `corporate_action_type` | B | Form family / MVP type | e.g. map `tender_offer` → `TENDER OFFER` (or keep `tender_offer`); be consistent |
| `event_subtype` | A/B | OTP / cover narrative | e.g. third-party vs issuer self-tender; cash tender |
| `mandatory_voluntary_indicator` | A/B | OTP terms | Tenders are typically voluntary; confirm from text when possible |
| `income_type` | C* | — | `null` unless we later add income events (`*` = N/A for TO MVP) |

### 3.2 Security

| Field | Class | Concise Rep hints / sources |
|-------|-------|-----------------------------|
| `security_description` | A | `security_description`, cover issuer name |
| `cusip` | A | `cusip` |
| `isin` | A | `isin` (often sparse in TO HTML) |
| `ticker` | A | `ticker` |
| `currency` | A | `currency` |
| `coupon_rate` | A | Debt/CA only; usually `null` for equity tender |
| `maturity_date` | A | Debt only; usually `null` for equity tender |

### 3.3 Parties (extension vs PDF — useful for TO)

Not all appear as named keys in the PDF JSON, but they are public and valuable. Store in `event_field_values` (and optionally nest under payload).

| Field | Class | Concise Rep hints |
|-------|-------|-------------------|
| `offeror` | A | `offeror`, `purchaser` |
| `target` | A | `target` |
| `purchaser` | A | `purchaser` |

### 3.4 Consideration & key dates (tender-oriented mapping)

| Field | Class | Concise Rep / mapping |
|-------|-------|------------------------|
| `cash_amount` | A | Prefer normalized `offer_price` (e.g. `18.75`); keep currency in `currency` |
| `offer_price` | A | Keep raw candidate too if useful; or store only normalized in `cash_amount` |
| `effective_date` | A | `effective_date` |
| `expiration_date` | A | `expiration_date` (OTP “Offer expire”) |
| `withdrawal_deadline` | A | If labeled / present in spans |
| `settlement_date` | A | `settlement_date` when present |
| `payment_date` | A | Often `null` for open tenders |
| `record_date` | A | Often `null` for third-party tenders |
| `ex_date` | A | Usually `null` for TO |

### 3.5 Elections / options (when disclosed in OTP)

| Field | Class | Notes |
|-------|-------|-------|
| `election_required` | A/B | Often false/default for simple cash tender; true if options disclosed |
| `available_options` | A | List; from `available_option` spans + section text |
| `default_option` | A | `null` if not stated |
| `election_deadline` | A | May equal or relate to `expiration_date` — only set if text supports it |
| `response_deadline` | A | Consent-like; often `null` for cash TO |
| `proration_terms` | A | Narrative; store as text if found |
| `minimum_tender_condition` | A | Condition text / flag if found |

### 3.6 Notification lifecycle (public-only interpretation)

| Field | Class | Rule under SEC-only |
|-------|-------|---------------------|
| `notification_type` | B | Default `ANNOUNCEMENT` for initial public package; amendments may be modeled as updates on same `event_id` |
| `notification_status` | B | From amendment activity: e.g. active / amended — **not** BNY REPLACEMENT codes unless we define a public mapping |
| `cancellation_reason` | A | Only if a withdrawal/cancel filing text supports it; else `null` |

---

## 4. Out-of-scope fields (always `null`)

These come from [`DBSchema.pdf`](DBSchema.pdf) but **cannot** be populated from SEC alone.

### 4.1 Email / BNY messaging

`message_id`, `bny_location`, `sender`, `recipient`, `email_date`, `email_subject`, `preparation_date`

### 4.2 BNY processing codes (as used in production email)

Production values for `processing_status` such as “Confirmed and Complete” — **null** unless we define a separate public proxy (prefer null).

### 4.3 Account & position

`account_number`, `account_name`, `eligible_quantity`, `position_quantity`, `principal_amount`, `interest_amount`, `debit_credit_indicator`

### 4.4 Reminder / ack workflow

`reminder_number`, acknowledgment-only statuses tied to client response flows

### 4.5 Wrong event family for current TO MVP (null unless corpus expands)

`old_security_*`, `new_security_*`, `conversion_ratio`, `conversion_price`, `redemption_amount`, `call_price`, `income_type` (Income Notification path)

---

## 5. Canonical agent output JSON

Use this shape for `notification_drafts.payload_json` and as the agent contract.
Internal keys are present for compatibility with the PDF, but must be null.

```json
{
  "schema_version": "sec_public_v1",
  "notification_family": "Corporate Action Notification",
  "event_id": "005-02933",
  "corporate_action_type": "tender_offer",
  "event_subtype": null,
  "mandatory_voluntary_indicator": "Voluntary",
  "notification_type": "ANNOUNCEMENT",
  "notification_status": null,
  "processing_status": null,

  "security_description": null,
  "isin": null,
  "cusip": null,
  "ticker": null,
  "currency": null,
  "coupon_rate": null,
  "maturity_date": null,

  "offeror": null,
  "target": null,
  "purchaser": null,

  "cash_amount": null,
  "offer_price_raw": null,
  "effective_date": null,
  "expiration_date": null,
  "withdrawal_deadline": null,
  "record_date": null,
  "ex_date": null,
  "payment_date": null,
  "settlement_date": null,

  "election_required": null,
  "available_options": [],
  "default_option": null,
  "election_deadline": null,
  "response_deadline": null,
  "minimum_tender_condition": null,
  "proration_terms": null,
  "cancellation_reason": null,

  "message_id": null,
  "bny_location": null,
  "sender": null,
  "recipient": null,
  "email_date": null,
  "email_subject": null,
  "preparation_date": null,
  "account_number": null,
  "account_name": null,
  "eligible_quantity": null,
  "position_quantity": null,
  "principal_amount": null,
  "interest_amount": null,
  "debit_credit_indicator": null,
  "reminder_number": null,
  "income_type": null,

  "evidence": {
    "cash_amount": {
      "raw": "$18.75",
      "passage": "…",
      "confidence": 0.91,
      "source_accession": "…",
      "doc_role": "otp",
      "method": "llm_from_gliner"
    }
  }
}
```

List fields: use `[]` only for `available_options` when unknown/empty. All other missing values: **`null`**.

---

## 6. Concise Rep → schema mapping

| Concise `field_hint` / signal | Schema field | Agent job |
|-------------------------------|--------------|-----------|
| `offer_price` | `cash_amount` (+ optional `offer_price_raw`) | Pick best span; parse number; set `currency` if known |
| `currency` | `currency` | Normalize (`USD`) |
| `cusip` / `isin` / `ticker` | same | Prefer high-score, CUSIP-like 9-char, etc. |
| `security_description` | `security_description` | Prefer issuer legal name over boilerplate |
| `offeror` / `purchaser` / `target` | same | Deduplicate; prefer OTP Summary / cover |
| `expiration_date` | `expiration_date` | Normalize `YYYY-MM-DD` when possible |
| `withdrawal_deadline` | `withdrawal_deadline` | Same |
| `effective_date` / `settlement_date` | same | Same |
| `available_option` | `available_options[]` | Aggregate unique options |
| `minimum_tender_condition` / `proration_terms` | same | Keep short text |
| `mvp_event_type` | `corporate_action_type` | Map enum |
| doc roles / amendments | `notification_type` / status | Conservative public labels only |

If Concise Rep has **no** usable candidate and segment lookup also fails → **`null`** (do not hallucinate).

---

## 7. Postgres landing (unchanged tables)

No new “BNY email” tables. Use existing store:

| Table | Role under SEC-only schema |
|-------|----------------------------|
| `schema_fields` | Catalog; mark `source_class` = public vs `bny_internal_only` |
| `events` / `documents` / `event_versions` | Catalog + timeline |
| `tender_concise_*` | Agent **input** (candidates) |
| `event_field_values` | Agent **output** (one row per field, with `source_quote`, `confidence`, `extraction_method='llm'`) |
| `notification_drafts.payload_json` | Full JSON in §5 for demos |

Internal PDF fields may still exist in `schema_fields` for documentation, but seeded placeholders should remain `null` / `placeholder` and **must not** be filled by the SEC agent.

---

## 8. Handling rules (SEC-only)

1. **Evidence first** — every non-null public field needs a passage or explicit derived rule.  
2. **Null over guess** — especially CUSIP/ISIN/dates.  
3. **Normalize** dates to `YYYY-MM-DD` when confident; else keep raw in `value_text` and put ISO in `value_normalized` only when sure.  
4. **Money** — numeric in `value_normalized` / `cash_amount`; currency separate.  
5. **Do not** fabricate `message_id`, accounts, or BNY location.  
6. **Amendments** — same `event_id`; new `event_versions` row; update current field values; do not invent BNY cancellation email codes without text support.  
7. **Income Notification** path — out of scope until income SEC corpus exists.

---

## 9. Success bar (capstone)

For a gold tender event, agent output should typically populate:

- `event_id`, `notification_family`, `corporate_action_type`
- `security_description`, `ticker` and/or `cusip`
- `offeror` and/or `target`
- `cash_amount` + `currency` (when OTP states price)
- `expiration_date` (when OTP states it)

…and leave §4 fields **null**, with evidence attached for each filled field.

---

## 10. References

- Origin field list: [`docs/DBSchema.pdf`](DBSchema.pdf)  
- Preprocess I/O: [`docs/preprocess-stage-io-example.md`](preprocess-stage-io-example.md)  
- Preprocess LLD: [`docs/lld-preprocess-pipeline.md`](lld-preprocess-pipeline.md)  
- Physical DDL: [`db/schema.sql`](../db/schema.sql) · [`db/README.md`](../db/README.md)
