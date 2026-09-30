#!/usr/bin/env python3
"""Download diverse tender / 8-K sample PDFs (+ HTML) into data/samples/.

Layout (every folder):
  data/samples/{folder}/*.pdf
  data/samples/{folder}/html/*.htm

Folders: schedule_to, to_t, to_i, 14d9, amendments, offer_to_purchase, 8k,
plus 8k_exhibits (EX-* supporting docs for the sampled 8-K accessions).

Usage (from repo root):
  python dataloader/download_samples.py
  python dataloader/download_samples.py --n 30 --force
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eda.sec_client import SecClient  # noqa: E402

OUT = ROOT / "data" / "samples"
DOCS_PATH = ROOT / "data" / "processed" / "documents.parquet"
MANIFEST_PATH = OUT / "manifest.csv"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
OTP_RE = re.compile(r"offer\s+to\s+purchase", re.I)
FOLDERS = ["schedule_to", "to_t", "to_i", "14d9", "amendments", "offer_to_purchase", "8k"]


def diversify(pool: pd.DataFrame, n: int) -> pd.DataFrame:
    """Year-stratified, unique accession + entity when possible."""
    pool = pool.dropna(subset=["year"]).sort_values("file_date").drop_duplicates("accession", keep="first")
    years = sorted(pool["year"].unique())
    if not years:
        return pool.head(0)
    base, rem = divmod(n, len(years))
    picked_idx: list = []
    used_entities: set[str] = set()
    for i, y in enumerate(years):
        want = base + (1 if i < rem else 0)
        sub = pool[pool["year"] == y]
        chosen = []
        for idx, row in sub.iterrows():
            if len(chosen) >= want:
                break
            ek = row["entity_key"]
            if ek and ek in used_entities:
                continue
            chosen.append(idx)
            if ek:
                used_entities.add(ek)
        if len(chosen) < want:
            for idx, _ in sub.iterrows():
                if len(chosen) >= want:
                    break
                if idx not in chosen:
                    chosen.append(idx)
        if len(chosen) > want:
            step = len(chosen) / want
            chosen = [chosen[int(j * step)] for j in range(want)]
        picked_idx.extend(chosen)
    out = pool.loc[picked_idx]
    if len(out) < n:
        extra = pool[~pool.index.isin(out.index)]
        for idx, row in extra.iterrows():
            if len(out) >= n:
                break
            if row["entity_key"] and row["entity_key"] in set(out["entity_key"]):
                continue
            out = pd.concat([out, row.to_frame().T])
        if len(out) < n:
            out = pd.concat([out, pool[~pool.index.isin(out.index)].head(n - len(out))])
    return out.head(n)


def save_doc(
    client: SecClient,
    *,
    cik: str,
    accession: str,
    filename: str,
    dest: Path,
    force: bool,
    chrome: Path,
) -> dict:
    html_dir = dest / "html"
    dest.mkdir(parents=True, exist_ok=True)
    html_dir.mkdir(parents=True, exist_ok=True)
    url = client.document_url(cik, accession, filename)
    stem = f"{accession}__{filename.replace('/', '_')}"
    stem_base = stem.rsplit(".", 1)[0] if stem.lower().endswith((".htm", ".html")) else stem
    html_path = html_dir / f"{stem_base}.htm"
    pdf_path = dest / f"{stem_base}.pdf"
    status, err = "ok", None
    try:
        need_html = force or not html_path.exists() or html_path.stat().st_size < 100
        need_pdf = force or not pdf_path.exists() or pdf_path.stat().st_size < 1000
        if not need_html and not need_pdf:
            status = "skipped"
        else:
            raw = client.get_bytes(url)
            if need_html or not html_path.exists():
                html_path.write_bytes(raw)
            if need_pdf:
                subprocess.run(
                    [
                        str(chrome),
                        "--headless",
                        "--disable-gpu",
                        "--no-pdf-header-footer",
                        f"--print-to-pdf={pdf_path}",
                        f"file://{html_path.resolve()}",
                    ],
                    check=True,
                    capture_output=True,
                )
                if not pdf_path.exists() or pdf_path.stat().st_size < 1000:
                    raise RuntimeError("pdf missing/too small")
    except Exception as exc:  # noqa: BLE001
        status, err = "failed", str(exc)
        print(f"  FAIL {accession} {filename}: {exc}")
    return {
        "url": url,
        "local_path": str(pdf_path) if pdf_path.exists() else None,
        "html_path": str(html_path) if html_path.exists() else None,
        "bytes": pdf_path.stat().st_size if pdf_path.exists() else None,
        "html_bytes": html_path.stat().st_size if html_path.exists() else None,
        "status": status,
        "error": err,
    }


def build_picks(docs: pd.DataFrame, n: int) -> dict[str, pd.DataFrame]:
    def primary(form_or_forms) -> pd.DataFrame:
        forms = [form_or_forms] if isinstance(form_or_forms, str) else list(form_or_forms)
        return docs[(docs["form"].isin(forms)) & (docs["is_primary_form_doc"] == True)]

    otp = docs[docs["file_description"].fillna("").astype(str).str.contains(OTP_RE, na=False)].copy()
    otp_t = diversify(
        otp[otp["form"].isin(["SC TO-T", "SC TO-T/A"])],
        min(15, otp[otp["form"].isin(["SC TO-T", "SC TO-T/A"])]["accession"].nunique()),
    )
    otp_i = diversify(otp[otp["form"].isin(["SC TO-I", "SC TO-I/A"])], n - len(otp_t))
    return {
        "schedule_to": pd.concat([diversify(primary("SC TO-T"), 15), diversify(primary("SC TO-I"), 15)]),
        "to_t": diversify(primary("SC TO-T"), n),
        "to_i": diversify(primary("SC TO-I"), n),
        "14d9": diversify(primary("SC 14D9"), n),
        "amendments": pd.concat(
            [
                diversify(primary("SC TO-T/A"), 10),
                diversify(primary("SC TO-I/A"), 10),
                diversify(primary("SC 14D9/A"), 10),
            ]
        ),
        "offer_to_purchase": pd.concat([otp_t, otp_i]).head(n),
        "8k": diversify(primary("8-K"), n),
    }


def run(*, n: int = 30, force: bool = False, chrome: Path = CHROME) -> Path:
    if not DOCS_PATH.exists():
        raise SystemExit(f"Missing {DOCS_PATH} — run: python scripts/build_corpus.py")
    if not chrome.exists():
        raise SystemExit(f"Chrome not found at {chrome}")

    docs = pd.read_parquet(DOCS_PATH)
    docs = docs[docs["filename"].notna() & docs["primary_cik"].notna()].copy()
    docs = docs[docs["format_guess"].isin(["html", "text"])]
    docs["year"] = pd.to_datetime(docs["file_date"], errors="coerce").dt.year
    docs["entity_key"] = docs["entity_name"].fillna("").astype(str).str.lower().str.strip()

    picks = build_picks(docs, n)
    for folder, sample in picks.items():
        print(
            f"{folder:20s} n={len(sample):2d}  "
            f"entities={sample['entity_key'].nunique():2d}  "
            f"years={dict(sorted(sample['year'].value_counts().items()))}"
        )

    client = SecClient()
    print(f"SEC User-Agent: {client.user_agent}")
    manifest: list[dict] = []

    for folder in FOLDERS:
        dest = OUT / folder
        if force and dest.exists():
            shutil.rmtree(dest)
        sample = picks[folder]
        print(f"\n== {folder}: {len(sample)} ==")
        for _, row in sample.iterrows():
            cik = str(int(str(row["primary_cik"])))
            acc = str(row["accession"])
            fn = str(row["filename"])
            meta = save_doc(client, cik=cik, accession=acc, filename=fn, dest=dest, force=force, chrome=chrome)
            manifest.append(
                {
                    "folder": folder,
                    "form": row["form"],
                    "year": int(row["year"]) if pd.notna(row["year"]) else None,
                    "accession": acc,
                    "filename": fn,
                    "entity_name": row.get("entity_name"),
                    "file_date": str(row.get("file_date")),
                    "file_description": row.get("file_description"),
                    "file_type": row.get("file_type"),
                    "doc_role": "primary",
                    **meta,
                }
            )

    ex_dest = OUT / "8k_exhibits"
    if force and ex_dest.exists():
        shutil.rmtree(ex_dest)
    ex_accs = set(picks["8k"]["accession"].astype(str))
    exhibits = docs[
        docs["accession"].isin(ex_accs)
        & docs["filename"].notna()
        & docs["primary_cik"].notna()
        & docs["format_guess"].isin(["html", "text"])
        & (
            (docs["is_exhibit"] == True)
            | docs["file_type"].fillna("").astype(str).str.upper().str.startswith("EX-")
        )
    ].copy()
    exhibits = exhibits[~exhibits["file_type"].fillna("").astype(str).str.upper().str.startswith("EX-101")]
    exhibits = exhibits.drop_duplicates(["accession", "filename"])
    print(f"\n== 8k_exhibits: {len(exhibits)} docs across {exhibits['accession'].nunique()} filings ==")
    for _, row in exhibits.iterrows():
        cik = str(int(str(row["primary_cik"])))
        acc = str(row["accession"])
        fn = str(row["filename"])
        meta = save_doc(client, cik=cik, accession=acc, filename=fn, dest=ex_dest, force=force, chrome=chrome)
        y = pd.to_datetime(row.get("file_date"), errors="coerce")
        manifest.append(
            {
                "folder": "8k_exhibits",
                "form": row["form"],
                "year": int(y.year) if pd.notna(y) else None,
                "accession": acc,
                "filename": fn,
                "entity_name": row.get("entity_name"),
                "file_date": str(row.get("file_date")),
                "file_description": row.get("file_description"),
                "file_type": row.get("file_type"),
                "doc_role": "exhibit",
                **meta,
            }
        )

    mf = pd.DataFrame(manifest)
    OUT.mkdir(parents=True, exist_ok=True)
    mf.to_csv(MANIFEST_PATH, index=False)
    print("\nWrote", MANIFEST_PATH)
    print(mf.groupby(["folder", "status"]).size().unstack(fill_value=0))
    return MANIFEST_PATH


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n", type=int, default=30, help="samples per primary folder (default 30)")
    p.add_argument("--force", action="store_true", help="wipe and re-download")
    p.add_argument("--chrome", type=Path, default=CHROME, help="path to Chrome binary")
    args = p.parse_args()
    run(n=args.n, force=args.force, chrome=args.chrome)


if __name__ == "__main__":
    main()
