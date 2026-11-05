# Vendor reconciliation (synthetic prototype)

Compares vendor tender-offer data with terms extracted from SEC filings and flags mismatches,
with filing evidence, for human review. **Vendor data here is synthetic**, generated from
`notebooks/evaluation/tender_offers.csv`; it tests the adapter and comparison logic, not extraction accuracy.

```bash
python vendor_reconciliation/generate_vendor_data.py --seed 7   # writes synthetic/
python vendor_reconciliation/reconcile.py                       # writes mismatches.csv + evaluation_summary.json
```

| File | Role |
|------|------|
| `filing_side.py` | Loads filing-extracted terms; one record per real offer (grouped by issuer + CUSIP + announce date, because the dataset's `event_id` is accession-based) |
| `adapters.py` | Single adapter layer: vendor A (CSV) and vendor B (JSONL, UTC timestamps) → common record |
| `generate_vendor_data.py` | Builds two vendor feeds with labeled injected errors (`answer_key.csv`) |
| `reconcile.py` | Matches vendor and filing records, compares price / expiration / CUSIP, writes tickets, scores against the answer key |

Injected errors: wrong price, stale price after an amendment, wrong expiration, stale extension, transposed CUSIP, missing values.
Benign differences that must **not** be flagged: name variants, number formats, `dd-Mon-YYYY` vs UTC timestamps.
Price is compared only where the filing has a numeric price (many issuer tenders price at net asset value).
