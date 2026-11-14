# Event linking: what changed in the tender offer and merger extraction

Event linking groups SEC filings that belong to one corporate action (an offer, its amendments, the target's response, a merger's registration and proxy) into one event with versions. In production we will not keep the filing documents, so every value linking needs is now captured **when a filing is extracted**, while its text is in memory.

This page lists what was added to `load_tender_filings.ipynb` and `load_merger_filings.ipynb`, including **changes to both extraction prompts**.

## Summary

| Area | Change |
|---|---|
| New module | `linking_fields.py`: fills the linking columns from SEC metadata and the filing text (no LLM) |
| New module | `issuer_info.py`: issuer's country of incorporation from the SEC company record (used for ISINs) |
| Tender prompt | **6 new fields**; field counts changed from 27 to 33 (34 keys with `passage`) |
| Merger prompt | **5 new fields**; field counts changed from thirteen to eighteen (nineteen keys with `passages`) |
| Tender CUSIP/ISIN rules | CUSIP pattern tightened; ISINs derived only where valid; two new columns |
| Both notebooks | Linking columns are added automatically each time extraction saves its results |
| `tender_offers.csv` | The always-empty `passages` column was removed (`passage` holds the evidence) |

## 1. Columns filled by code (no LLM)

Added to both tables by `add_linking_fields()` in `linking_fields.py`.

| Column | Source | What it is | Why linking needs it |
|---|---|---|---|
| `filer_ciks` | SEC search metadata (`selected_filings.csv`) | every company's CIK on the filing (JSON list) | links filings from different companies in one deal; the table previously kept one registrant |
| `filer_names` | SEC search metadata | those companies' names (JSON list) | review and display |
| `file_numbers` | SEC search metadata | every SEC file number on the filing (JSON list) | same-program links (`005-` tender offers, `333-` registrations) |
| `is_amendment` | SEC search metadata, else the form ends in "/A" | true or false | version order |
| `amendment_number` | rule: "Amendment No. 3" near the cover | number | version order |
| `amends_filing_date` | rule: "originally filed … on December 1, 2025" or "Schedule TO filed … with the U.S. Securities and Exchange Commission on …" | ISO date; left blank if the stated date is after the amendment itself (a typo in the filing) | finds the original an amendment belongs to, including originals filed before our data window |
| `referenced_file_numbers` | rule: file numbers in the text, other than the filing's own | JSON list | links filings that cite each other |
| `evidence_verified` | code | true when every evidence quote is found in the filing text | flags extractions to review |
| `evidence_unverified_fields` | code | fields whose quote was not found (JSON list) | shows which fields to check |
| `prompt_version` | code | short fingerprint of the prompt text | tells rows from different prompt versions apart |
| `extracted_at` | code | UTC time the filing was extracted | audit |

Notes:
- `prompt_version` and `extracted_at` are recorded for filings extracted from now on, so they appear once new rows exist.
- A quote "not found" means it was not found word for word. Some are reformatted or paraphrased rather than wrong, so review before drawing conclusions.
- In `tender_offers.csv`, `passage` is now stored as valid JSON. In `mergers.csv`, `passages` already was.

## 2. Prompt changes

### Tender prompt (`PROMPT` in `load_tender_filings.ipynb`)

New "LINKING FIELDS" section, keys 28–33 (`passage` moved to 34). Missing values use "N/A", as before.

| Field | What the model returns |
|---|---|
| `agreement_name` | the agreement the offer is made under (for example "Agreement and Plan of Merger"); "N/A" for an issuer tender offer with no such agreement |
| `agreement_date` | the date that agreement is "dated as of", M/D/YYYY |
| `offer_commencement_date` | the date the offer commenced, only when stated |
| `original_filing_date` | for an amendment, the date of the original filing it amends |
| `related_entities` | entities in a structural relationship, as "Name (relationship)" separated by " \| ": master fund, feeder fund, parent, merger subsidiary, co-registrant, affiliate |
| `security_identifiers` | per class: "Class: CUSIP; ISIN; ticker", separated by " \| ", copied exactly as printed |

All counts in the prompt (number of fields, keys inside `passage`, output keys) were updated to match.

### Merger prompt (`prompt` in `load_merger_filings.ipynb`)

New fields 14–18 (`passages` moved to 19). Missing values use null, as before.

| Field | What the model returns |
|---|---|
| `agreement_name` | the agreement the merger is made under (original name, not an amendment's) |
| `agreement_date` | the original agreement date, M/D/YYYY |
| `original_filing_date` | for an amended filing (S-4/A, SC 13E3/A), the date of the original |
| `related_entities` | parent, merger subsidiary, co-registrant, affiliate, master fund, feeder fund |
| `security_identifiers` | per class: "Class: CUSIP; ISIN; ticker" |

The "thirteen"/"fourteen" counts became "eighteen"/"nineteen", and both key lists include the new fields.

### Checks on the new prompt fields

Added by `linking_fields.py` when those columns are present:

| Column | Check |
|---|---|
| `security_identifiers_unverified` | CUSIPs or ISINs the model returned that are not printed in the filing (JSON list). CUSIPs copied with a space, such as "48255N 100", are compared without it |
| `original_filing_date_agrees` | whether the model's `original_filing_date` matches the rule's `amends_filing_date` |

### Rights issues

The rights prompt is not in this repository (it runs in the StackAI workflow). It needs `issuer`, `related_entities` and `security_identifiers` added there, in the same format.

## 3. Tender CUSIP and ISIN rules

- **CUSIP:** a match now needs at least one digit in its first six characters. This removes false matches such as "FEBRUARY 5".
- **ISIN:** an ISIN stated in the filing is kept. Otherwise it is derived only from a CUSIP that starts with a digit: "US" + CUSIP, or "CA" for a Canadian issuer. A CUSIP that starts with a letter (a CINS code, used for issuers outside the US and Canada) is never converted, because its ISIN uses the home country's own scheme.
- **New columns:** `isin_source` (`stated` or `derived_from_cusip`) and `issuer_country` (from the SEC company record, cached in `issuers.json` next to the run's data).
- **Known gap:** each record still carries every CUSIP in the filing, not only its own class's. `security_identifiers` from the new prompt is meant to fix this; compare it with `cusip` before relying on it.

## 4. How to run

**Code-filled columns:** nothing extra to run. During extraction, every save rebuilds the table with the linking columns, while the filing text is in memory. Set `SEC_USER_AGENT` first; the tender notebook calls the SEC company API once per issuer for `issuer_country`.

**Fill the new prompt fields:** these need a new extraction pass.
- Tender: the loop skips filings already logged as `ok` in `tender_offer_run_log.csv`, so remove those entries for the filings you want to re-extract.
- Merger: `START_FRESH = True` clears all results and re-runs every filing. Keep that in mind before running cell 24.

**Merger text:** only about 140 of the 562 merger filings have their text in this repository. The text-based columns (`amendment_number`, `amends_filing_date`, `referenced_file_numbers`, the quote check) fill completely only where the full text is loaded, which is the machine that ran the merger extraction.

## 5. Not changed yet

These renames were left out because other code reads the current names (`vendor_reconciliation/`, `agents/client_briefing/`, `corporate-actions-demo/scripts/`, `load_action_filings.py` and its tests):

- `event_id` → `filing_record_id` (today it is one per filing, `tender_offer_<accession>`, not a real event ID)
- `passage` (tender) and `passages` (merger) → one `evidence` column
- dropping `filing_id`, which duplicates `accession_number`

Still to do for linking: read each filing's EDGAR header to get `subject_cik` and `filed_by_ciks` (who is the subject and who filed), which the SEC search metadata does not label.
