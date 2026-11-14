# Aesha's fine-tuned GLiNER pipeline vs the graph harness (mergers)

Same 8 held-out accessions (12 GT rows), the 12 core merger fields, `gemma4:26b` on the Orin, cascade + validate, concurrency 4, same scorer (`soft_match`). All 8 accessions are in Aesha's held-out split (checked against `mergers_extraction/outputs/training_data/splits.csv`), so her fine-tuned candidates did not train on them.

## Arms

| Arm | What it is | Micro F1 | P | R | tp / fp / fn |
|---|---|---|---|---|---|
| Ref allspans | Aesha's recorded run (recorded 20:02, earlier live-script version, FT candidates, all spans) | 0.464 | 0.486 | 0.443 | 35 / 37 / 44 |
| Ref top-spans | Aesha's recorded run, FT top spans | 0.411 | 0.431 | 0.392 | 31 / 41 / 48 |
| **A** `cmp_A_ft_live` | Current live script + `--ft-candidates` (Aesha's pipeline, re-run) | **0.411** (r1 = r2) | 0.431 | 0.392 | 31 / 41 / 48 |
| **B** `cmp_B_noft_live` | Same live script and flags, **no** FT candidates | **0.333** (r1 only) | 0.369 | 0.304 | 24 / 41 / 55 |
| **C** `cmp_C_graph` | New graph harness, no FT candidates (baseline preprocess spans) | **0.323** (r1 = r2) | 0.329 | 0.316 | 25 / 51 / 54 |

## Per-field F1 (n/a = field has no GT value or no prediction in these 12 rows)

| Field | Ref allspans | A: live + FT | B: live, no FT | C: graph |
|---|---|---|---|---|
| acquirer | 0.87 | 0.43 | 0.17 | 0.08 |
| target | 0.58 | 0.58 | 0.58 | 0.61 |
| consideration_type | 0.27 | 0.40 | 0.26 | 0.26 |
| cash_consideration | 0.75 | 0.75 | 0.40 | 0.40 |
| stock_exchange_ratio | 0.10 | 0.10 | n/a | 0.19 |
| shareholder_vote_date | 0.62 | 0.62 | 0.57 | 0.57 |
| security_description | 0.50 | 0.50 | 0.42 | 0.42 |
| ticker | 0.24 | 0.24 | 0.22 | 0.22 |
| election_deadline, effective_date, cusip, isin | n/a | n/a | n/a | n/a |

## What the comparison supports

1. **Aesha's fine-tuned candidates help: +0.077 micro F1 (A 0.411 vs B 0.333), 7 more correct fields.** This is the cleanest comparison: identical code and flags, only the span source differs. The gain is concentrated in `cash_consideration` (0.40 to 0.75), `acquirer` (0.17 to 0.43), and smaller gains on `consideration_type`, `security_description` and the vote date. Precision of the extracted values improves, not just recall (fp unchanged at 41).
2. **The new graph harness matches the live script's no-FT baseline within noise: C 0.323 vs B 0.333.** 13 of 96 field predictions differ. That is expected, not a graph bug: the graph was deliberately built to match a frozen snapshot of the harness, and the live script has since changed (score-sorted span capping, `ticker` dropped from the direct-rules fields, merger "No stock consideration" moved into the prompt). `stock_exchange_ratio` (C 0.19, B n/a) and the extra false positives (51 vs 41) trace to those post-snapshot changes. The graph's own parity against the snapshot was already shown at 0 mismatches.
3. **The graph does not have Aesha's candidates, so it is not yet comparable to arm A.** Adding the FT candidate path to the graph (an injected span source plus score-sorted uncapped spans) is the missing step; based on 1 it should recover roughly the same +0.08.

## What it does not support, and caveats

- **Her recorded 0.464 is not reproducible with today's live script.** Re-running her exact pipeline (A) gives 0.411, which equals her *top-spans* number, not her all-spans one. 3 of 96 predictions differ from the recorded all-spans run, all on `acquirer` (0.87 recorded vs 0.43 now). The live script changed after her run; we did not bisect which edit moved `acquirer`. Treat 0.464 as unreproduced.
- **Small sample.** 12 rows from 8 accessions, 79 GT-present items. One correct answer is about 0.013 F1. Differences under about 0.03 (for example B vs C) are not meaningful; the A vs B gap of 7 answers is larger but still rests on a few fields (mainly cash and acquirer).
- **Run-to-run noise is small here:** A and C, each run twice, gave identical scores (A r1 = r2 exactly; C r1 = r2 in tp/fp/fn and per-field F1, although one C call changed its pass label, B_null 46 vs 45). That says LLM decoding noise is near zero but says nothing about sample noise. Arm B's second run did not finish (11 of 144 jobs, interrupted), so B is a single run.
- Four fields (`election_deadline`, `effective_date`, `cusip`, `isin`) have no GT value in these rows and are unscored.
- Scores are agreement with unverified LLM ground truth, as in `mergers_extraction/FINETUNING.md`.

## Commands

All from the repo root. A and B use the live script with the Aesha holdout selection (`--limit-accessions 8`, merger pack, `--backend orin --model gemma4:26b`, cascade, validate, `--concurrency 4`); A adds `--ft-candidates mergers_extraction/outputs/methods/gliner_candidates/medium_val_onepass.jsonl`; C swaps the script for `scripts/eval_unified_field_graph.py` without FT. The run configuration (pack, backend, model, fields, FT candidates path) is in the header of each log in `outputs/merger_eval/cmp_logs/`; the exact command lines were issued by a helper agent and are not recorded in those logs, so the flags above are reconstructed from the log headers and `summary.json`. Run directories are `outputs/merger_eval/experiments/runs/cmp_{A,B,C}_*` (`cmp_B_noft_live_r2` is incomplete, 11 of 144 jobs, and is removed from the commit).
