"""Every span the fine-tuned GLiNER proposes on the learned windows, with its score and surrounding text, cached so
that filters and rules (cash_filter.py, role_rule.py) can choose among them without rerunning the model.

Cache: outputs/methods/gliner_candidates/<model>.jsonl, one line per filing.
"""
from __future__ import annotations

import json

import common
from window_selection import Selector

THRESHOLD = 0.3  # lower than the 0.4 used for top-1 answers, so filters have alternatives to choose from


def cache_path(model: str):
    return common.OUTPUTS / "methods" / "gliner_candidates" / f"{model}.jsonl"


def load(accs: list[str], model: str) -> dict[str, list[dict]]:
    """accession -> candidate spans; computes and appends the missing filings."""
    path = cache_path(model)
    path.parent.mkdir(parents=True, exist_ok=True)
    cached = {}
    if path.exists():
        for line in path.read_text().splitlines():
            row = json.loads(line)
            cached[row["accession_number"]] = row["candidates"]
    missing = [a for a in accs if a not in cached]
    if missing:
        from gliner import GLiNER
        net = GLiNER.from_pretrained(str(common.MODELS / model / "final"))
        selector = Selector.load()
        labels = [label for label, _ in common.SPAN_FIELDS.values()]
        label_field = {label: field for field, (label, _) in common.SPAN_FIELDS.items()}
        with path.open("a") as fh:
            for n, acc in enumerate(missing, 1):
                text = common.filing_text(acc)
                cands = []
                for offset, chunk in selector.select(text, per_field=5, max_windows=50):
                    for ent in net.predict_entities(chunk, labels, threshold=THRESHOLD):
                        s, e = offset + ent["start"], offset + ent["end"]
                        cands.append({"field": label_field[ent["label"]], "value": ent["text"], "score": round(float(ent["score"]), 4),
                                      "start": s, "end": e, "context": text[max(0, s - 200):e + 200]})
                fh.write(json.dumps({"accession_number": acc, "candidates": cands}) + "\n")
                cached[acc] = cands
                if n % 10 == 0:
                    print(f"GLiNER candidates {n}/{len(missing)}", flush=True)
    return {a: cached[a] for a in accs}
