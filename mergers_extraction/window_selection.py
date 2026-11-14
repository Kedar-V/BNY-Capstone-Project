#!/usr/bin/env python3
"""Choose which parts of a long filing GLiNER reads.

GLiNER reads ~900-character windows, and merger filings run to millions of characters, so only some windows can be
read. The existing pipeline (src/merger_gliner.py) takes the first and last hit of 8 keyword patterns, which missed
most ground-truth quotes. This script learns a better choice from the training filings:

  * split each filing into overlapping 900-character windows,
  * for each span field, mark the windows that contain the ground-truth value,
  * learn a naive-Bayes score per field from the words in a window and its position in the filing
    (values cluster in the summary at the front of a proxy), keeping only words seen in answer windows of at
    least 5 different deals, so one deal's company names do not count,
  * select the top windows per field.

It then reports answer recall on the held-out filings: the share of ground-truth values that fall inside a
selected window, for the original keyword windows, the first windows of the filing, and the learned selector, at several
window budgets. Only training filings are used to learn the scores.

    python mergers_extraction/window_selection.py
"""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

import common
from build_training_data import flexible, value_spans

WIDTH, STRIDE = 900, 700
POSITION_BUCKETS = 20
SELECTOR_PATH = common.OUTPUTS / "window_selector" / "selector.json"
MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"


# ---------------------------------------------------------------- windows and features
def chunks(text: str, width: int = WIDTH, stride: int = STRIDE) -> list[tuple[int, str]]:
    """Overlapping windows covering the whole filing, cut at spaces."""
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + width)
        if end < len(text):
            cut = text.rfind(" ", start + width // 2, end)
            end = cut if cut > start else end
        out.append((start, text[start:end]))
        if end >= len(text):
            break
        start += stride
    return out


def features(chunk: str, start: int, length: int) -> set[str]:
    """Distinct words plus shape markers (money, date, ratio-like number) and the position bucket."""
    low = chunk.lower()
    words = re.findall(r"[a-z][a-z'\-]+", low)
    feats = {w for w in words if len(w) > 2} | {f"{a} {b}" for a, b in zip(words, words[1:])}
    if re.search(r"\$\s?\d", chunk):
        feats.add("<money>")
    if re.search(rf"\b(?:{MONTHS})\s+\d{{1,2}},?\s+\d{{4}}", low):
        feats.add("<date>")
    if re.search(r"\b0\.\d{2,}\b", chunk):
        feats.add("<decimal>")
    if re.search(r"\[\s*[•·]?\s*\]|\[•\]", chunk):
        feats.add("<placeholder>")
    feats.add(f"<pos{min(POSITION_BUCKETS - 1, int(POSITION_BUCKETS * start / max(1, length)))}>")
    return feats


def value_positions(text: str, records: pd.DataFrame) -> dict[str, list[tuple[int, int]]]:
    """field -> character spans of the ground-truth values, found inside the field's own quotes."""
    out = defaultdict(list)
    for _, row in records.iterrows():
        passages = common.passages_of(row)
        for field, (_, kind) in common.SPAN_FIELDS.items():
            gold = str(row.get(field, "")).strip()
            if common.blank(gold) or common.absence(gold):
                continue
            for q in passages.get(field) or []:
                quote = q.get("quote") if isinstance(q, dict) else None
                hit = flexible(quote).search(text) if quote else None
                if not hit:
                    continue
                lo = hit.start()
                hi = min(len(text), lo + len(quote) + 200)
                out[field] += [(lo + s, lo + e) for s, e in value_spans(text[lo:hi], kind, gold)]
    return out


# ---------------------------------------------------------------- selector
class Selector:
    """Per-field naive Bayes over window features (Bernoulli, add-one smoothing)."""

    def __init__(self, weights: dict[str, dict[str, float]], prior: dict[str, float]):
        self.weights, self.prior = weights, prior

    @classmethod
    def fit(cls, filings: list[tuple[str, dict]], groups: list[str] | None = None, max_negatives_per_filing: int = 200,
            seed: int = 0, min_positive_count: int = 3, min_deal_groups: int = 5, max_features: int = 150) -> "Selector":
        """groups: the deal group of each filing. A feature is kept only if it appears in answer windows of at least
        min_deal_groups different deals, so words that belong to one deal (company names, tickers) drop out."""
        import random
        rng = random.Random(seed)
        groups = groups or [str(i) for i in range(len(filings))]
        pos_df, neg_df = defaultdict(Counter), defaultdict(Counter)
        pos_groups: dict[str, dict[str, set]] = defaultdict(lambda: defaultdict(set))
        n_pos, n_neg = Counter(), Counter()
        for (text, spans), group in zip(filings, groups):
            wins = chunks(text)
            feats = [features(c, s, len(text)) for s, c in wins]
            for field in common.SPAN_FIELDS:
                hits = spans.get(field, [])
                positive = [i for i, (s, c) in enumerate(wins) if any(s <= a and b <= s + len(c) for a, b in hits)]
                pset = set(positive)
                negatives = [i for i in range(len(wins)) if i not in pset]
                if len(negatives) > max_negatives_per_filing:
                    negatives = rng.sample(negatives, max_negatives_per_filing)
                for i in positive:
                    pos_df[field].update(feats[i])
                    for f in feats[i]:
                        pos_groups[field][f].add(group)
                for i in negatives:
                    neg_df[field].update(feats[i])
                n_pos[field] += len(positive)
                n_neg[field] += len(negatives)
        weights, prior = {}, {}
        for field in common.SPAN_FIELDS:
            if not n_pos[field]:
                continue
            vocab = set(pos_df[field]) | set(neg_df[field])
            w = {}
            for f in vocab:
                p = (pos_df[field][f] + 1) / (n_pos[field] + 2)
                q = (neg_df[field][f] + 1) / (n_neg[field] + 2)
                # Bernoulli NB: log-odds of the feature being present; absent features are folded into the prior
                w[f] = math.log(p / q) - math.log((1 - p) / (1 - q))
            # keep only features seen in enough answer windows of enough different deals, then the most informative:
            # rare words and one deal's company names are noise on a new filing. Position features are always kept.
            keep = [f for f in vocab if f.startswith("<pos") or (pos_df[field][f] >= min_positive_count
                                                                  and len(pos_groups[field][f]) >= min_deal_groups)]
            keep = sorted(keep, key=lambda f: -abs(w[f]))[:max_features]
            weights[field] = {f: round(w[f], 4) for f in keep}
            prior[field] = 0.0
        return cls(weights, prior)

    def scores(self, text: str) -> tuple[list[tuple[int, str]], dict[str, list[float]]]:
        wins = chunks(text)
        feats = [features(c, s, len(text)) for s, c in wins]
        return wins, {field: [sum(w.get(f, 0.0) for f in fs) for fs in feats] for field, w in self.weights.items()}

    def select(self, text: str, per_field: int = 3, max_windows: int = 30) -> list[tuple[int, str]]:
        """Top windows per field, taken round-robin across fields until the budget is used."""
        wins, scores = self.scores(text)
        ranked = {field: sorted(range(len(wins)), key=lambda i: -s[i])[:per_field] for field, s in scores.items()}
        chosen: list[int] = []
        for rank in range(per_field):
            for field in ranked:
                if rank < len(ranked[field]) and ranked[field][rank] not in chosen and len(chosen) < max_windows:
                    chosen.append(ranked[field][rank])
        return [wins[i] for i in sorted(chosen)]

    def save(self, path: Path = SELECTOR_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"width": WIDTH, "stride": STRIDE, "prior": self.prior, "weights": self.weights}))

    @classmethod
    def load(cls, path: Path = SELECTOR_PATH) -> "Selector":
        if not path.exists():
            raise SystemExit(f"{path} not found: run mergers_extraction/window_selection.py first")
        data = json.loads(path.read_text())
        return cls(data["weights"], data["prior"])


def first_windows(text: str, n: int) -> list[tuple[int, str]]:
    return chunks(text)[:n]


# ---------------------------------------------------------------- evaluation
def answer_recall(filings: list[tuple[str, dict]], choose) -> tuple[dict[str, float], float, float]:
    """Share of located ground-truth values (per record and field) inside at least one chosen window."""
    found, total, n_windows = Counter(), Counter(), []
    for text, spans in filings:
        wins = choose(text)
        n_windows.append(len(wins))
        for field, hits in spans.items():
            groups = defaultdict(list)  # one value can occur several times; count it once
            for a, b in hits:
                groups[text[a:b].lower()].append((a, b))
            for occurrences in groups.values():
                total[field] += 1
                found[field] += any(s <= a and b <= s + len(c) for a, b in occurrences for s, c in wins)
    per_field = {f: found[f] / total[f] for f in common.SPAN_FIELDS if total[f]}
    overall = sum(found.values()) / max(1, sum(total.values()))
    return per_field, overall, sum(n_windows) / max(1, len(n_windows))


def load_filings(gt: pd.DataFrame, accessions: list[str]) -> list[tuple[str, dict]]:
    out = []
    for acc in accessions:
        text = common.filing_text(acc)
        out.append((text, value_positions(text, gt[gt["accession_number"] == acc])))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gt", type=Path, default=common.TRAINING_DATA / "ground_truth_snapshot.csv")
    ap.add_argument("--min-deal-groups", type=int, default=5,
                    help="keep a word only if it appears in answer windows of this many different deals")
    args = ap.parse_args()

    gt = common.load_ground_truth(args.gt)
    splits = pd.read_csv(common.SPLITS_PATH, dtype=str)
    in_gt = set(gt["accession_number"])
    train = sorted(set(splits.loc[splits["split"] == "train", "accession_number"]) & in_gt)
    holdout = sorted(set(splits.loc[splits["split"] == "holdout", "accession_number"]) & in_gt)
    print(f"learning from {len(train)} training filings, scoring {len(holdout)} held-out filings")

    group_of = dict(splits[["accession_number", "deal_group"]].values)
    selector = Selector.fit(load_filings(gt, train), groups=[group_of[a] for a in train],
                            min_deal_groups=args.min_deal_groups)
    selector.save()
    test = load_filings(gt, holdout)

    strategies = {
        "original keyword windows (12)": lambda t: common.select_windows(t, max_windows=12),
        "first 12 windows": lambda t: first_windows(t, 12),
        "first 30 windows": lambda t: first_windows(t, 30),
        "first 50 windows": lambda t: first_windows(t, 50),
        "first 100 windows": lambda t: first_windows(t, 100),
        "learned, 1 per field (10)": lambda t: selector.select(t, per_field=1, max_windows=10),
        "learned, 2 per field (20)": lambda t: selector.select(t, per_field=2, max_windows=20),
        "learned, 3 per field (30)": lambda t: selector.select(t, per_field=3, max_windows=30),
        "learned, 5 per field (50)": lambda t: selector.select(t, per_field=5, max_windows=50),
    }
    rows = []
    for name, choose in strategies.items():
        per_field, overall, avg = answer_recall(test, choose)
        rows.append({"strategy": name, "avg_windows": round(avg, 1), "overall": round(overall, 3),
                     **{f: round(v, 2) for f, v in per_field.items()}})
    table = pd.DataFrame(rows)
    out = common.OUTPUTS / "window_selector"
    table.to_csv(out / "answer_recall.csv", index=False)
    top = {f: sorted(w.items(), key=lambda kv: -kv[1])[:12] for f, w in selector.weights.items()}
    (out / "top_features.json").write_text(json.dumps(top, indent=1))
    pd.set_option("display.width", 250)
    print(table.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
