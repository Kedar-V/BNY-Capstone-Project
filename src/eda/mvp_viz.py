"""MVP-focused plots for datastore → extraction → notification design."""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

from .config import FIGURES_DIR

# Consistent palette for source ownership
SOURCE_COLORS = {
    "public_document_extractable": "#1f4e79",
    "derived_from_public": "#2e7d4f",
    "bny_internal_only": "#8b1e1e",
    "unclear_requires_investigation": "#b07d1a",
}

FAMILY_COLORS = {
    "issuer_tender": "#7a8a99",
    "mixed": "#1f4e79",
    "third_party_tender": "#2e7d4f",
}


def _ensure_figs() -> Path:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    return FIGURES_DIR


def _save(fig: plt.Figure, name: str, save: bool) -> None:
    if save:
        _ensure_figs()
        fig.savefig(FIGURES_DIR / name, dpi=150, bbox_inches="tight")


def plot_event_family_mix(events: pd.DataFrame, save: bool = True) -> plt.Figure:
    """Event-level form-family mix — preferred over raw EFTS hit counts for MVP selection."""
    counts = (
        events["primary_form_family"]
        .fillna("unknown")
        .value_counts()
        .rename_axis("primary_form_family")
        .reset_index(name="n_events")
    )
    fig, ax = plt.subplots(figsize=(8, 4.2))
    colors = [FAMILY_COLORS.get(f, "#555555") for f in counts["primary_form_family"]]
    sns.barplot(data=counts, y="primary_form_family", x="n_events", ax=ax, palette=colors)
    ax.set_title("Events by form family (event-centric — use this for MVP selection)")
    ax.set_xlabel("Events")
    ax.set_ylabel("primary_form_family")
    for i, row in counts.iterrows():
        ax.text(row["n_events"] + max(counts["n_events"]) * 0.01, i, f"{int(row['n_events'])}", va="center")
    fig.tight_layout()
    _save(fig, "mvp_event_family_mix.png", save)
    return fig


def plot_mvp_selection_funnel(funnel: pd.DataFrame, save: bool = True) -> plt.Figure:
    """Funnel from full corpus → MVP notification datastore pool."""
    fig, ax = plt.subplots(figsize=(9, 4.5))
    order = funnel["stage"].tolist()
    sns.barplot(data=funnel, y="stage", x="n_events", order=order, ax=ax, color="#1f4e79")
    ax.set_title("MVP datastore selection funnel (events)")
    ax.set_xlabel("Events remaining")
    ax.set_ylabel("")
    xmax = max(funnel["n_events"].max(), 1)
    for i, row in funnel.iterrows():
        ax.text(row["n_events"] + xmax * 0.01, i, f"{int(row['n_events'])}", va="center")
    fig.tight_layout()
    _save(fig, "mvp_selection_funnel.png", save)
    return fig


def plot_schema_coverage_by_ownership(
    schema_coverage: pd.DataFrame,
    save: bool = True,
) -> plt.Figure:
    """BNY field coverage, colored by public vs internal ownership."""
    cov = schema_coverage.dropna(subset=["public_coverage_pct"]).copy()
    cov = cov.sort_values("public_coverage_pct", ascending=True)
    fig, ax = plt.subplots(figsize=(10, 11))
    palette = {k: SOURCE_COLORS.get(k, "#555555") for k in cov["source_class"].unique()}
    sns.barplot(
        data=cov,
        y="field",
        x="public_coverage_pct",
        hue="source_class",
        dodge=False,
        ax=ax,
        palette=palette,
    )
    ax.set_xlim(0, 100)
    ax.set_xlabel("Public coverage % (metadata or sample mention)")
    ax.set_title("BNY schema coverage by field ownership\n(red = internal-only → placeholder in datastore)")
    ax.legend(title="source_class", loc="lower right", fontsize=8)
    fig.tight_layout()
    _save(fig, "mvp_schema_coverage_by_ownership.png", save)
    return fig


def plot_field_ownership_counts(schema_coverage: pd.DataFrame, save: bool = True) -> plt.Figure:
    """How many BNY fields fall into each datastore ownership class."""
    cls = (
        schema_coverage.groupby("source_class", dropna=False)
        .size()
        .rename("n_fields")
        .reset_index()
        .sort_values("n_fields", ascending=True)
    )
    fig, ax = plt.subplots(figsize=(8, 3.8))
    colors = [SOURCE_COLORS.get(c, "#555555") for c in cls["source_class"]]
    sns.barplot(data=cls, y="source_class", x="n_fields", ax=ax, palette=colors)
    ax.set_title("Datastore field ownership (count of BNY schema fields)")
    ax.set_xlabel("Fields")
    ax.set_ylabel("")
    fig.tight_layout()
    _save(fig, "mvp_field_ownership.png", save)
    return fig


def plot_benchmark_field_coverage(
    schema_coverage: pd.DataFrame,
    benchmark_fields: list[str],
    save: bool = True,
) -> plt.Figure:
    """Coverage for the v1 extraction benchmark only."""
    cov = schema_coverage[schema_coverage["field"].isin(benchmark_fields)].copy()
    if cov.empty:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "No benchmark fields in coverage table", ha="center")
        ax.axis("off")
        return fig
    order = [f for f in benchmark_fields if f in set(cov["field"])]
    cov["field"] = pd.Categorical(cov["field"], categories=order, ordered=True)
    cov = cov.sort_values("field")
    fig, ax = plt.subplots(figsize=(9, 4.5))
    colors = [SOURCE_COLORS.get(c, "#555555") for c in cov["source_class"]]
    sns.barplot(data=cov, y="field", x="public_coverage_pct", ax=ax, palette=colors)
    ax.set_xlim(0, 100)
    ax.set_xlabel("Public coverage %")
    ax.set_title("v1 extraction benchmark fields (datastore → notification core)")
    fig.tight_layout()
    _save(fig, "mvp_benchmark_field_coverage.png", save)
    return fig


def plot_mvp_amendment_readiness(mvp_events: pd.DataFrame, save: bool = True) -> plt.Figure:
    """Amendment / multi-doc distributions for the MVP event pool."""
    if mvp_events.empty:
        fig, ax = plt.subplots(figsize=(8, 3))
        ax.text(0.5, 0.5, "Empty MVP event table", ha="center")
        ax.axis("off")
        return fig

    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    sns.histplot(mvp_events["n_filings"], bins=20, ax=axes[0], color="#1f4e79")
    axes[0].set_title("Filings / MVP event")
    axes[0].set_xlabel("n_filings")

    sns.histplot(mvp_events["n_amendment_filings"], bins=20, ax=axes[1], color="#2e7d4f")
    axes[1].set_title("Amendments / MVP event")
    axes[1].set_xlabel("n_amendment_filings")

    span = mvp_events["event_span_days"].dropna().astype(float)
    sns.histplot(span[span >= 0], bins=25, ax=axes[2], color="#8b4513")
    axes[2].set_title("MVP event span (days)")
    axes[2].set_xlabel("days")

    fig.suptitle("Temporal datastore readiness (MVP pool)", y=1.02)
    fig.tight_layout()
    _save(fig, "mvp_amendment_readiness.png", save)
    return fig


def plot_notification_completeness(
    catalog: pd.DataFrame,
    save: bool = True,
) -> plt.Figure:
    """Share of notification fields by datastore role."""
    role_order = [
        "extract_from_public",
        "derive_from_public",
        "annotate_then_store",
        "bny_placeholder",
        "exclude_or_investigate",
    ]
    role_colors = {
        "extract_from_public": "#1f4e79",
        "derive_from_public": "#2e7d4f",
        "annotate_then_store": "#b07d1a",
        "bny_placeholder": "#8b1e1e",
        "exclude_or_investigate": "#7a8a99",
    }
    counts = (
        catalog["datastore_role"]
        .value_counts()
        .reindex([r for r in role_order if r in set(catalog["datastore_role"])])
        .rename_axis("datastore_role")
        .reset_index(name="n_fields")
    )
    fig, ax = plt.subplots(figsize=(9, 4))
    colors = [role_colors.get(r, "#555555") for r in counts["datastore_role"]]
    sns.barplot(data=counts, y="datastore_role", x="n_fields", ax=ax, palette=colors)
    ax.set_title("Notification field roles in the MVP datastore")
    ax.set_xlabel("Fields")
    ax.set_ylabel("")
    fig.tight_layout()
    _save(fig, "mvp_notification_field_roles.png", save)
    return fig


def plot_mvp_event_type_readiness(
    corpus_gaps: pd.DataFrame,
    save: bool = True,
) -> plt.Figure:
    """Primary-form coverage for each target MVP event type (honest corpus gaps)."""
    fig, ax = plt.subplots(figsize=(9, 4.5))
    order = corpus_gaps["mvp_event_type"].tolist()
    status_colors = {
        "collected": "#2e7d4f",
        "partial_in_tender_corpus": "#b07d1a",
        "not_collected": "#8b1e1e",
    }
    colors = [status_colors.get(s, "#555555") for s in corpus_gaps["corpus_status"]]
    sns.barplot(
        data=corpus_gaps,
        y="mvp_event_type",
        x="primary_form_coverage_pct",
        order=order,
        ax=ax,
        palette=colors,
    )
    ax.set_xlim(0, 100)
    ax.set_xlabel("% of target primary SEC forms present in current corpus")
    ax.set_title(
        "MVP event-type readiness (tender / exchange / rights / merger / conversion)\n"
        "Green=collected · Amber=partial · Red=not collected"
    )
    ax.set_ylabel("")
    fig.tight_layout()
    _save(fig, "mvp_event_type_readiness.png", save)
    return fig


def plot_event_type_field_relevance_matrix(save: bool = True) -> plt.Figure:
    """Which BNY fields matter for which MVP event type (relevance prior, not coverage %)."""
    from .bny_schema import BNY_SCHEMA
    from .event_taxonomy import MVP_EVENT_TYPE_KEYS, RELEVANCE_BY_MVP_TYPE

    # Short labels keep x-axis text horizontal (viz principles: prefer horizontal text)
    type_labels = {
        "tender_offer": "Tender",
        "exchange_offer": "Exchange",
        "rights_issue": "Rights",
        "merger": "Merger",
        "conversion": "Conversion",
    }
    score = {"relevant": 2, "optional": 1, "not_relevant": 0}
    rows = []
    for f in BNY_SCHEMA:
        row = {"field": f.name.replace("_", " ")}
        for tkey in MVP_EVENT_TYPE_KEYS:
            row[type_labels.get(tkey, tkey)] = score[
                RELEVANCE_BY_MVP_TYPE.get(tkey, {}).get(f.name, "relevant")
            ]
        rows.append(row)
    mat = pd.DataFrame(rows).set_index("field")
    # Column order matches MVP type order
    cols = [type_labels[k] for k in MVP_EVENT_TYPE_KEYS if type_labels[k] in mat.columns]
    mat = mat[cols]

    fig, ax = plt.subplots(figsize=(7.5, 11))
    sns.heatmap(
        mat,
        cmap="Blues",
        ax=ax,
        cbar_kws={"label": "N/A · optional · relevant"},
        linewidths=0.2,
        linecolor="#f5f5f5",
    )
    ax.set_title(
        "Most BNY notification fields are relevant across all five MVP event types\n"
        "(design prior — not observed coverage)",
        fontsize=12,
        fontweight="bold",
        pad=14,
    )
    ax.set_xlabel("Event type")
    ax.set_ylabel("")
    plt.setp(ax.get_xticklabels(), rotation=0, ha="center")
    plt.setp(ax.get_yticklabels(), rotation=0)
    fig.tight_layout()
    _save(fig, "mvp_field_relevance_by_event_type.png", save)
    return fig


def plot_event_type_coverage_heatmap(
    event_type_coverage: pd.DataFrame,
    save: bool = True,
) -> plt.Figure | None:
    """Observed sample coverage for form families currently in the corpus."""
    if event_type_coverage is None or event_type_coverage.empty:
        return None
    pivot = event_type_coverage.pivot_table(
        index="field", columns="corporate_action_type", values="coverage_pct"
    )
    # Human-readable index/columns; keep tick text horizontal
    pivot = pivot.copy()
    pivot.index = [str(i).replace("_", " ") for i in pivot.index]
    pivot.columns = [str(c).replace("_", " ").title() for c in pivot.columns]

    fig, ax = plt.subplots(figsize=(8, 11))
    sns.heatmap(pivot, annot=False, cmap="Blues", ax=ax, vmin=0, vmax=100)
    ax.set_title(
        "Sample mention coverage is tender-heavy until other form families are collected",
        loc="left",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )
    ax.set_xlabel("Form family / event type in sample")
    ax.set_ylabel("")
    ax.set_xticklabels(ax.get_xticklabels(), rotation=0, ha="center")
    ax.set_yticklabels(ax.get_yticklabels(), rotation=0)
    fig.tight_layout()
    _save(fig, "mvp_event_type_coverage_heatmap.png", save)
    return fig
