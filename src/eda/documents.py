"""Document characteristic analysis, including optional content sampling."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from bs4 import BeautifulSoup

from .config import CORPUS_DIR, FIGURES_DIR
from .sec_client import SecClient


def _approx_tokens(text: str) -> int:
    # Heuristic only: whitespace tokens, not a model tokenizer.
    return len(re.findall(r"\S+", text))


def _approx_pages(text: str, words: int) -> float:
    # Heuristic only: ~500 words/page for dense SEC HTML prose.
    if words <= 0:
        return 0.0
    return round(words / 500.0, 2)


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def detect_table_prevalence(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")
    text = soup.get_text(" ", strip=True)
    words = max(len(re.findall(r"\S+", text)), 1)
    table_text = " ".join(t.get_text(" ", strip=True) for t in tables)
    table_words = len(re.findall(r"\S+", table_text))
    return {
        "n_html_tables": len(tables),
        "table_word_share": round(table_words / words, 4),
        "narrative_word_share": round(1.0 - (table_words / words), 4),
    }


def analyze_format_availability(docs: pd.DataFrame) -> pd.DataFrame:
    return (
        docs.groupby(["form", "format_guess"], dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values(["form", "n"], ascending=[True, False])
    )


def find_duplicate_filenames(docs: pd.DataFrame) -> pd.DataFrame:
    """Exact duplicates by accession+filename (should be rare) and near-dup by filename across accessions."""
    exact = (
        docs.groupby(["accession", "filename"], dropna=False)
        .size()
        .reset_index(name="n")
        .query("n > 1")
    )
    by_name = (
        docs.dropna(subset=["filename"])
        .groupby("filename")
        .agg(n_rows=("hit_id", "size"), n_accessions=("accession", "nunique"))
        .reset_index()
        .query("n_accessions > 1")
        .sort_values("n_accessions", ascending=False)
    )
    return by_name


def sample_documents_for_content(
    docs: pd.DataFrame,
    n_per_form: int = 8,
    client: SecClient | None = None,
    cache_dir: Path | None = None,
) -> pd.DataFrame:
    """
    Download a stratified sample of primary HTML/text docs and compute length stats.

    Content-derived metrics are labeled as observed-from-sample.
    Missing downloads are recorded, not fabricated.
    """
    client = client or SecClient()
    cache_dir = cache_dir or (CORPUS_DIR / "sample_docs")
    cache_dir.mkdir(parents=True, exist_ok=True)

    candidates = docs[
        docs["filename"].notna()
        & docs["primary_cik"].notna()
        & docs["format_guess"].isin(["html", "text"])
        & (~docs["is_exhibit"] | docs["is_primary_form_doc"])
    ].copy()
    # Prefer primary form docs; fall back to non-exhibits.
    primary = candidates[candidates["is_primary_form_doc"]]
    if primary.empty:
        primary = candidates[~candidates["is_exhibit"]]
    if primary.empty:
        primary = candidates

    samples = (
        primary.sort_values("file_date")
        .groupby("form", group_keys=False)
        .head(n_per_form)
    )

    rows: list[dict[str, Any]] = []
    for _, row in samples.iterrows():
        cik = str(row["primary_cik"])
        accession = str(row["accession"])
        filename = str(row["filename"])
        url = client.document_url(cik, accession, filename)
        local = cache_dir / f"{accession}__{filename.replace('/', '_')}"
        status = "ok"
        text = ""
        html = ""
        error = None
        try:
            if local.exists():
                raw = local.read_bytes()
            else:
                raw = client.get_bytes(url)
                local.write_bytes(raw)
            if not raw or len(raw.strip()) == 0:
                status = "empty"
            else:
                html = raw.decode("utf-8", errors="replace")
                if row["format_guess"] == "html" or "<html" in html[:1000].lower():
                    text = html_to_text(html)
                    table_stats = detect_table_prevalence(html)
                else:
                    text = html
                    table_stats = {
                        "n_html_tables": pd.NA,
                        "table_word_share": pd.NA,
                        "narrative_word_share": pd.NA,
                    }
                if not text.strip():
                    status = "empty_after_parse"
        except Exception as exc:  # noqa: BLE001 - record failures explicitly
            status = "download_or_parse_failed"
            error = str(exc)
            table_stats = {
                "n_html_tables": pd.NA,
                "table_word_share": pd.NA,
                "narrative_word_share": pd.NA,
            }

        words = len(re.findall(r"\S+", text)) if text else 0
        rows.append(
            {
                "accession": accession,
                "filename": filename,
                "form": row["form"],
                "event_id": row["event_id"],
                "entity_name": row.get("entity_name"),
                "url": url,
                "local_path": str(local) if local.exists() else None,
                "status": status,
                "error": error,
                "bytes": local.stat().st_size if local.exists() else pd.NA,
                "chars": len(text),
                "words": words,
                "tokens_whitespace": _approx_tokens(text) if text else 0,
                "pages_approx_500w": _approx_pages(text, words),
                "content_sha1": hashlib.sha1(text.encode("utf-8")).hexdigest() if text else None,
                "n_html_tables": table_stats.get("n_html_tables"),
                "table_word_share": table_stats.get("table_word_share"),
                "narrative_word_share": table_stats.get("narrative_word_share"),
                "metric_source": "observed_sample",
            }
        )
    return pd.DataFrame(rows)


def analyze_documents(docs: pd.DataFrame, content_sample: pd.DataFrame | None = None) -> dict:
    format_dist = docs["format_guess"].value_counts(dropna=False).rename_axis("format").reset_index(name="n")
    by_form_format = analyze_format_availability(docs)
    missing = pd.DataFrame(
        {
            "field": ["filename", "primary_cik", "primary_file_num", "entity_name", "file_date"],
            "n_missing": [
                int(docs["filename"].isna().sum()),
                int(docs["primary_cik"].isna().sum()),
                int(docs["primary_file_num"].isna().sum()),
                int(docs["entity_name"].isna().sum()),
                int(docs["file_date"].isna().sum()),
            ],
            "pct_missing": [
                round(100 * docs["filename"].isna().mean(), 2),
                round(100 * docs["primary_cik"].isna().mean(), 2),
                round(100 * docs["primary_file_num"].isna().mean(), 2),
                round(100 * docs["entity_name"].isna().mean(), 2),
                round(100 * docs["file_date"].isna().mean(), 2),
            ],
        }
    )
    dup_filenames = find_duplicate_filenames(docs)

    out: dict[str, Any] = {
        "format_distribution": format_dist,
        "format_by_form": by_form_format,
        "missing_core_fields": missing,
        "duplicate_filenames_across_accessions": dup_filenames.head(25),
        "note": (
            "Page/word/token stats require document downloads. "
            "When content_sample is provided, length metrics are sample-observed only."
        ),
    }
    if content_sample is not None and not content_sample.empty:
        ok = content_sample[content_sample["status"] == "ok"]
        out["sample_status_counts"] = content_sample["status"].value_counts().rename_axis("status").reset_index(name="n")
        out["length_by_form"] = (
            ok.groupby("form")[["words", "tokens_whitespace", "pages_approx_500w", "n_html_tables", "table_word_share"]]
            .describe()
            if not ok.empty
            else pd.DataFrame()
        )
        out["near_duplicate_content"] = (
            ok.groupby("content_sha1")
            .agg(n=("accession", "size"), forms=("form", lambda s: sorted(set(s))), accessions=("accession", list))
            .reset_index()
            .query("n > 1")
        )
        out["content_sample"] = content_sample
    return out


def plot_format_distribution(docs: pd.DataFrame, save: bool = True) -> plt.Figure:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 4))
    order = docs["format_guess"].value_counts().index
    sns.countplot(data=docs, y="format_guess", order=order, ax=ax, color="#1f4e79")
    ax.set_title("Document format guess from filename extension")
    ax.set_xlabel("Documents")
    ax.set_ylabel("Format")
    fig.tight_layout()
    if save:
        fig.savefig(FIGURES_DIR / "format_distribution.png", dpi=150)
    return fig
