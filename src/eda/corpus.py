"""Corpus construction and loading helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from .config import (
    AMENDMENT_FORMS,
    COLLECTION_TRACKS,
    CORPUS_DIR,
    DEFAULT_END,
    DEFAULT_START,
    EFTS_BROAD_QUERY,
    FORM_FAMILIES,
    PROCESSED_DIR,
    RAW_DIR,
    TENDER_FORMS,
)
from .sec_client import SecClient


def _parse_display_name(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {"entity_name": None, "tickers": [], "cik_from_name": None}
    # Example: "PureTech Health plc  (PRTC, PTCHF)  (CIK 0001782999)"
    cik_m = re.search(r"\(CIK\s+(\d+)\)", raw)
    ticker_m = re.search(r"\(([^)]+)\)\s+\(CIK", raw)
    name = re.split(r"\s+\(", raw, maxsplit=1)[0].strip()
    tickers = []
    if ticker_m:
        tickers = [t.strip() for t in ticker_m.group(1).split(",") if t.strip()]
    return {
        "entity_name": name or None,
        "tickers": tickers,
        "cik_from_name": cik_m.group(1) if cik_m else None,
    }


def _filename_from_hit_id(hit_id: str, adsh: str) -> str | None:
    # EFTS _id format: "{adsh}:{filename}"
    prefix = f"{adsh}:"
    if hit_id.startswith(prefix):
        return hit_id[len(prefix) :]
    if ":" in hit_id:
        return hit_id.split(":", 1)[1]
    return None


def hit_to_record(hit: dict[str, Any]) -> dict[str, Any]:
    src = hit.get("_source", {})
    adsh = src.get("adsh")
    filename = _filename_from_hit_id(hit.get("_id", ""), adsh or "")
    display_names = src.get("display_names") or []
    parsed = _parse_display_name(display_names[0] if display_names else None)
    ciks = src.get("ciks") or []
    file_nums = src.get("file_num") or []
    form = src.get("form")
    file_type = src.get("file_type") or ""
    is_amendment = form in AMENDMENT_FORMS or str(form).endswith("/A")
    is_exhibit = str(file_type).upper().startswith("EX-") or "EXHIBIT" in (
        src.get("file_description") or ""
    ).upper()
    primary_cik = ciks[0] if ciks else parsed.get("cik_from_name")
    primary_file_num = file_nums[0] if file_nums else None
    return {
        "hit_id": hit.get("_id"),
        "accession": adsh,
        "filename": filename,
        "form": form,
        "root_forms": src.get("root_forms"),
        "form_family": FORM_FAMILIES.get(form, "other"),
        "file_type": file_type,
        "file_description": src.get("file_description"),
        "file_date": src.get("file_date"),
        "sequence": src.get("sequence"),
        "ciks": ciks,
        "primary_cik": primary_cik,
        "display_names": display_names,
        "entity_name": parsed["entity_name"],
        "tickers": parsed["tickers"],
        "file_nums": file_nums,
        "primary_file_num": primary_file_num,
        "biz_states": src.get("biz_states"),
        "inc_states": src.get("inc_states"),
        "sics": src.get("sics"),
        "xsl": src.get("xsl"),
        "is_amendment": is_amendment,
        "is_exhibit": is_exhibit,
        "is_primary_form_doc": (not is_exhibit)
        and bool(file_type)
        and (
            file_type == form
            or file_type.replace("-", "") == str(form).replace("-", "").replace(" ", "")
        ),
    }


def collect_efts_metadata(
    start: str = DEFAULT_START,
    end: str = DEFAULT_END,
    forms: list[str] | None = None,
    client: SecClient | None = None,
    out_path: Path | None = None,
    checkpoint_path: Path | None = None,
    tracks: list[str] | None = None,
    q: str | None = None,
) -> pd.DataFrame:
    """
    Collect EFTS document-level metadata for MVP collection tracks.

    Prefer `tracks` (tender / merger_exchange / rights / conversion). Legacy
    `forms=` still works as a single ad-hoc track.
    """
    client = client or SecClient()
    tracks = tracks or (["tender"] if forms is None else ["custom"])
    checkpoint_path = checkpoint_path or (RAW_DIR / "efts_collection_checkpoint.json")
    jsonl_path = RAW_DIR / "efts_mvp_metadata.jsonl"
    legacy_jsonl = RAW_DIR / "efts_tender_metadata.jsonl"
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    # Build work items: (track, form, q)
    work: list[tuple[str, str, str, tuple[str, ...]]] = []
    for track_name in tracks:
        if track_name == "custom":
            form_list = forms or TENDER_FORMS
            # Strip /A — EFTS returns amendments with the base form.
            bases = []
            for f in form_list:
                base = f[:-2] if str(f).endswith("/A") else f
                if base not in bases:
                    bases.append(base)
            for form in bases:
                work.append(("custom", form, q or EFTS_BROAD_QUERY, ("custom",)))
            continue
        if track_name not in COLLECTION_TRACKS:
            raise ValueError(f"Unknown track {track_name!r}. Choose from {sorted(COLLECTION_TRACKS)}")
        spec = COLLECTION_TRACKS[track_name]
        for form in spec["forms"]:
            work.append(
                (
                    track_name,
                    form,
                    spec["q"],
                    tuple(spec.get("mvp_event_types", [])),
                )
            )

    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    done_windows: set[str] = set()

    # Seed from prior MVP + legacy tender jsonl so we do not re-download.
    for path in (jsonl_path, legacy_jsonl):
        if not path.exists():
            continue
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                row = json.loads(line)
                hit_id = row.get("hit_id")
                if hit_id and hit_id not in seen_ids:
                    seen_ids.add(hit_id)
                    if "collection_track" not in row:
                        row["collection_track"] = "tender"
                    records.append(row)

    if checkpoint_path.exists():
        done_windows = set(json.loads(checkpoint_path.read_text(encoding="utf-8")).get("done_windows", []))

    with jsonl_path.open("a", encoding="utf-8") as fh:
        for track_name, form, query, mvp_types in work:
            for win_start, win_end in client.iter_month_windows(start, end):
                key = f"{track_name}|{form}|{win_start}|{win_end}"
                # Also honor legacy tender checkpoint keys: "SC TO-T|2020-01-01|..."
                legacy_key = f"{form}|{win_start}|{win_end}"
                if key in done_windows or (track_name == "tender" and legacy_key in done_windows):
                    continue
                hits = client.efts_paginate(
                    q=query,
                    forms=form,
                    start=win_start,
                    end=win_end,
                )
                for hit in hits:
                    hit_id = hit.get("_id")
                    if not hit_id or hit_id in seen_ids:
                        continue
                    seen_ids.add(hit_id)
                    rec = hit_to_record(hit)
                    rec["collection_track"] = track_name
                    rec["efts_query"] = query
                    rec["mvp_event_types"] = list(mvp_types)
                    records.append(rec)
                    fh.write(json.dumps(rec, default=str) + "\n")
                done_windows.add(key)
                checkpoint_path.write_text(
                    json.dumps({"done_windows": sorted(done_windows)}, indent=2),
                    encoding="utf-8",
                )
                print(f"  collected {key} (+{len(hits)} hits, total={len(records)})")

    df = pd.DataFrame.from_records(records)
    if not df.empty:
        df["file_date"] = pd.to_datetime(df["file_date"], errors="coerce")
        if "hit_id" in df.columns:
            df = df.drop_duplicates(subset=["hit_id"], keep="last")
        if "sequence" in df.columns:
            df["sequence"] = pd.to_numeric(df["sequence"], errors="coerce")
        for col in ("is_amendment", "is_exhibit", "is_primary_form_doc"):
            if col in df.columns:
                df[col] = df[col].astype("boolean")
        for col in (
            "ciks",
            "display_names",
            "tickers",
            "file_nums",
            "biz_states",
            "inc_states",
            "sics",
            "root_forms",
            "mvp_event_types",
        ):
            if col in df.columns:
                df[col] = df[col].apply(
                    lambda x: list(x)
                    if isinstance(x, (list, tuple))
                    else ([] if (x is None or (isinstance(x, float) and pd.isna(x))) else [x])
                )
    out_path = out_path or (RAW_DIR / "efts_mvp_metadata.parquet")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix == ".parquet":
        df.to_parquet(out_path, index=False)
    else:
        df.to_json(out_path, orient="records", date_format="iso")
    # Keep legacy tender parquet in sync for older loaders.
    tender_out = RAW_DIR / "efts_tender_metadata.parquet"
    if not df.empty and "form" in df.columns:
        tender_mask = df["form"].astype(str).str.startswith(("SC TO-", "SC 14D9"))
        df.loc[tender_mask].to_parquet(tender_out, index=False)
    return df


def build_document_table(meta: pd.DataFrame) -> pd.DataFrame:
    docs = meta.copy()
    if docs.empty:
        return docs
    docs["event_id"] = docs["primary_file_num"].fillna("NO_FILE_NUM:" + docs["accession"].astype(str))
    docs["doc_ext"] = docs["filename"].fillna("").str.lower().str.extract(r"(\.[a-z0-9]+)$", expand=False)
    docs["format_guess"] = docs["doc_ext"].map(
        {
            ".htm": "html",
            ".html": "html",
            ".txt": "text",
            ".pdf": "pdf",
            ".xml": "xml",
            ".xsd": "xml",
            ".jpg": "image",
            ".jpeg": "image",
            ".png": "image",
            ".gif": "image",
        }
    ).fillna("other")
    return docs


def build_event_table(docs: pd.DataFrame) -> pd.DataFrame:
    if docs.empty:
        return pd.DataFrame()

    def _agg(g: pd.DataFrame) -> pd.Series:
        forms = sorted(set(g["form"].dropna()))
        families = sorted(set(g["form_family"].dropna()))
        names = [n for n in g["entity_name"].dropna().unique().tolist() if n]
        ciks = sorted({c for vals in g["ciks"].dropna() for c in (vals if isinstance(vals, list) else [vals])})
        tickers = sorted({t for vals in g["tickers"].dropna() for t in (vals if isinstance(vals, list) else [])})
        file_dates = g["file_date"].dropna().sort_values()
        n_amend_filings = g.loc[g["is_amendment"], "accession"].nunique()
        n_initial_filings = g.loc[~g["is_amendment"], "accession"].nunique()
        return pd.Series(
            {
                "n_documents": len(g),
                "n_filings": g["accession"].nunique(),
                "n_amendment_filings": n_amend_filings,
                "n_initial_filings": n_initial_filings,
                "has_amendment": n_amend_filings > 0,
                "forms": forms,
                "form_families": families,
                "primary_form_family": families[0] if len(families) == 1 else ("mixed" if families else None),
                "entity_names": names,
                "primary_entity": names[0] if names else None,
                "ciks": ciks,
                "primary_cik": ciks[0] if ciks else None,
                "tickers": tickers,
                "first_file_date": file_dates.iloc[0] if len(file_dates) else pd.NaT,
                "last_file_date": file_dates.iloc[-1] if len(file_dates) else pd.NaT,
                "event_span_days": (
                    (file_dates.iloc[-1] - file_dates.iloc[0]).days if len(file_dates) else pd.NA
                ),
                "n_exhibits": int(g["is_exhibit"].sum()),
                "n_primary_docs": int(g["is_primary_form_doc"].sum()),
            }
        )

    events = docs.groupby("event_id", dropna=False).apply(_agg, include_groups=False).reset_index()
    return events


def save_processed_tables(docs: pd.DataFrame, events: pd.DataFrame) -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    docs.to_parquet(PROCESSED_DIR / "documents.parquet", index=False)
    events.to_parquet(PROCESSED_DIR / "events.parquet", index=False)
    docs.to_csv(PROCESSED_DIR / "documents.csv", index=False)
    events.to_csv(PROCESSED_DIR / "events.csv", index=False)


def load_corpus(
    docs_path: Path | None = None,
    events_path: Path | None = None,
    meta_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load processed tables, rebuilding from raw metadata if needed."""
    docs_path = docs_path or (PROCESSED_DIR / "documents.parquet")
    events_path = events_path or (PROCESSED_DIR / "events.parquet")
    if docs_path.exists() and events_path.exists():
        docs = pd.read_parquet(docs_path)
        events = pd.read_parquet(events_path)
        if "file_date" in docs.columns:
            docs["file_date"] = pd.to_datetime(docs["file_date"], errors="coerce")
        for col in ("first_file_date", "last_file_date"):
            if col in events.columns:
                events[col] = pd.to_datetime(events[col], errors="coerce")
        return docs, events

    meta_path = meta_path or (RAW_DIR / "efts_mvp_metadata.parquet")
    if not meta_path.exists():
        legacy = RAW_DIR / "efts_tender_metadata.parquet"
        if legacy.exists():
            meta_path = legacy
    if not meta_path.exists():
        jsonl = RAW_DIR / "efts_mvp_metadata.jsonl"
        if not jsonl.exists():
            jsonl = RAW_DIR / "efts_tender_metadata.jsonl"
        if not jsonl.exists():
            raise FileNotFoundError(
                "No corpus found. Run scripts/build_corpus.py first "
                f"(looked for efts_mvp_metadata / efts_tender_metadata under {RAW_DIR})."
            )
        meta = pd.read_json(jsonl, lines=True)
        if "file_date" in meta.columns:
            meta["file_date"] = pd.to_datetime(meta["file_date"], errors="coerce")
    else:
        meta = pd.read_parquet(meta_path)
        if "file_date" in meta.columns:
            meta["file_date"] = pd.to_datetime(meta["file_date"], errors="coerce")

    docs = build_document_table(meta)
    events = build_event_table(docs)
    save_processed_tables(docs, events)
    return docs, events
