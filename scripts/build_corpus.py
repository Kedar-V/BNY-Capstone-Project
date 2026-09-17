#!/usr/bin/env python3
"""Build the public MVP corporate-action corpus from SEC EFTS metadata (+ optional doc sample).

Tracks:
  tender           — SC TO-T / SC TO-I / SC 14D9
  merger_exchange  — S-4 / DEFM14A / PREM14A / SC 13E3 / 425
  rights           — 424B* filtered to rights-offering language
  conversion       — 8-K filtered to conversion language
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eda.config import (  # noqa: E402
    COLLECTION_TRACKS,
    DEFAULT_END,
    DEFAULT_START,
    PROCESSED_DIR,
    RAW_DIR,
)
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
    parser.add_argument(
        "--tracks",
        default="merger_exchange,rights,conversion",
        help=(
            "Comma-separated tracks to collect. "
            f"Choices: {', '.join(sorted(COLLECTION_TRACKS))} or 'all'. "
            "Default skips tender (already collected)."
        ),
    )
    parser.add_argument("--sample-per-form", type=int, default=6)
    parser.add_argument("--skip-sample", action="store_true")
    parser.add_argument(
        "--rebuild-only",
        action="store_true",
        help="Skip EFTS collection; rebuild processed tables from existing raw metadata.",
    )
    args = parser.parse_args()

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    if args.tracks.strip().lower() == "all":
        tracks = list(COLLECTION_TRACKS.keys())
    else:
        tracks = [t.strip() for t in args.tracks.split(",") if t.strip()]

    if not args.rebuild_only:
        print(f"Collecting EFTS metadata {args.start} → {args.end} tracks={tracks} ...")
        meta = collect_efts_metadata(start=args.start, end=args.end, tracks=tracks)
    else:
        mvp_path = RAW_DIR / "efts_mvp_metadata.parquet"
        tender_path = RAW_DIR / "efts_tender_metadata.parquet"
        if mvp_path.exists():
            import pandas as pd

            meta = pd.read_parquet(mvp_path)
        elif tender_path.exists():
            import pandas as pd

            meta = pd.read_parquet(tender_path)
        else:
            raise SystemExit("No raw metadata found. Run without --rebuild-only first.")

    print(f"Collected/loaded {len(meta):,} document hits")

    docs = build_document_table(meta)
    events = build_event_table(docs)
    save_processed_tables(docs, events)
    print(f"Saved {len(docs):,} documents and {len(events):,} events to {PROCESSED_DIR}")
    if "form" in docs.columns:
        print("Form counts:")
        print(docs["form"].value_counts(dropna=False).head(30).to_string())

    if not args.skip_sample and not docs.empty:
        # Stratify across newly relevant forms when present.
        target_forms = [
            "S-4",
            "S-4/A",
            "DEFM14A",
            "PREM14A",
            "SC 13E3",
            "SC 13E3/A",
            "425",
            "424B2",
            "424B3",
            "424B5",
            "8-K",
            "SC TO-T",
            "SC TO-T/A",
            "SC 14D9",
        ]
        present = [f for f in target_forms if f in set(docs["form"].dropna().astype(str))]
        subset = docs[docs["form"].isin(present)].copy() if present else docs
        print(f"Downloading stratified content sample ({args.sample_per_form}/form) over {len(present)} forms ...")
        sample = sample_documents_for_content(subset, n_per_form=args.sample_per_form)
        sample_path = PROCESSED_DIR / "content_sample.parquet"
        sample.to_parquet(sample_path, index=False)
        sample.to_csv(PROCESSED_DIR / "content_sample.csv", index=False)
        print(f"Saved content sample ({len(sample)} rows) → {sample_path}")
        print(sample["status"].value_counts().to_string())


if __name__ == "__main__":
    main()
