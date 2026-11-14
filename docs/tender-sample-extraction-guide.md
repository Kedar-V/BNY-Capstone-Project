# Tender Offer Samples: Structure, Linkage & Extraction Guide

| Field | Value |
|-------|--------|
| **Status** | Working guide (from local sample corpus analysis) |
| **Audience** | Engineers building tender-offer extraction / preprocess |
| **Scope** | How SEC tender docs relate, how we process one deal, what structure exists in samples, and where GLiNER fits |
| **Sample root** | `data/samples/` (local; gitignored) |
| **Related code** | `dataloader/download_samples.py`, `src/preprocess/paths/tender.py`, `scripts/run_preprocess.py` |
| **Eval harness** | [`docs/action-pack-unified-extract.md`](action-pack-unified-extract.md) — ActionPack unified extract, Orin oneshot, clause retrieve, DTO/LangGraph design |

This document is **self-contained**. It does not require prior chat context.

---

## 1. Purpose

We keep a diverse local sample set of tender-related SEC filings to:

1. Learn recurring document structure usable for routing / extraction.
2. Prototype field extraction (structure first, then span models).
3. Align with the production tender preprocess path (inventory → concise rep).

**Default sample size:** ~30 PDFs + matching HTML per folder (8-K exhibits may differ).

**Formats:** EDGAR usually ships these as HTML. PDFs in `data/samples/` are Chrome headless prints of that HTML (not native SEC PDFs).

---

## 2. Sample folder inventory

```text
data/samples/
  manifest.csv                 # accession, form, entity, paths, status
  structure_analysis.csv       # per-doc cue / size metrics (if regenerated)
  schedule_to/                 # Schedule TO covers (TO-T + TO-I mix)
  to_t/                        # SC TO-T primary covers
  to_i/                        # SC TO-I primary covers
  14d9/                        # SC 14D9 (target recommendation)
  amendments/                  # SC TO-T/A, SC TO-I/A, SC 14D9/A mix
  offer_to_purchase/           # EX-99 “Offer to Purchase” exhibits
  8k/                          # Form 8-K (conversion / CA signal track)
  8k_exhibits/                 # EX-* attached to those 8-Ks
```

Each typed folder typically has:

- `*.pdf` at the folder root (for human reading)
- `html/*.htm` (for machine parsing — prefer this for extraction)

EFTS / EDGAR form labels used in metadata:

| Friendly name | EDGAR / EFTS label |
|---------------|--------------------|
| Schedule TO (third-party) | `SC TO-T` |
| Schedule TO (issuer) | `SC TO-I` |
| Amendment | `SC TO-T/A`, `SC TO-I/A`, `SC 14D9/A` |
| Target recommendation | `SC 14D9` (not `SC 14D-9`) |
| Offer to Purchase | Exhibit under a TO filing (often `EX-99.(A)(1)(A)`, description contains “OFFER TO PURCHASE”) |
| Current report | `8-K` |

Diversity targets when downloading samples: years 2020–2025, distinct entities, and for mixed folders an intentional form subtype split (e.g. amendments = 10 TO-T/A + 10 TO-I/A + 10 14D9/A).

---

## 3. How these documents interact on one tender

They are **roles in one deal package**, not six independent corpora.

### 3.1 Who files what

| Piece | What it is | Typical filer |
|-------|------------|---------------|
| **Schedule TO** | Umbrella tender schedule | Bidder or issuer |
| **TO-T** | Third-party tender (buyer for target shares) | Bidder |
| **TO-I** | Issuer self-tender | Issuer |
| **Offer to Purchase (OTP)** | Long narrative exhibit *inside* the TO accession | Same as the TO |
| **14D-9** | Target board solicitation / recommendation | **Target** (third-party deals) |
| **Amendments (`/A`)** | Updates to a prior TO or 14D-9 | Same party as the original |
| **8-K (+ exhibits)** | Current report / contracts — parallel track, not the TO body | Issuer |

**TO-T and TO-I are mutually exclusive flavors** of Schedule TO for a given offer.

### 3.2 Linkage model

```text
Third-party cash tender (preferred MVP path)
────────────────────────────────────────────
Bidder files SC TO-T  ──covers / attaches──►  Offer to Purchase (+ Letter of Transmittal, …)
                                                      │
                                                      │  same subject company / SEC file number
                                                      ▼
Target files SC 14D9  (recommend / remain neutral / reject)
                                                      │
Over time either side files /A                        ▼
SC TO-T/A , SC 14D9/A  (extend deadline, change price, new exhibits)


Issuer self-tender
──────────────────
Issuer files SC TO-I + OTP (+ /A as needed)
14D-9 usually absent (no separate “target” responding to itself)
```

**Four interaction types:**

1. **Containment** — OTP lives inside a TO accession (same filing, different document role: `cover` vs `otp`).
2. **Cross-filing join** — TO-T and 14D-9 are different accessions, joined by subject company / `primary_file_num` → one `event_id`.
3. **Version chain** — `/A` updates the prior filing in that series; many important changes live in the **delta**.
4. **Field complementarity** — TO/OTP carry offer mechanics; 14D-9 carries board stance / fairness / background.

In this repo’s corpus, third-party file numbers often co-occur as `(TO-T, 14D9)`; issuer file numbers often stand alone as `(TO-I,)`.

---

## 4. How we process files for a given tender offer

Unit of work = one **event** (typically SEC `primary_file_num`), not one PDF.

### 4.1 Bind the deal

From `data/processed/documents.parquet` / `events.parquet`, group rows sharing the event key. That pulls TO, OTP exhibits, 14D-9, and amendments for the subject company.

### 4.2 Pick priority docs (inventory roles)

Do **not** ingest every exhibit. Classify and keep:

| Role | Source |
|------|--------|
| `cover` | SC TO-T or SC TO-I primary form doc |
| `otp` | Exhibit whose description/type matches Offer to Purchase (or inferred EX-99.(A)(1)*) |
| `sc_14d9` | SC 14D9 primary (third-party) |
| `lot` | Letter of Transmittal (optional) |

Implemented in `src/preprocess/paths/tender.py` → `select_priority_docs`.

**Cohorts:**

| Cohort | Meaning |
|--------|---------|
| `gold` | cover + OTP + 14D-9 |
| `needs_otp_resolve` | cover + 14D-9, OTP missing |
| `incomplete` | otherwise |

`download_ready` ≈ cover + OTP present.

v1 prefers **initial (non-amendment)** docs per role; amendments are counted for later version/history work.

### 4.3 Pipeline stages

```text
inventory → download → cleanup → segment → gliner → assemble → load_db
```

| Stage | Output idea |
|-------|-------------|
| inventory | `inventory.json` — roles + cohort |
| download | `raw/` HTML bytes |
| cleanup | `clean/` text |
| segment | `segments.json` (structure/windows) |
| gliner | `spans.json` candidate values |
| assemble | `concise/event_rep.json` |
| load_db | path-specific Concise Rep tables |

Artifacts: `data/preprocess/tender/events/{event_id}/`.

CLI: `python scripts/run_preprocess.py --path tender …`  
Sample playground: `preprocess/run_gliner_on_samples.ipynb`.

### 4.4 Practical read / extract order

1. TO **cover** — parties, CUSIP, skeleton, exhibit pointers  
2. **OTP** — primary terms (price, expiration, procedures, conditions)  
3. **14D-9** (if TO-T) — recommendation / fairness  
4. **`/A` filings** — what changed (extensions, price, exhibits)

Issuer TO-I: same flow without requiring 14D-9.

---

## 5. Structure observed in the sample set

Analysis method: HTML under `data/samples/*/html/`, cue/heading/Item scans → optional `data/samples/structure_analysis.csv`.

Approximate size / Item density (medians from one full pass):

| Folder | Median words | TOC present | Unique “Item” mentions (median) |
|--------|-------------:|------------:|--------------------------------:|
| schedule_to | ~1.8k | ~0% | ~12 |
| to_t | ~1.8k | ~0% | ~12 |
| to_i | ~2.0k | ~3% | ~13 |
| offer_to_purchase | ~16k | ~67% | ~0 (uses numbered narrative sections) |
| 14d9 | ~35k | ~60% | ~10 |
| amendments | ~1.0k | ~3% | ~1 |
| 8k | ~1.2k | ~0% | ~3 |
| 8k_exhibits | ~3.6k | ~10% | ~0 |

### 5.1 Schedule TO covers (`schedule_to`, `to_t`, `to_i`)

**Shape:** Fixed SEC Schedule TO Item skeleton (Summary Term Sheet through Exhibits). Headings repeatedly include `SCHEDULE TO`, `Item 1` … `Item 12`, filing-fee tables.

**Important:** Many covers are **thin shells**. A large share:

- are under ~2.5k words, and  
- **incorporate the Offer to Purchase by reference**.

**Exploit for:** parties, CUSIP (~97–100% cue hit), form identity, exhibit list.  
**Do not expect:** full offer narrative, reliable clock-time expiration.

### 5.2 Offer to Purchase (`offer_to_purchase`)

**Shape:** Narrative booklet with recurring titles, often TOC:

- Summary Term Sheet  
- Introduction / The Offer  
- Purpose of the Offer  
- Terms of the Offer  
- Acceptance / payment / proration  
- Procedures for tendering  
- Withdrawal rights  
- Conditions  

Cue prevalence in samples (approx.): offer price ~97%, expiration ~97%, withdrawal ~93%, conditions ~80%, procedures ~60%.

**Exploit for:** **primary field extraction** (price, deadlines, how-to-tender, proration, conditions).  
**Note:** Little rigid “Item N” numbering — route by **section title / TOC**, not Schedule TO Item IDs.

### 5.3 Schedule 14D-9 (`14d9`)

**Shape:** Rigid Items, e.g.:

- Item 1 — Subject Company Information  
- Item 2 — Identity and Background of Filing Person  
- Item 3 — Past Contacts / Transactions  
- Item 4 — The Solicitation or Recommendation (~97% cue)  
- Items 5–9 — persons retained, interest in securities, additional info, exhibits  

Often long; TOC common. Also echoes price/CUSIP; fairness opinion language in a majority of samples.

**Exploit for:** board recommendation stance, fairness/background. Secondary copy of offer terms.

### 5.4 Amendments (`amendments`)

**Shape:** Short delta filings. ~90% open with “This Amendment No…”. Typically patch a subset of Items (commonly **8 / 11 / 12** in sample openings).

**Exploit for:** **change detection** (extension, price change, new exhibits) via diff against prior version.  
**Not** a full restate of the offer — do not treat as standalone OTP replacement.

### 5.5 8-K and exhibits

**8-K:** Current Report structure; common Items in samples include **1.01** (material agreement) and **9.01** (exhibits). Good as an **event signal**, different schema from tender body fields.

**8-K exhibits:** Indentures, warrants, purchase agreements, etc. Low shared Item skeleton — weak for bulk IE without targeted clause rules.

---

## 6. Extraction exploitability summary

| Folder | Structure strength | Best extraction use | Weak use |
|--------|--------------------|---------------------|----------|
| OTP | Section/TOC, high field density | Price, expiration, procedures, conditions | Rigid Item anchors |
| 14D-9 | Strong Item skeleton | Recommendation (Item 4), fairness, background | Primary offer mechanics |
| TO covers | Strong Items, thin body | CUSIP, parties, exhibit pointers | Full terms (often by reference) |
| Amendments | Short, formulaic opener | Deltas / version history | Full-field extract |
| 8-K | Item 1.01 / 9.01 | Kickoff / agreement notice | Tender field schema |
| 8-K exhibits | Freeform legal | Rare clause hunt | GLiNER-first whole-doc |

**Recommended order for one deal:** cover → OTP → 14D-9 → `/A` diffs.

---

## 7. Is GLiNER relevant given this structure?

**Yes — as a value extractor on routed slices, not as the document navigator.**

### 7.1 Layered responsibility

| Layer | Owner | Why |
|-------|--------|-----|
| Which document | Inventory roles (`cover` / `otp` / `sc_14d9` / amendment) | Form + exhibit metadata |
| Which section | Item headers, OTP TOC/section titles | Stable across samples |
| Which string is the value | **GLiNER and/or regex** | Local span problem (`$X.XX`, dates, org names) |

Production path already approximates this: segment → GLiNER → `span_rank` with **doc-role bonuses** (e.g. boost CUSIP on cover; boost price/expiration on OTP). Labels live in `src/preprocess/contracts.py` (`GLINER_LABELS_TO`, etc.).

### 7.2 Where GLiNER still earns its keep

- OTP: section known, but exact price/date/CUSIP phrasing varies.  
- 14D-9 Item 4: “recommend / neutral / reject” wording varies.  
- Party and security names: messy entities.

### 7.3 Where GLiNER alone is weak / overkill

- Whole-doc GLiNER on thin TO covers for full tender fields (terms live in OTP).  
- Using GLiNER to *discover* “Item 4” (regex/TOC already finds structure).  
- Amendments: short deltas — prefer diff + targeted patterns.  
- 8-K exhibits: noisy without clause routing.

### 7.4 Design rule

```text
structure routing  →  window/segment  →  GLiNER (or regex)  →  rank/filter  →  concise rep
```

Do **not** replace structure with GLiNER; do **not** drop GLiNER for variable value strings inside the right window.

---

## 8. Operational pointers

```bash
# Build/refresh samples (needs documents.parquet)
python dataloader/download_samples.py
# optional: --n 30 --force

# Inspect
jupyter notebook dataloader/inspect_samples.ipynb
jupyter notebook preprocess/run_gliner_on_samples.ipynb

# Production tender path
python scripts/run_preprocess.py --path tender --cohort gold --limit 3
```

`data/` is gitignored. Regenerate samples and analysis locally; do not rely on them being in git.

Design / stage I/O details:

- [`docs/lld-preprocess-pipeline.md`](lld-preprocess-pipeline.md)  
- [`docs/preprocess-stage-io-example.md`](preprocess-stage-io-example.md)

---

## 9. One-page cheat sheet

| Question | Answer |
|----------|--------|
| What is one “tender”? | Event keyed by SEC file number / subject company |
| Where are the terms? | **Offer to Purchase** (not the thin TO cover) |
| Where is the board stance? | **14D-9 Item 4** (TO-T deals) |
| Where do changes show up? | **`/A` amendments** (often Items 8/11/12) |
| TO-T vs TO-I? | Third-party vs issuer self-tender |
| Process which files? | cover + otp (+ 14d9 if gold); amendments as version pass |
| GLiNER? | Yes, on routed sections after structure |
| Prefer HTML or PDF for IE? | **HTML** (`html/`); PDF is for humans |

---

*End of guide.*
