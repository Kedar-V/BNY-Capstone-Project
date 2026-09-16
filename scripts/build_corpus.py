#!/usr/bin/env python3
"""Build the public tender-offer EDA corpus from SEC EFTS metadata (+ optional doc sample)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eda.config import DEFAULT_END, DEFAULT_START, PROCESSED_DIR, RAW_DIR  # noqa: E402
from eda.corpus import (  # noqa: E402
    build_document_table,
    build_event_table,
    collect_efts_metadata,
    save_processed_tables,
)
from eda.documents import sample_documents_for_content  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--sample-per-form", type=int, default=8)
    parser.add_argument("--skip-sample", action="store_true")
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Collecting EFTS metadata {args.start} → {args.end} ...")
    meta = collect_efts_metadata(start=args.start, end=args.end)
    print(f"Collected {len(meta):,} document hits")

    docs = build_document_table(meta)
    events = build_event_table(docs)
    save_processed_tables(docs, events)
    print(f"Saved {len(docs):,} documents and {len(events):,} events to {PROCESSED_DIR}")

    if not args.skip_sample and not docs.empty:
        print(f"Downloading stratified content sample ({args.sample_per_form}/form) ...")
        sample = sample_documents_for_content(docs, n_per_form=args.sample_per_form)
        sample_path = PROCESSED_DIR / "content_sample.parquet"
        sample.to_parquet(sample_path, index=False)
        sample.to_csv(PROCESSED_DIR / "content_sample.csv", index=False)
        print(f"Saved content sample ({len(sample)} rows) → {sample_path}")
        print(sample["status"].value_counts().to_string())


if __name__ == "__main__":
    main()
