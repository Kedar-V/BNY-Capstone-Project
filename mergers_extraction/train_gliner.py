#!/usr/bin/env python3
"""Fine-tune GLiNER on the merger training data from build_training_data.py.

Adapted from scripts/train_tender_gliner.py (same optimiser settings). Trains on train.jsonl and reports loss on
holdout.jsonl; the held-out deals are never trained on. Weights go to models/merger_gliner/<name>/final (gitignored).

    python mergers_extraction/train_gliner.py                      # 500 steps from gliner_medium-v2.1
    python mergers_extraction/train_gliner.py --max-steps 100 --name smoke_test
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import common


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", type=Path, default=common.TRAINING_DATA)
    ap.add_argument("--base-model", default=common.BASE_MODEL)
    ap.add_argument("--name", default="medium_500steps")
    ap.add_argument("--max-steps", type=int, default=500)
    ap.add_argument("--batch-size", type=int, default=2)
    ap.add_argument("--lr", type=float, default=5e-6)
    ap.add_argument("--use-cpu", action="store_true", help="skip the Mac GPU (MPS) if training fails on it")
    ap.add_argument("--exclude-validation", action="store_true",
                    help="leave out the validation deals (common.validation_accessions) so checkpoints can be chosen on them")
    ap.add_argument("--save-steps", type=int, default=None, help="save a checkpoint every N steps (default: half the run)")
    ap.add_argument("--eval-loss", action="store_true",
                    help="also report holdout loss during training (uses extra GPU memory that the Mac does not free; "
                         "the real holdout evaluation is gliner_finetuned_eval.py)")
    args = ap.parse_args()

    train = load_jsonl(args.data / "train.jsonl")
    validation = set(common.validation_accessions()) if args.exclude_validation else set()
    train = [x for x in train if x["accession"] not in validation]
    holdout = load_jsonl(args.data / "holdout.jsonl")
    labels = [label for label, _ in common.SPAN_FIELDS.values()]

    def slim(xs: list[dict]) -> list[dict]:
        """Every passage carries all field labels (as at inference), so a passage with no values teaches the
        model that none of the fields is present. Without this GLiNER fails on a batch of only negatives."""
        out = []
        for i, x in enumerate(xs):
            order = labels[:]
            random.Random(i).shuffle(order)
            out.append({"tokenized_text": x["tokenized_text"], "ner": x["ner"], "ner_labels": order})
        return out
    out = common.MODELS / args.name
    meta = {"base_model": args.base_model, "data": str(args.data), "max_steps": args.max_steps,
            "batch_size": args.batch_size, "lr": args.lr, "validation_filings_excluded": len(validation),
            "train_examples": len(train), "train_spans": sum(len(x["ner"]) for x in train),
            "holdout_examples": len(holdout), "holdout_spans": sum(len(x["ner"]) for x in holdout),
            "training_data_summary": json.loads((args.data / "summary.json").read_text())}
    print(json.dumps({k: v for k, v in meta.items() if k != "training_data_summary"}, indent=2))

    from gliner import GLiNER
    model = GLiNER.from_pretrained(args.base_model)
    started = time.time()
    out.mkdir(parents=True, exist_ok=True)
    trainer = model.train_model(
        train_dataset=slim(train),
        eval_dataset=slim(holdout),
        output_dir=str(out),
        learning_rate=args.lr,
        weight_decay=0.01,
        others_lr=1e-5,
        others_weight_decay=0.01,
        lr_scheduler_type="linear",
        warmup_ratio=0.1,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        focal_loss_alpha=0.75,
        focal_loss_gamma=2,
        max_steps=args.max_steps,
        save_steps=args.save_steps or max(100, args.max_steps // 2),
        save_total_limit=None,
        save_only_model=True,
        logging_steps=25,
        eval_strategy="steps" if args.eval_loss else "no",
        eval_steps=max(50, args.max_steps // 5),
        dataloader_num_workers=0,
        use_cpu=args.use_cpu,
        report_to="none",
    )
    model.save_pretrained(str(out / "final"))
    history = getattr(getattr(trainer, "state", None), "log_history", []) or []
    meta.update({"train_seconds": round(time.time() - started),
                 "loss_history": [{k: v for k, v in h.items() if k in ("step", "loss", "eval_loss")} for h in history]})
    (out / "train_meta.json").write_text(json.dumps(meta, indent=2))
    print(f"saved {out / 'final'} in {meta['train_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
