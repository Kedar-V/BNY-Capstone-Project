"""End-to-end runner that writes outputs/ artifacts for the BNY schema EDA."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from eda.amendments import analyze_amendments
from eda.config import FIGURES_DIR, PROCESSED_DIR
from eda.corpus import load_corpus
from eda.documents import analyze_documents, plot_format_distribution, sample_documents_for_content
from eda.events import analyze_events, plot_event_distributions
from eda.missingness import classify_missingness, ground_truth_recommendations
from eda.mvp import recommend_mvp_design
from eda.overview import overview_tables, plot_form_distribution, plot_temporal_volume, summarize_dataset
from eda.quality import analyze_data_quality
from eda.schema_coverage import analyze_schema_coverage


OUTPUTS = ROOT / "outputs"


def stratified_sample(docs: pd.DataFrame, n_per_form: int = 10) -> pd.DataFrame:
    """Prefer primary HTML docs, fall back to non-exhibit HTML/text per form."""
    c = docs[
        docs["filename"].notna()
        & docs["primary_cik"].notna()
        & docs["format_guess"].isin(["html", "text"])
    ].copy()
    c["priority"] = c["is_primary_form_doc"].astype(int) * 2 + (~c["is_exhibit"]).astype(int)
    c = c.sort_values(["form", "priority", "file_date"], ascending=[True, False, True])
    picks = c.groupby("form", group_keys=False).head(n_per_form)
    subset = docs[docs["hit_id"].isin(picks["hit_id"])].copy()
    subset["is_primary_form_doc"] = True
    subset["is_exhibit"] = False
    return sample_documents_for_content(subset, n_per_form=n_per_form)


def main() -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS / "figures").mkdir(parents=True, exist_ok=True)

    docs, events = load_corpus()
    print(f"Loaded docs={len(docs):,} events={len(events):,}")

    sample_path = PROCESSED_DIR / "content_sample.parquet"
    if sample_path.exists():
        content_sample = pd.read_parquet(sample_path)
        if content_sample["form"].nunique() < 4 or len(content_sample) < 20:
            print("Refreshing content sample for broader form coverage...")
            content_sample = stratified_sample(docs, n_per_form=10)
            content_sample.to_parquet(sample_path, index=False)
    else:
        content_sample = stratified_sample(docs, n_per_form=10)
        content_sample.to_parquet(sample_path, index=False)
    content_sample.to_csv(OUTPUTS / "content_sample.csv", index=False)

    overview = summarize_dataset(docs, events)
    tables = overview_tables(docs, events)
    event_stats = analyze_events(docs, events)
    doc_stats = analyze_documents(docs, content_sample)
    coverage = analyze_schema_coverage(docs, events, content_sample)
    amend_stats = analyze_amendments(docs, events, content_sample)
    quality = analyze_data_quality(docs, events)
    missingness = classify_missingness(coverage["schema_coverage"], coverage["event_type_coverage"])
    gt = ground_truth_recommendations(coverage["schema_coverage"])
    mvp = recommend_mvp_design(docs, events, coverage["schema_coverage"].rename(columns={"public_coverage_pct": "pct_detected", "field": "field"}))

    # Plots
    plot_form_distribution(docs)
    plot_temporal_volume(docs)
    plot_event_distributions(events)
    plot_format_distribution(docs)

    cov = coverage["schema_coverage"].dropna(subset=["public_coverage_pct"])
    if not cov.empty:
        fig, ax = plt.subplots(figsize=(10, 10))
        plot_df = cov.sort_values("public_coverage_pct", ascending=True)
        sns.barplot(data=plot_df, y="field", x="public_coverage_pct", hue="group", dodge=False, ax=ax)
        ax.set_xlim(0, 100)
        ax.set_xlabel("Public coverage %")
        ax.set_title("BNY schema field coverage from public documents")
        fig.tight_layout()
        fig.savefig(OUTPUTS / "figures" / "schema_coverage.png", dpi=150)
        fig.savefig(FIGURES_DIR / "schema_coverage.png", dpi=150)
        plt.close(fig)

    etc = coverage["event_type_coverage"]
    if not etc.empty:
        pivot = etc.pivot_table(index="field", columns="corporate_action_type", values="coverage_pct")
        fig, ax = plt.subplots(figsize=(10, 12))
        sns.heatmap(pivot, annot=False, cmap="Blues", ax=ax, vmin=0, vmax=100)
        ax.set_title("Coverage by corporate_action_type × field (sample)")
        fig.tight_layout()
        fig.savefig(OUTPUTS / "figures" / "event_type_coverage_heatmap.png", dpi=150)
        plt.close(fig)

    # Required CSVs
    coverage["schema_coverage"].to_csv(OUTPUTS / "schema_coverage.csv", index=False)
    coverage["event_type_coverage"].to_csv(OUTPUTS / "event_type_coverage.csv", index=False)

    dq_parts = [
        quality["missing_metadata"].assign(section="missing_metadata"),
        quality["leakage_risks"].assign(section="leakage_risks"),
        missingness.assign(section="missingness_taxonomy"),
        doc_stats["format_distribution"].assign(section="format_distribution"),
        doc_stats["sample_status_counts"].assign(section="sample_download_status")
        if isinstance(doc_stats.get("sample_status_counts"), pd.DataFrame)
        else pd.DataFrame(),
    ]
    data_quality = pd.concat(dq_parts, ignore_index=True, sort=False)
    data_quality.to_csv(OUTPUTS / "data_quality_report.csv", index=False)

    tables["summary"].to_csv(OUTPUTS / "dataset_overview.csv", index=False)
    tables["form_counts"].to_csv(OUTPUTS / "form_counts.csv", index=False)
    events.to_csv(OUTPUTS / "events.csv", index=False)
    gt.to_csv(OUTPUTS / "ground_truth_feasibility.csv", index=False)
    event_stats["unusual_document_volume"].to_csv(OUTPUTS / "unusual_document_volume.csv", index=False)
    event_stats["unusual_amendment_volume"].to_csv(OUTPUTS / "unusual_amendment_volume.csv", index=False)
    amend_stats["simple_amendment_examples"].to_csv(OUTPUTS / "simple_amendment_examples.csv", index=False)
    amend_stats["complex_amendment_examples"].to_csv(OUTPUTS / "complex_amendment_examples.csv", index=False)
    if isinstance(amend_stats.get("field_presence_delta_summary"), pd.DataFrame):
        amend_stats["field_presence_delta_summary"].to_csv(OUTPUTS / "amendment_field_deltas.csv", index=False)

    # Copy figures into outputs/
    for p in FIGURES_DIR.glob("*.png"):
        target = OUTPUTS / "figures" / p.name
        target.write_bytes(p.read_bytes())

    summary_stats = {
        "n_documents": int(len(docs)),
        "n_filings": int(docs["accession"].nunique()),
        "n_events": int(len(events)),
        "date_min": overview["date_min"],
        "date_max": overview["date_max"],
        "pct_events_with_amendments": overview["pct_events_with_amendments"],
        "n_sample_events_for_text_coverage": coverage["n_sample_events"],
        "coverage_note": coverage["note"],
        "mvp_event_count": mvp.get("mvp_event_count"),
        "amendment_eval_simple_count": mvp.get("amendment_eval_simple_count"),
        "amendment_eval_complex_count": mvp.get("amendment_eval_complex_count"),
    }
    (OUTPUTS / "run_summary.json").write_text(json.dumps(summary_stats, indent=2), encoding="utf-8")
    print(json.dumps(summary_stats, indent=2))
    print("Wrote artifacts to", OUTPUTS)


if __name__ == "__main__":
    main()
