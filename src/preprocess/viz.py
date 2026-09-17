"""Preprocess QA figures — one claim per chart (story-first)."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from src.eda.config import FIGURES_DIR, PROJECT_ROOT
from src.preprocess.progress import stage_progress
from src.preprocess.store import DEFAULT_PREPROCESS_ROOT, ArtifactStore

# One accent + neutrals (qualitative: highlight the focal group)
_ACCENT = "#1f4e79"
_MUTED = "#b0b7c3"
_PASS = "#2ca25f"
_FAIL = "#c994c7"  # soft contrast for fail (not alarming red decoration)


def _figs_dir() -> Path:
    d = FIGURES_DIR / "preprocess"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _inspect_dir(event_id: str) -> Path:
    d = PROJECT_ROOT / "outputs" / "preprocess_inspect" / event_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _style_ax(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#888888")
    ax.spines["bottom"].set_color("#888888")
    ax.tick_params(colors="#333333", length=0)
    ax.grid(False)


def _label_bars_h(ax: plt.Axes, bars, values: list[int | float], *, fmt: str = "{:.0f}") -> None:
    for bar, val in zip(bars, values):
        w = bar.get_width()
        ax.text(
            w + max(values) * 0.02 if values and max(values) else 0.1,
            bar.get_y() + bar.get_height() / 2,
            fmt.format(val),
            va="center",
            ha="left",
            fontsize=10,
            color="#222222",
        )


def event_artifact_funnel(store: ArtifactStore) -> pd.DataFrame:
    """Event-level throughput from disk (same unit at every stage)."""
    events_root = store.path_root / "events"
    counts = {
        "Inventoried": 0,
        "Raw downloaded": 0,
        "Cleaned text": 0,
        "Segmented": 0,
        "GLiNER spans": 0,
        "Concise Rep": 0,
    }
    if not events_root.exists():
        return pd.DataFrame({"stage": list(counts), "n": list(counts.values())})

    for d in events_root.iterdir():
        if not d.is_dir():
            continue
        if (d / "inventory.json").exists():
            counts["Inventoried"] += 1
        else:
            continue
        if (d / "raw").exists() and any((d / "raw").iterdir()):
            counts["Raw downloaded"] += 1
        if (d / "clean").exists() and any((d / "clean").glob("*.txt")):
            counts["Cleaned text"] += 1
        if (d / "segments.json").exists():
            counts["Segmented"] += 1
        if (d / "spans.json").exists():
            counts["GLiNER spans"] += 1
        if (d / "concise" / "event_rep.json").exists():
            counts["Concise Rep"] += 1

    return pd.DataFrame({"stage": list(counts.keys()), "n": list(counts.values())})


def plot_cohort_mix(cohort_index: dict[str, Any], save: bool = True) -> plt.Figure:
    """Claim: almost all inventoried TO events are gold (cover + OTP + 14D-9)."""
    cohorts = cohort_index.get("cohorts") or {}
    label_map = {
        "gold": "Gold (cover + OTP + 14D-9)",
        "needs_otp_resolve": "Needs OTP resolve",
        "incomplete": "Incomplete",
    }
    rows = [{"cohort": label_map.get(k, k), "key": k, "n": int(v or 0)} for k, v in cohorts.items()]
    df = pd.DataFrame(rows)
    df = df[df["n"] > 0].sort_values("n", ascending=True)

    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    if df.empty:
        ax.set_title("No inventoried events yet")
        _style_ax(ax)
        return fig

    colors = [_ACCENT if k == "gold" else _MUTED for k in df["key"]]
    bars = ax.barh(df["cohort"], df["n"], color=colors, height=0.55)
    total = int(df["n"].sum())
    gold_n = int(df.loc[df["key"] == "gold", "n"].sum()) if (df["key"] == "gold").any() else 0
    pct = round(100 * gold_n / total) if total else 0

    ax.set_title(
        f"{pct}% of inventoried tender events are gold (cover + OTP + 14D-9)",
        loc="left",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )
    ax.set_xlabel("Events")
    ax.set_ylabel("")
    _label_bars_h(ax, bars, df["n"].tolist())
    ax.set_xlim(0, max(df["n"]) * 1.18)
    _style_ax(ax)
    fig.tight_layout()
    if save:
        fig.savefig(_figs_dir() / "preprocess_cohort_mix.png", dpi=160, bbox_inches="tight")
    return fig


def plot_pipeline_funnel(
    metrics_df: pd.DataFrame | None = None,
    save: bool = True,
    *,
    store: ArtifactStore | None = None,
    path_name: str = "tender",
    root: Path | None = None,
) -> plt.Figure:
    """Claim: nearly every inventoried event reaches Concise Rep (event-level units only)."""
    store = store or ArtifactStore(path_name, root or DEFAULT_PREPROCESS_ROOT)
    df = event_artifact_funnel(store)
    # Keep pipeline order (ordinal stages — do not sort by value)
    order = list(df["stage"])
    n0 = int(df["n"].iloc[0]) if not df.empty else 0
    n_end = int(df["n"].iloc[-1]) if not df.empty else 0
    drop = n0 - n_end

    fig, ax = plt.subplots(figsize=(8, 4.2))
    # Highlight final Concise Rep bar; mute earlier stages
    colors = [_MUTED] * (len(df) - 1) + [_ACCENT] if len(df) else []
    if len(df) == 1:
        colors = [_ACCENT]
    bars = ax.barh(df["stage"], df["n"], color=colors, height=0.6)
    ax.invert_yaxis()  # top = first stage

    if drop == 0 and n0 > 0:
        title = f"All {n0} inventoried events reach a Concise Rep"
    elif n0 > 0:
        title = f"{n_end} of {n0} inventoried events reach a Concise Rep ({drop} stopped early)"
    else:
        title = "No inventoried events on disk yet"
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", pad=12)
    ax.set_xlabel("Events (same unit at every stage)")
    ax.set_ylabel("")
    _label_bars_h(ax, bars, df["n"].tolist())
    ax.set_xlim(0, max(df["n"].max() * 1.15, 1))
    _style_ax(ax)
    fig.tight_layout()
    if save:
        fig.savefig(_figs_dir() / "preprocess_selection_funnel.png", dpi=160, bbox_inches="tight")
    return fig


def plot_quality_gates(
    gate_df: pd.DataFrame,
    save: bool = True,
) -> plt.Figure:
    """Claim: share of Concise Reps that pass upstream quality gates."""
    n = len(gate_df)
    n_ok = int(gate_df["ok"].sum()) if n and "ok" in gate_df.columns else 0
    n_fail = n - n_ok
    pct = round(100 * n_ok / n) if n else 0

    fig, ax = plt.subplots(figsize=(7, 2.8))
    labels = ["Pass gates", "Fail gates"]
    vals = [n_ok, n_fail]
    colors = [_PASS, _MUTED]
    bars = ax.barh(labels, vals, color=colors, height=0.5)
    ax.set_title(
        f"{pct}% of Concise Reps pass upstream quality gates (n={n} tender events)",
        loc="left",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )
    ax.set_xlabel("Events")
    ax.set_ylabel("")
    _label_bars_h(ax, bars, vals)
    ax.set_xlim(0, max(vals) * 1.2 if vals and max(vals) else 1)
    _style_ax(ax)
    fig.tight_layout()
    if save:
        fig.savefig(_figs_dir() / "preprocess_quality_gates.png", dpi=160, bbox_inches="tight")
    return fig


def plot_top1_field_readiness(
    cohort_df: pd.DataFrame,
    save: bool = True,
) -> plt.Figure:
    """Claim: top-1 offer price / expiration / offeror are usually present after ranking."""
    n = len(cohort_df)
    if n == 0:
        fig, ax = plt.subplots(figsize=(7, 3))
        ax.set_title("No Concise Reps to score", loc="left")
        return fig

    money = cohort_df["top_offer_price"].astype(str).str.contains(r"\$", na=False)
    has_date = cohort_df["top_expiration"].notna() & (cohort_df["top_expiration"].astype(str).str.len() > 0)
    has_off = cohort_df["top_offeror"].notna() & (cohort_df["top_offeror"].astype(str).str.len() > 0)

    rows = [
        {"field": "Offer price is $… shaped", "pct": 100 * money.mean(), "n": int(money.sum())},
        {"field": "Expiration date present", "pct": 100 * has_date.mean(), "n": int(has_date.sum())},
        {"field": "Offeror present", "pct": 100 * has_off.mean(), "n": int(has_off.sum())},
    ]
    df = pd.DataFrame(rows).sort_values("pct", ascending=True)

    fig, ax = plt.subplots(figsize=(7.5, 3.2))
    colors = [_ACCENT if p >= 90 else _MUTED for p in df["pct"]]
    bars = ax.barh(df["field"], df["pct"], color=colors, height=0.55)
    ax.set_title(
        f"Top-1 notification fields are usually ready after ranking (n={n})",
        loc="left",
        fontsize=12,
        fontweight="bold",
        pad=12,
    )
    ax.set_xlabel("Share of events (%)")
    ax.set_ylabel("")
    ax.set_xlim(0, 112)
    for bar, pct, count in zip(bars, df["pct"], df["n"]):
        ax.text(
            min(pct + 2, 108),
            bar.get_y() + bar.get_height() / 2,
            f"{pct:.0f}%  ({count}/{n})",
            va="center",
            ha="left",
            fontsize=10,
        )
    _style_ax(ax)
    fig.tight_layout()
    if save:
        fig.savefig(_figs_dir() / "preprocess_top1_field_readiness.png", dpi=160, bbox_inches="tight")
    return fig


def write_event_inspect_pages(
    path_name: str,
    event_ids: list[str],
    root: Path | None = None,
    show_progress: bool = True,
) -> list[Path]:
    store = ArtifactStore(path_name, root or DEFAULT_PREPROCESS_ROOT)
    written: list[Path] = []
    for eid in stage_progress(event_ids, desc="viz", total=len(event_ids), unit="event", show=show_progress):
        out_dir = _inspect_dir(eid)
        inv_path = store.inventory_path(eid)
        if inv_path.exists():
            inv = store.read_json(inv_path)
            body = ["<h1>Inventory</h1>", f"<p>cohort={html.escape(str(inv.get('cohort')))}</p>", "<table border=1 cellpadding=4>"]
            body.append("<tr><th>role</th><th>form</th><th>file_type</th><th>filename</th><th>otp_method</th></tr>")
            for d in inv.get("docs") or []:
                body.append(
                    "<tr>"
                    + "".join(
                        f"<td>{html.escape(str(d.get(k) or ''))}</td>"
                        for k in ("role", "form", "file_type", "filename", "otp_method")
                    )
                    + "</tr>"
                )
            body.append("</table>")
            p = out_dir / "01_inventory.html"
            p.write_text("\n".join(body), encoding="utf-8")
            written.append(p)

        seg_path = store.segments_path(eid)
        if seg_path.exists():
            seg = store.read_json(seg_path)
            parts = ["<h1>Segments</h1>"]
            for s in (seg.get("segments") or [])[:40]:
                parts.append(
                    f"<h3>{html.escape(str(s.get('kind')))} — {html.escape(str(s.get('heading') or s.get('question') or ''))}</h3>"
                )
                preview = (s.get("text") or "")[:1200]
                parts.append(f"<pre>{html.escape(preview)}</pre>")
            p = out_dir / "04_segments.html"
            p.write_text("\n".join(parts), encoding="utf-8")
            written.append(p)

        spans_path = store.spans_path(eid)
        if spans_path.exists():
            spans = store.read_json(spans_path)
            parts = ["<h1>GLiNER spans</h1>", "<table border=1 cellpadding=4>"]
            parts.append("<tr><th>label</th><th>text</th><th>score</th><th>segment</th></tr>")
            for sp in spans.get("spans") or []:
                parts.append(
                    "<tr>"
                    f"<td>{html.escape(str(sp.get('label')))}</td>"
                    f"<td>{html.escape(str(sp.get('text')))}</td>"
                    f"<td>{html.escape(str(sp.get('score')))}</td>"
                    f"<td>{html.escape(str(sp.get('segment_id')))}</td>"
                    "</tr>"
                )
            parts.append("</table>")
            p = out_dir / "05_gliner_spans.html"
            p.write_text("\n".join(parts), encoding="utf-8")
            written.append(p)

        rep_path = store.event_rep_path(eid)
        if rep_path.exists():
            rep = store.read_json(rep_path)
            parts = [
                "<h1>Concise Rep</h1>",
                f"<p>status={html.escape(str(rep.get('preprocess_status')))} facts={len(rep.get('candidate_facts') or [])}</p>",
                "<table border=1 cellpadding=4>",
                "<tr><th>field_hint</th><th>raw</th><th>confidence</th><th>method</th></tr>",
            ]
            for f in rep.get("candidate_facts") or []:
                parts.append(
                    "<tr>"
                    f"<td>{html.escape(str(f.get('field_hint')))}</td>"
                    f"<td>{html.escape(str(f.get('raw')))}</td>"
                    f"<td>{html.escape(str(f.get('confidence')))}</td>"
                    f"<td>{html.escape(str(f.get('method')))}</td>"
                    "</tr>"
                )
            parts.append("</table>")
            p = out_dir / "06_concise_rep.html"
            p.write_text("\n".join(parts), encoding="utf-8")
            written.append(p)
    return written


def run_viz(
    path_name: str = "tender",
    event_ids: list[str] | None = None,
    inspect_limit: int = 5,
    root: Path | None = None,
    show_progress: bool = True,
) -> dict[str, Any]:
    from src.preprocess.metrics import collect_stage_metrics
    from src.preprocess.quality_gates import check_event_rep

    store = ArtifactStore(path_name, root or DEFAULT_PREPROCESS_ROOT)
    out: dict[str, Any] = {"figures": [], "inspect": []}
    idx_path = store.cohort_index_path()
    if idx_path.exists():
        idx = store.read_json(idx_path)
        plot_cohort_mix(idx)
        out["figures"].append("preprocess_cohort_mix.png")
        if not event_ids:
            event_ids = (idx.get("cohort_event_ids") or {}).get("gold") or []
            event_ids = event_ids[:inspect_limit]

    metrics_df = collect_stage_metrics(path_name, root)
    plot_pipeline_funnel(metrics_df, store=store)
    out["figures"].append("preprocess_selection_funnel.png")

    # Gate + field readiness from Concise Reps on disk
    rows = []
    events_root = store.path_root / "events"
    if events_root.exists():
        for d in sorted(events_root.iterdir()):
            rep_p = d / "concise" / "event_rep.json"
            if not rep_p.exists():
                continue
            rep = store.read_json(rep_p)
            g = check_event_rep(rep)
            rows.append(
                {
                    "event_id": d.name,
                    "ok": g["ok"],
                    "top_offer_price": g["checks"].get("top1_offer_price"),
                    "top_expiration": g["checks"].get("top1_expiration_date"),
                    "top_offeror": g["checks"].get("top1_offeror"),
                }
            )
    if rows:
        gate_df = pd.DataFrame(rows)
        plot_quality_gates(gate_df)
        plot_top1_field_readiness(gate_df)
        out["figures"].extend(["preprocess_quality_gates.png", "preprocess_top1_field_readiness.png"])

    if event_ids:
        out["inspect"] = [str(p) for p in write_event_inspect_pages(path_name, event_ids, root, show_progress)]
    return out
