# Fine-tuning GLiNER for merger extraction

How we fine-tuned GLiNER to extract merger fields from SEC filings, how we chose which parts of each filing it reads, and how well it does now. Every number below comes from the files in `outputs/`. The charts are drawn from them by `make_figures.py`, and `visualize_mergers_results.ipynb` shows the same charts and tables for any run, including runs added later.

**Status, November 11, 2026.** On 103 held-out filings, fine-tuned GLiNER reading learned windows scores **0.56 micro-F1** across 10 span fields, against 0.20 for off-the-shelf GLiNER. These scores measure agreement with LLM-extracted ground truth that nobody has checked yet, so they are not accuracy.

**Terms used throughout.** GLiNER reads text in pieces of about 900 characters, called **windows**. A merger filing runs to hundreds of thousands or millions of characters, so only some of its windows can be read, and something has to choose which.

| Term | What GLiNER reads | Windows per filing |
|---|---|---|
| **Original keyword windows** (called `pipeline` in the result folders and the `--windows` option) | The choice made by the existing merger pipeline (`src/merger_gliner.py`), before this work: the start of the filing, plus the text around the first and last mention of 8 keyword patterns such as "merger consideration", "exchange ratio" and "special meeting" | About 11 |
| **Learned windows** | The choice made by `window_selection.py`: every filing is split into windows, each window is scored for each field by how much it looks like the windows that held that field's answer in the training filings (its words and its position in the filing), and the top 5 per field are read | About 30 (fields often pick the same windows) |
| **Ground-truth passages** | Only the passages the ground truth quotes as evidence. Not usable in practice, because it needs the answer's location; it shows what GLiNER scores when it reads the right text | One per quote |

Section 7 explains the learned windows in detail.

![Micro-F1 by setup](figures/01_overall_micro_f1.png)

## 1. Ground truth

The ground truth is `notebooks/evaluation/data/merger_2026-01-01_2026-09-30/mergers.csv`, made by `load_merger_filings.ipynb`. An LLM reads each filing and returns the merger fields with exact supporting quotes.

- **Regenerated for this work.** The first version wrote sentences into the value fields (a median of 288 characters for cash consideration), which a span model cannot match. The prompt now asks for short values: names only, "$47.60 per share", "0.400 shares of X common stock per share", dates as M/D/YYYY. Caveats moved to seven new columns at the end of the table. The 13 original columns keep their names and order, because the downstream agents read them.
- **Coverage.** 600 filings from January to September 2026 gave 951 records from 573 filings. 23 filings returned no merger record, 3 were over the 4.5-million-character limit, and 1 timed out.
- **Unverified.** Every row is LLM output. Scores below are agreement with it.

## 2. Which fields GLiNER handles

GLiNER is a span model: it can only return text that appears in the filing. Fields were split the same way the tender-offer pipeline splits them.

| Group | Fields | Method |
|---|---|---|
| Span fields (fine-tuned) | acquirer, target, merger_subsidiary, security_description, cash_consideration, stock_exchange_ratio, shareholder_vote_date, effective_date, election_deadline, expected_closing | GLiNER |
| Identifiers | ticker, cusip, isin | Regex in the notebook, as in the tender pipeline |
| Derived categories | consideration_type, stock_exchange_ratio_type, mandatory_voluntary_indicator | Rules on the other fields |
| Summaries and status | event_status, closing_conditions, available_options, default_option, qualifications, other_consideration, event_status_details | Not fine-tuned; later candidates for an LLM |

## 3. Baseline: zero-shot GLiNER

`gliner_zero_shot_eval.py` runs off-the-shelf `urchade/gliner_medium-v2.1` with plain-English labels such as "acquirer organization". On the held-out filings it scores 0.20 micro-F1. Its typical mistakes were defined terms and labels from the filing, chosen with high confidence: "Buyer", "Merger Sub", "Exchange Ratio", "Effective Time", tickers such as "FLYX", par values such as "$0.001", and deal totals.

## 4. Building the training data

`build_training_data.py` turns the ground truth into GLiNER training passages.

1. **Find the value in the filing.** For each record and span field, find the field's supporting quotes in the filing text, then find the value inside them. Formatting differences are allowed: "6/11/2026" matches "June 11, 2026", "$16.00 per share" matches "$16.00", and "1 share" matches "one (1) share".
2. **Cut a passage.** Take about 900 characters around each value, the same size GLiNER reads at inference.
3. **Label every value in the passage.** Every ground-truth value of that filing found in the passage is labelled, so a correct answer is never left unmarked.
4. **Add negatives.** Passages from the same filing that hold no values are added unlabelled. They teach the model that "Buyer" or "Exchange Ratio" is not an answer.

Values that cannot be found in the text produce no training data. Exchange ratios are often formulas ("$4.58 divided by Closing VWAP"), and every election deadline in the ground truth is relative wording ("Ten business days after the effective time").

![Ground-truth values found in the filing text](figures/05_training_values_located.png)

## 5. Splitting by deal

One deal produces several filings: a 425, an S-4, a proxy, an 8-K. If they land on both sides of the split, the model is tested on wording it was trained on. Filings that share an SEC file number, a filer CIK or a target name form one deal group, and about 20% of groups are held out. The assignment is saved in `outputs/training_data/splits.csv` and kept as data is added, so the holdout never moves into training.

| | Filings | Deal groups | Passages | Labelled spans |
|---|---|---|---|---|
| Training | 470 | 268 | 5,248 | 15,805 |
| Held out | 103 | 75 | 1,282 | 3,749 |

## 6. Fine-tuning

`train_gliner.py` fine-tunes `urchade/gliner_medium-v2.1` with the settings of the tender-offer fine-tune (`scripts/train_tender_gliner.py`): 500 steps, batch size 2, learning rate 5e-6 (1e-5 for the non-encoder layers), linear schedule with 10% warm-up, focal loss (α 0.75, γ 2). It took 8 minutes on the CPU.

Two practical points:

- **Every passage carries all 10 labels**, as at inference. Without this, GLiNER fails on a batch made only of negative passages, and the model never learns that a field can be absent.
- **Train on the CPU** (`--use-cpu`). On the Mac GPU (MPS), memory grew with every step and training failed around step 100 each time; the CPU was about as fast.

![Training loss](figures/06_training_loss.png)

## 7. Choosing which windows to read

A merger filing has hundreds of thousands to millions of characters, and GLiNER reads about 900 at a time, so something has to choose what it reads. The existing pipeline (`src/merger_gliner.py`) reads around the first and last hit of 8 keyword patterns, about 11 windows per filing. Those windows held only 30% of the held-out answers.

`window_selection.py` learns the choice instead, from the training filings only:

1. Split each filing into overlapping 900-character windows.
2. Mark the windows that contain each field's ground-truth value.
3. For each field, learn which words, two-word phrases ("special meeting", "right to receive") and positions in the filing mark those windows. It is a naive-Bayes score, limited to the 150 most telling features that appear in answer windows of at least 5 different deals (so one deal's company names and tickers do not count). Position matters: about 75% of party-name quotes sit in the first 10% of the filing, in the proxy summary.
4. For a new filing, read the top 5 windows per field. Fields often pick the same windows, so this averages 30 windows.

![Answers inside the windows, by number of windows read](figures/03_window_coverage.png)

The learned windows hold 74% of the held-out answers from 30 windows. Reading the first 90 windows of each filing gets 66%.

The most telling words it learned are general merger wording: "without interest", "in cash" and "receive per" for cash; "held virtually", "am eastern" and "online via" for the vote date; "date depends" and "when do" (from "When do you expect the merger to be completed?") for expected closing; the proxy cover letter ("dear … enclose") for the acquirer and target. They are listed per field in `outputs/window_selector/top_features.json`.

![Answers inside the windows, by field](figures/04_window_coverage_by_field.png)

How the settings were chosen. The first version used every word and did no better than reading the start of the filing; limiting it to 150 features seen in at least 3 answer windows was decided after a look at the first 26 held-out filings, so those filings had a small influence on the design. That version still learned company names from individual training deals ("hpst", "aptose", "devon"), which mean nothing on a new filing, so words now also have to appear in answer windows of at least 5 different deals. That rule was chosen from the learned word lists, not from held-out scores, and raised coverage from 65% to 74% and fine-tuned micro-F1 by 0.02.

## 8. Results

`gliner_finetuned_eval.py` scores each model on the 103 held-out filings. It takes the top-scoring span per field and filing and compares it with every ground-truth record of that filing:

- **Names** are compared without suffixes such as "Inc." or "Corp.". A generic role such as "Parent" or "Merger Sub" never counts as correct.
- **Cash and ratios** are compared as numbers, and **dates** as dates. For ratios, number words count: "one (1) share" matches 1.
- **Security description and expected closing** need at least half their words in common.
- **Stated absences** such as "No cash consideration" are counted apart, because a span model cannot produce them.

**Scoring correction, November 11.** The first scores read only digits, so an answer of "one" (from "one (1) share of PubCo") was marked wrong against "1 share … per share". Fixing this turned 36 held-out exchange-ratio answers from wrong to right: exchange ratio rose from 0.12 to 0.39 and micro-F1 from 0.53 to 0.56. All saved runs were rescored from their saved predictions (`rescore_all.py`); no model was rerun.

The "ground-truth passages" column is a reference point: GLiNER reads only the passages the ground truth quotes. It shows what perfect window choice would give, though not exactly. Those passages are pooled across fields, so for some fields the model picks a span from another field's passage and scores below the learned windows.

![F1 per field](figures/02_per_field_f1.png)

| Field | Zero-shot, learned windows | Fine-tuned, original keyword windows | **Fine-tuned, learned windows** | Fine-tuned, ground-truth passages |
|---|---|---|---|---|
| Expected closing | 0.54 | 0.38 | **0.79** | 0.87 |
| Merger subsidiary | 0.15 | 0.56 | **0.68** | 0.67 |
| Security description | 0.29 | 0.65 | **0.64** | 0.64 |
| Target | 0.26 | 0.48 | **0.52** | 0.51 |
| Acquirer | 0.09 | 0.44 | **0.50** | 0.43 |
| Shareholder vote date | 0.32 | 0.42 | **0.47** | 0.51 |
| Cash consideration | 0 | 0.42 | **0.46** | 0.39 |
| Exchange ratio | 0.03 | 0.41 | **0.39** | 0.47 |
| Effective date | 0.01 | 0.22 | **0.06** | 0.50 |
| Election deadline | 0 | — | **—** | — |
| **Micro-F1** | 0.19 | 0.49 | **0.56** | 0.57 |

Election deadline has no training data and only 4 held-out values, so no fine-tuned F1 is reported.

**What the results show**

- **Fine-tuning is the main gain:** 0.20 to 0.49. It removed most of the defined-term and ticker answers.
- **Learned windows add 0.07,** almost all the way to the 0.57 reference. Expected closing gains the most (0.38 to 0.79) because the original keyword windows rarely reached the "expected to close" sentences.
- **Some fields now need precision, not more reading.** With learned windows, cash consideration finds 82% of the held-out amounts but is right only 32% of the time it answers (it also tags deal totals and other prices). Vote date finds 84% and is right 33% of the time (other dates in the meeting notice). See the plan in section 10.
- **Effective date** has a value in only 18 of 951 records, so the model rarely sees one and tags dates where there is none: 1 right and 33 wrong on the holdout.
- **Exchange ratio** reaches 0.39: fixed ratios are found ("0.2236", "one (1) share"), but only 52% of its values can be found in the text at all, because many are formulas ("$4.58 divided by Closing VWAP").

The first fine-tune, on 146 filings with a 26-filing holdout, scored 0.40 with original keyword windows. That holdout is smaller and different, so it is not directly comparable, but the direction matched.

## 9. Limitations

- **Unverified ground truth.** All scores are agreement with LLM output. A hand-checked sample of the held-out filings is needed before calling any number accuracy.
- **Top-1 per filing.** One prediction per field is compared with every record of a filing, so a filing about two deals or two share classes can never score fully.
- **Missing filings.** 27 of the 600 filings give no training or test data (23 without a merger record, 4 not extracted).
- **Lenient text matching** for security description and expected closing (half the words in common).

## 10. Plan

The fields fall into two groups, and they need different work.

| Group | Fields | What limits them | Next method |
|---|---|---|---|
| GLiNER works | Expected closing, merger subsidiary, security description, target, acquirer | Under-training and wrong candidates (acquirer and target swap roles) | More GLiNER training; a role rule for acquirer and target |
| GLiNER finds the answer but picks wrong ones | Cash consideration, shareholder vote date | Precision: they find over 80% of answers but are right about a third of the time | Candidate filters (cash: no "million"/"billion", near "per share"); temporal NER for the vote date |
| GLiNER cannot do it | Effective date, election deadline, formula exchange ratios | Relative wording, too few examples, formulas (fixed ratios work: exchange ratio 0.39) | Temporal NER for the dates; Qwen for formula ratios and the election deadline |
| Not span fields | Closing conditions, available and default options, qualifications, other consideration, event status and details | Summaries and labels, not text spans | Qwen |

**Priority: methods for the weak fields first.** More GLiNER training cannot fix the weak fields, which are about half of all fields, and they are what BNY asked for: in the October 16 demo feedback, dates (deadlines especially, where a wrong value is the costliest error), mandatory versus voluntary classification (which depends on the available and default options), and consistent event descriptions built from the key facts. Longer GLiNER training runs in the background at the same time, since it needs computer time, not attention.

| Order | Work | Detail |
|---|---|---|
| 1 | **Temporal NER for dates** | Reuse `scripts/eval_temporal_tagger_dates.py` (`satyaalmasian/temporal_tagger_BERT_tokenclassifier`). Find every date in the learned windows, then assign the role from nearby wording ("special meeting … will be held" for the vote date, "became effective" or "completed the merger" for the effective date, "Election Deadline" for the election deadline). Return nothing when no wording matches, which is what effective date needs. |
| 2 | **Qwen on the learned windows** | Exchange ratio, election deadline, options, default, conditions, qualifications and event status, asked for as JSON in the ground truth's format. Templates: `scripts/eval_qwen_direct_fields.py` and `scripts/eval_llm_clause_fields.py` (Qwen3 4B was the strongest single method on tender offers, 0.65). Needs Ollama (`brew install ollama`) and a model download of about 2.5 GB; not installed yet. |
| Background | **GLiNER experiment A** | Longer training with a validation set (below). |
| 3 | **Combine** | Send each field to its best method on the validation set, then report per-field accuracy, runtime and cost against the LLM ground truth: the goal of near-LLM accuracy at lower cost. |
| Ongoing | **Hand-check 20 to 30 held-out filings** | So the scores measure accuracy, not agreement with the LLM. |

Every method writes its scores with `common.write_results` (`per_field.csv` and `summary.json`, with `"method": "<name>"` in the summary), so it appears in `visualize_mergers_results.ipynb` next to GLiNER on the same held-out filings.

### Next GLiNER training experiment

| Setting | Choice | Why |
|---|---|---|
| Base model | `gliner_medium-v2.1` | What the tender pipeline settled on; large is 2–3 times slower on the CPU and the tender attempt at it was stopped. Try large only if medium stops improving. |
| Training data | All training deals except a validation slice | Less data does not reduce overfitting, it makes it likelier. Deal-level splitting already keeps one deal's filings together. |
| Validation set | About 15% of the training deal groups, split by deal | Every choice (checkpoint, thresholds, rules) is made on it. The 103 held-out filings are scored once per finished experiment, so they stay an honest test. |
| Steps | About 2,600 (one pass over the 5,248 passages at batch size 2), about 45 minutes on the CPU | 500 steps saw about a fifth of the passages; the final tender model saw about half of its 2,091. |
| Checkpoints | At 500, 1,000, 1,500, 2,000 and 2,600 steps, each scored on validation | Early stopping: keep the best checkpoint. Do not go past about two passes without a clear validation gain, because the labels are LLM output and longer training memorises their errors. |
| Learning rate and schedule | Unchanged (5e-6, 10% warm-up, linear decay) | Change one thing at a time. |

Then, one change per experiment: (B) negatives taken from the learned windows instead of the original keyword windows, so the model trains on the passages that produce its wrong answers; (C) per-field confidence thresholds and candidate filters, tuned on validation. Thresholds may help less than expected: on tender offers, changing the threshold from 0.25 to 0.55 left the score unchanged, because wrong answers were also high-confidence. With 103 held-out filings, treat a change smaller than about 0.03 as noise unless it holds across most fields; rerun close calls with a second seed.

## Reproduce

From the repository root, with the project `.venv`:

```bash
.venv/bin/python mergers_extraction/build_training_data.py
.venv/bin/python mergers_extraction/train_gliner.py --use-cpu --name medium_500steps_573filings
.venv/bin/python mergers_extraction/gliner_finetuned_eval.py --name medium_500steps_573filings --windows pipeline
.venv/bin/python mergers_extraction/window_selection.py
.venv/bin/python mergers_extraction/gliner_finetuned_eval.py --name medium_500steps_573filings --windows learned
.venv/bin/python mergers_extraction/make_figures.py
```

| Output | Where |
|---|---|
| Training data, split and coverage | `outputs/training_data/` |
| Model weights (gitignored) | `models/merger_gliner/medium_500steps_573filings/` |
| Training settings and loss | `outputs/gliner_finetuned_medium_500steps_573filings_holdout/train_meta.json` |
| Scores and every prediction | `outputs/gliner_finetuned_medium_500steps_573filings_holdout/{pipeline,learned}_windows/` |
| Window selector and its coverage | `outputs/window_selector/` |
| Charts | `figures/` |
