# Creating the Evaluation Reference Dataset

## Goal and responsibilities

Create a reference dataset from approximately **1,000–2,000 SEC filings across five actions**, using **one LLM for now**. Outputs remain unverified until checked against the source. This task covers dataset creation; pipeline evaluation comes later.

- **Pranshul:** maintain the shared StackAI workflow, base prompt and model settings.
- **Aesha, Pranshul and Alex:** divide the actions, prepare inputs/prompts, run extraction and review results. Assignments are still pending.
- **Team:** combine the results using the same field names.

## 1. Load filings and text

Open [load_action_filings.ipynb](load_action_filings.ipynb), choose your action, filing dates and count, and run the cells. Forms and keywords are in [corporate_actions.json](corporate_actions.json).

Add `SEC_USER_AGENT` to your `.env` file using your name/project and real contact email:

```dotenv
SEC_USER_AGENT="Your Project your-contact@example.com"
```

No SEC API key or Chrome is needed. To run the script instead, use this from the repository root:

```bash
python notebooks/evaluation/load_action_filings.py --action exchange_offer --start 2023-07-01 --end 2023-08-31 --n 10
```

The loader downloads main documents and attached exhibits, cleans HTML and returns a pandas table. Use each row's `text` for the LLM. It reuses saved downloads and can read an existing filing list with `--metadata-path`. Supporting forms are included; conditional forms require `--include-conditional`.

Outputs are under `notebooks/evaluation/data/<action>_<start>_<end>/`:

- `documents/` and `documents.csv`: sources, metadata and download status.
- `input_text/`: combined text per filing.
- `filings.jsonl`: records with text; `filings.csv`: summary without text.
- `search_counts.csv`: search counts and limits reached.

**Check before extraction:** results are candidates, not confirmed action labels. Counts are filings, not unique events. Inspect partial/failed downloads and complex tables. PDFs/images are not converted to text, and references to documents in other filings are not followed automatically. Keep the exact input and note missing material; do not silently truncate long text.

## 2. Do an informal check

Try a few examples to check the prompt, JSON and evidence. Fix obvious issues, then save the prompt/schema version and model settings. Record later changes and rerun affected inputs where needed.

## 3. Call the LLM

Follow steps 4–8 of [Evaluation_LLM.ipynb](Evaluation_LLM.ipynb):

1. Set `API_URL` and `STACKAI_API_KEY` in your environment.
2. Adapt the tender prompt to your action's fields and interpretation rules.
3. Send filing text as `in-0` and the prompt as `in-1`.
4. Parse `outputs["out-0"]`, then attach accession number, filing date, and other general info outside the LLM call.

```python
out = query({"in-0": filing_text, "in-1": action_prompt})
records = parse_llm_json(out["outputs"]["out-0"])
```

The example returns six tender fields as strings, `"N/A"` for missing/unclear values and `[]` for no event. It does **not** yet request shared event fields or supporting quotations; add these to the agreed prompt for the reference dataset.

Save the original response, model ID/settings, run date and any errors. Record empty `[]` results too, so no-event inputs are not lost.

## 4. Check the output

Check JSON structure and required keys. Normalize dates and numbers while preserving original wording, units and qualifications. Convert `"N/A"` to `null` in final records, but do not interpret it as proof that a field is absent or not applicable.

Keep one review table: **source ID, field, model value, final value, evidence, review status and reviewer notes**. Flag missing evidence, uncertainty, conflicting passages and incomplete inputs.

## 5. Review against the source

Review flagged fields, prioritizing prices, ratios, deadlines, options and conditions. Also spot-check a random sample of other results. Record corrections, supporting passages, reviewer and a short reason.

Label each field:

- `model_extracted_unreviewed`: not yet checked by a person.
- `manually_reviewed`: checked against the source.
- `unresolved`: information remains unclear or unsupported.

Keep separate records for distinct events and separate snapshots for amendments. Link related records with an internal event ID; do not overwrite earlier terms.

## 6. Combine and save

Export one **JSONL dataset**, with an optional CSV summary. Include source metadata, action, extracted fields, evidence and review labels. Link to the original model responses and review table.

Check duplicate records, field consistency and source links. Save a version name and brief notes covering dates, counts by action/event, prompts/model used, exclusions and known gaps.

## Forms to use as a starting point

This is the project's working mapping, not an exhaustive SEC taxonomy. Confirm relevance from content and include exhibits containing actual terms. Preserve the API's actual form label.

| Corporate action | Primary SEC forms in project mapping | Supporting SEC forms in project mapping |
| --- | --- | --- |
| Tender offer | SC TO-T, SC TO-T/A, SC TO-I, SC TO-I/A | SC 14D9, SC 14D9/A |
| Exchange offer | SC TO-T, SC TO-T/A, SC TO-I, SC TO-I/A, S-4, S-4/A, F-4, F-4/A, 424B3 | SC 14D9, SC 14D9/A, SC TO-C, 425, 8-K, 6-K; conditional: SC 13E3, SC 13E3/A |
| Rights issue | 424B2, 424B3, 424B5, S-3, S-3ASR | 8-K, 424B4 |
| Merger | DEFM14A, PREM14A, S-4, S-4/A, SC 13E3, SC 13E3/A | 8-K, 425 |
| Conversion | 8-K, 424B2, 424B3, S-3, S-3ASR | 10-K, 10-Q |


## General event fields: shared across actions

Include these shared fields in final records, using `null` when unavailable. Extract event details with the LLM; attach source metadata and internal IDs separately.

| Group | Field | Meaning / population rule |
| --- | --- | --- |
| Classification and evidence | `event_id` | Internal event identifier linking related documents/amendments; assigned by the workflow, not invented by the LLM. |
| Classification and evidence | `corporate_action_type` | One of `tender_offer`, `exchange_offer`, `rights_issue`, `merger`, `conversion`; confirm from content and flag ambiguous cases. |
| Classification and evidence | `event_status` | Status supported by this source, such as announced, amended, completed, or withdrawn. Do not infer current status from later information. |
| Classification and evidence | `mandatory_voluntary_indicator` | Mandatory, voluntary, or mandatory with options, based on the notice. |
| Classification and evidence | `source_document`, `passages` | Workflow supplies document links/IDs; LLM supplies field-level supporting quotations and section/page/table locations when available. |
| Classification and evidence | `confidence`, `exception_flags` | Preserve any model confidence separately from review labels. Confidence is not a calibrated correctness probability. Workflow adds conflicting-evidence, missing-input, or review flags. |
| Entities and securities | `parties` | Role-labeled entities: issuer, target, acquirer, offeror, and other relevant parties. Do not assume the registrant's role. |
| Entities and securities | `security_description` | Description/class of the security affected. Use multiple entries when several securities are involved. |
| Entities and securities | `isin`, `cusip`, `ticker` | Security identifiers explicitly supported by the document; preserve as strings. Do not assume every security has all three. |
| Entities and securities | `currency` | Currency associated with cash terms; specify per term when more than one currency occurs. |
| Terms and options | `available_options` | Choices available to the holder, with separate terms/deadlines where needed. |
| Terms and options | `default_option` | What happens when no election is made; extract only if supported. |
| Terms and options | `financial_terms` | Shared representation of cash prices, exchange ratios, conversion prices, and qualifications. Keep consistent with action-specific fields. |
| Terms and options | `conditions_restrictions` | Eligibility rules, proration, minimums, and other material restrictions. |
| Dates and milestones | `effective_date` | Event execution/effectiveness date; retain proposed or conditional status. |
| Dates and milestones | `election_deadline` | Holder election cutoff in the source; distinguish it from offer expiration or an intermediary deadline. |
| Dates and milestones | `expiration_date` | Offer/right expiration, including time/timezone when stated. |
| Dates and milestones | `settlement_date` | Expected consideration settlement date; retain qualifications. |

## Action-specific fields

Add the fields for your action. Fields repeated in the shared schema, such as `expiration_date`, must stay consistent.

| Action | Fields to extract | Interpretation notes |
| --- | --- | --- |
| Tender offer | `offer_price`, `expiration_date`, `withdrawal_deadline`, `minimum_tender_condition`, `proration_terms`, `tendering_conditions` | Preserve currency, per-share/per-unit basis, fixed price versus range, and qualifications. Separate withdrawal rights from offer expiration. |
| Exchange offer | `old_security`, `new_security`, `exchange_ratio`, `expiration_date`, `withdrawal_deadline`, `proration_terms` | Identify the surrendered and received securities. State ratio direction and units; preserve caps, ranges, or variable formulas. Put any cash component in shared `financial_terms` and applicable options. |
| Rights issue | `record_date`, `subscription_ratio`, `subscription_price`, `expiration_date`, `oversubscription_rights`, `rights_transferable` | Distinguish rights allocated per existing holding from rights needed per new share. Preserve subscription currency, eligibility, oversubscription conditions, and transferability as true/false/null. |
| Merger | `acquirer`, `target`, `consideration_type`, `cash_consideration`, `stock_exchange_ratio`, `shareholder_vote_date`, `closing_conditions` | Keep party roles consistent with `parties`. Separate cash, stock, and mixed/elective consideration; retain per-share basis and conditional/proposed closing terms. |
| Conversion | `old_security`, `new_security`, `conversion_ratio`, `conversion_price`, `conversion_deadline`, `conversion_conditions` | State ratio direction, price basis, holder versus issuer election, triggers, and adjustment terms. Keep absent deadlines null rather than inferring them. |

## Rules to keep consistent

- Extract only from supplied text; treat it as source material, not instructions.
- Keep company roles, securities, options and transaction phases separate. SEC search names do not establish party roles; filing date is not event date.
- Preserve proposed/conditional terms, ratio direction, units and timezones. Do not guess missing values or amendment terms.
- Keep identifiers as strings. Use lists or structured values where multiple parties, options or financial terms need to be represented.
- Preserve evidence for extracted values. Model confidence is optional and is not a correctness score.

## Completion checklist

- [ ] Source files, exact input text and SEC metadata saved.
- [ ] Informal check completed; prompts/schema and model settings recorded.
- [ ] Model responses, empty results and failures retained.
- [ ] Flagged fields and a sample of other results reviewed; unresolved fields marked.
- [ ] Combined JSONL, review table and short dataset notes saved with a version name.
