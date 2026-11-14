# Merger extraction

Experiments for extracting merger fields from SEC filings, starting with GLiNER and adding other methods where it falls short. For the method and current results, read [FINETUNING.md](FINETUNING.md).

## Inputs

| What | Where |
|---|---|
| Ground truth (LLM-extracted, unverified) | `notebooks/evaluation/data/merger_2026-01-01_2026-09-30/mergers.csv` (600 filings), `mergers_sample.csv` (10-filing sample) |
| Filing text, one file per filing | `notebooks/evaluation/data/merger_2026-01-01_2026-09-30/input_text/<accession>.txt` |
| How the ground truth is made | `notebooks/evaluation/load_merger_filings.ipynb` |

The ground truth is model output that nobody has checked, so every score here is agreement with it, not accuracy.

## Fields and extraction method

Method is the approach chosen for production; TBD until an experiment settles it. GLiNER scores in the notes are micro-F1 on the 103 held-out filings with learned windows (full fine-tune, below). The tender column shows how the tender-offer pipeline handles the equivalent field (`src/preprocess/contracts.py` for GLiNER labels, `src/preprocess/rules_ids.py` for rules).

**Acquirer and target are defined per affected security** (decided Nov 12, 2026), the way custodians process a corporate action: one record for each company whose securities are cancelled or converted. The *target* is that company; the *acquirer* is the company whose shares or cash its holders receive. In a SPAC merger with a new holding company (PubCo), both the SPAC and the operating company are targets, in two records, and PubCo is the acquirer of both. In a SPAC merger without one, the operating company is the target and the SPAC the acquirer; the SPAC's holders keep their shares, so they have no record. The ground-truth prompt states this; the merger file was labelled before the change, so it follows the rule only mostly.

| Field | Ground-truth value | Tender equivalent | Method | Notes |
|---|---|---|---|---|
| acquirer | Legal name of the issuer of the new shares, or the cash payer | offeror: GLiNER | TBD | Fine-tuned GLiNER 0.50 (zero-shot 0.09); still picks other organisations |
| target | Legal name of the company whose securities convert; one record each | target: GLiNER | TBD | Fine-tuned GLiNER 0.52 (zero-shot 0.26) |
| merger_subsidiary | Legal name | purchaser: GLiNER | TBD | Fine-tuned GLiNER 0.68 (zero-shot 0.15) |
| security_description | Class, e.g. "Class A common stock" | security_description: GLiNER | TBD | Fine-tuned GLiNER 0.64 (zero-shot 0.29) |
| cash_consideration | "$16.00 per share" | offer_price: GLiNER | TBD | Fine-tuned GLiNER 0.46 (zero-shot 0); finds most amounts but also tags deal totals and prices |
| stock_exchange_ratio | "0.2236 shares of X common stock per share" | none | TBD | Fine-tuned GLiNER 0.39; fixed ratios work, but only 52% of values can be located (formulas), candidate for an LLM |
| shareholder_vote_date | "6/11/2026 4:00 PM Eastern Time" | none (dates: GLiNER) | TBD | Fine-tuned GLiNER 0.47 (zero-shot 0.32); tags other dates; candidate for temporal NER |
| effective_date | Date | effective_date: GLiNER | TBD | Only 18 of 951 records have one; fine-tuned GLiNER tags dates where there is none (1 right, 33 wrong on the holdout) |
| election_deadline | Date | none (dates: GLiNER) | TBD | 19 of 951 records, all relative wording, so no training data |
| expected_closing | "second half of 2026" | settlement_date (timing phrases): rules | TBD | Fine-tuned GLiNER 0.79 (zero-shot 0.54) |
| consideration_type | Cash / Stock / Mixed cash and stock / Elective consideration / Other | offer_price_type: not in GLiNER | Rule on other fields | Derived from cash, ratio and options; agrees with the ground truth in 97 of 100 records where cash or ratio is present |
| stock_exchange_ratio_type | Fixed / Range / Formula | none | Rule on other fields | Derived from the ratio value; agrees in 70 of 76 records |
| event_status | Announced / Pending / Amended / Completed / Terminated / Withdrawn | event_status: not in GLiNER | TBD | Not set by form type (8-Ks have all five statuses); GLiNER returned nothing |
| event_status_details | Short note | not in GLiNER | TBD | Summary |
| closing_conditions | Short list | conditions: not in GLiNER; minimum_tender_condition: GLiNER | TBD | Summary |
| available_options | Short list or "No holder election" | available_option: GLiNER | TBD | Summary |
| default_option | Short note | not in GLiNER | TBD | Summary |
| cash_consideration_qualifications | Short list | not in GLiNER | TBD | Summary |
| stock_exchange_ratio_qualifications | Short list | none | TBD | Summary |
| other_consideration | Short note, e.g. CVR terms | none | TBD | Summary |
| ticker | Symbol(s) | rules | Regex + SEC search data | Already in the notebook; not a GLiNER field |
| cusip | 9-character ID | rules | Regex with check digit | Already in the notebook; not a GLiNER field |
| isin | 12-character ID | rules | Regex, else derived from CUSIP | Already in the notebook; derived values are not in the filing text |
| mandatory_voluntary_indicator | Mandatory / Mandatory with options | fixed "Voluntary" | Rule on other fields | Already in the notebook |
| form, filing date, registrant, CIK, accession, SEC file number | — | EDGAR metadata | EDGAR metadata | Not extracted |

Stated absences such as "No holder election" or "No cash consideration" cannot come from a span model; whichever method handles those fields has to produce them.

## Contents

| File | What it does |
|---|---|
| `FINETUNING.md` | **Start here:** the fine-tuning and window-selection method, step by step, with charts of the current results |
| `visualize_mergers_results.ipynb` | Scores and charts for every scored run in `outputs/`; rerun it after any experiment (nothing is retrained) |
| `results.py` | Finds the scored runs and draws the charts, used by the notebook and `make_figures.py` |
| `rescore_all.py` | Recomputes every saved run's scores from its saved predictions after a change to the scorer; no model is run |
| `make_figures.py` | Saves the charts in `figures/` used by `FINETUNING.md` |
| `common.py` | Shared code: paths, the field lists (`SPAN_FIELDS` are fine-tuned, `SUMMARY_FIELDS` are zero-shot only), value matching, the deal split and the scorer |
| `gliner_zero_shot_eval.py` | Off-the-shelf GLiNER (`urchade/gliner_medium-v2.1`, no training) on the span and summary fields, scored field by field |
| `build_training_data.py` | Turns the ground truth into GLiNER training passages and splits filings into train and holdout by deal |
| `train_gliner.py` | Fine-tunes GLiNER on the training passages (settings from the tender fine-tune) |
| `gliner_finetuned_eval.py` | Scores the fine-tuned model and zero-shot GLiNER side by side on the held-out deals, with either window choice (`--windows pipeline` or `--windows learned`) |
| `window_selection.py` | Learns which parts of a filing GLiNER should read, from the training filings, and reports how many held-out answers each window choice covers |
| `outputs/gliner_zero_shot_sample/` | Zero-shot results on the 10-filing sample |
| `outputs/training_data/` | Training data: `train.jsonl`, `holdout.jsonl`, `splits.csv`, `coverage.csv`, `summary.json` and the ground-truth snapshot it was built from |
| `outputs/window_selector/` | The learned selector (`selector.json`), its most telling words per field (`top_features.json`) and answer coverage per window choice (`answer_recall.csv`) |
| `outputs/gliner_finetuned_<name>_holdout/<windows>_windows/` | Fine-tuned versus zero-shot comparison (`comparison.csv`, plus per-field scores and every prediction for each model), written by `gliner_finetuned_eval.py` |

Model weights are saved to `models/merger_gliner/<name>/` at the repository root, which git ignores.

Every evaluation scores GLiNER twice:

- **original keyword windows** or **learned windows**: the parts of the filing it reads in practice (see FINETUNING.md, "Terms used throughout")
- **ground-truth passages** (`oracle` in the files): the quotes the ground truth cites, so window selection is perfect

## Fine-tuning workflow

Run from the repository root with the project's `.venv` (training also needs `accelerate`, installed there). Train with `--use-cpu`: on the Mac GPU (MPS) training ran out of memory around step 100 every time, while the CPU is about as fast.

```bash
.venv/bin/python mergers_extraction/build_training_data.py          # snapshot mergers.csv, build passages, split by deal
.venv/bin/python mergers_extraction/train_gliner.py --use-cpu       # 500 steps, about 9 minutes on the CPU
.venv/bin/python mergers_extraction/gliner_finetuned_eval.py --name <name> --windows pipeline
.venv/bin/python mergers_extraction/window_selection.py             # learn which windows to read (training filings only)
.venv/bin/python mergers_extraction/gliner_finetuned_eval.py --name <name> --windows learned
```

- **Snapshot:** `build_training_data.py` reads only the filings the notebook has finished and saves them as `ground_truth_snapshot.csv`, so it can run while the full extraction is still going. Rerun it when more filings are done.
- **Training passages:** for each span field, the value is found inside the field's quotes in the filing, allowing for formatting ("6/11/2026" matches "June 11, 2026", "$16.00 per share" matches "$16.00"), and a ~900-character passage is cut around it. Every ground-truth value of that filing found in the passage is labelled. Original keyword windows with no values are added as negatives, so the model learns that defined terms such as "Buyer" or "Exchange Ratio" are not answers.
- **Deal split:** filings that share an SEC file number, a filer CIK or a target name form one deal group, and about 20% of groups are held out. Assignments are saved in `splits.csv` and kept when the data grows, so the holdout stays fixed.
- **Coverage:** `coverage.csv` shows, per field, how many ground-truth values were located in the filing text. Fields that cannot be located get no training data.

### First build: 119 filings (214 records), November 11

| Field | Records with a value | Located in the filing | Training spans |
|---|---|---|---|
| acquirer | 197 | 88% | 923 |
| target | 200 | 98% | 1,557 |
| merger_subsidiary | 180 | 92% | 282 |
| security_description | 181 | 86% | 1,459 |
| cash_consideration | 72 (30 are "No cash consideration") | 86% | 105 |
| stock_exchange_ratio | 158 (31 are "No stock consideration") | 54% (formulas cannot be located) | 214 |
| shareholder_vote_date | 59 | 100% | 92 |
| effective_date | 10 | 100% | 20 |
| election_deadline | 5 | 0% (all relative, e.g. "Ten business days after the effective time") | 0 |
| expected_closing | 159 | 82% | 81 |

Split: 101 filings in 90 deal groups for training, 18 filings in 18 groups held out. 1,224 training passages, 206 holdout passages.

Zero-shot GLiNER on those 18 held-out filings, span fields only: micro-F1 0.17 with original keyword windows, 0.26 with the ground-truth passages. This is the baseline the fine-tuned model has to beat.

### First fine-tune: 146 filings, November 11

Model `medium_500steps_146filings`: `gliner_medium-v2.1`, 500 steps on 120 training filings (1,438 passages), CPU, 9 minutes. Scored on the 26 held-out filings (`outputs/gliner_finetuned_medium_500steps_146filings_holdout/pipeline_windows/comparison.csv`).

| Field | Fine-tuned, original keyword windows | Zero-shot, original keyword windows | Fine-tuned, ground-truth passages | Zero-shot, ground-truth passages |
|---|---|---|---|---|
| acquirer | 0.26 | 0.07 | 0.29 | 0.19 |
| target | 0.43 | 0.25 | 0.50 | 0.15 |
| merger_subsidiary | 0.49 | 0.12 | 0.58 | 0.24 |
| security_description | 0.56 | 0.36 | 0.61 | 0.39 |
| cash_consideration | 0.28 | 0.05 | 0.29 | 0.15 |
| stock_exchange_ratio | 0.39 | 0 | 0.44 | 0 |
| shareholder_vote_date | 0.43 | 0.16 | 0.61 | 0.54 |
| effective_date | 0.50 (1 value) | 0 | 0.50 | 0 |
| expected_closing | 0.25 | 0.13 | 0.92 | 0.38 |
| **Micro-F1** | **0.40** | **0.14** | **0.53** | **0.22** |

Every field improved. With 26 held-out filings, single-field scores move a lot with one or two filings; treat them as directional until the full 600-filing run.

Remaining problems, from `finetuned/details.csv`:

- **Window selection is now the main loss.** The original keyword windows held 6 of 33 acquirer quotes and 1 of 15 expected-closing quotes. Expected closing scores 0.92 when GLiNER reads the right passage but 0.25 with the original keyword windows.
- **Acquirer** still picks other organisations, e.g. "Nasdaq Stock Market LLC" or a subsidiary.
- **Cash** still tags deal totals ("$441,500,000") and nearby prices.
- **Exchange ratio** is limited by formula ratios ("$4.58 divided by Closing VWAP"), which cannot be a span. (Scores in this table were rescored after the number-word fix; see FINETUNING.md, section 8.)

## Current results

Full method, charts and per-field results: [FINETUNING.md](FINETUNING.md). Latest scores for every run: `visualize_mergers_results.ipynb`.

On the 103 held-out filings (75 deal groups), November 11: zero-shot GLiNER 0.20 micro-F1 with original keyword windows; fine-tuned `medium_500steps_573filings` 0.49 with original keyword windows and **0.56 with learned windows**; 0.57 when it reads only the ground-truth passages. The learned windows hold 74% of the held-out answers from about 30 windows per filing, against 30% for the original keyword windows. Agreement with unverified LLM output, not accuracy.

## Zero-shot result on the 10-filing sample

Micro-F1 0.16 with either window type, so the model's reading is the main problem, not where it looks. GLiNER picks defined terms ("Buyer", "Merger Sub", "Exchange Ratio", "Effective Time"), tickers and par values with high confidence. Per-field scores are in the table above and in `outputs/gliner_zero_shot_sample/per_field.csv`.

The original keyword windows held only 2 of 17 acquirer quotes and 0 of 14 ratio quotes, so window selection will matter once extraction improves.

## Next steps

See the plan in [FINETUNING.md, section 10](FINETUNING.md#10-plan): temporal NER for the dates and Qwen for the exchange ratio, election deadline and summary fields first, with a longer GLiNER training run (validation set, checkpoints) in the background.
