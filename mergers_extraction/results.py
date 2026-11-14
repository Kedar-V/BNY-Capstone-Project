"""Load every scored merger-extraction run under outputs/ and chart it.

A run is any folder under outputs/ holding `per_field.csv` and `summary.json`, as written by common.write_results
(gliner_zero_shot_eval.py and gliner_finetuned_eval.py both use it). A new method shows up in
visualize_mergers_results.ipynb as soon as it writes its scores the same way.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

import common

FIGURES = common.HERE / "figures"

# Colours: checked with the dataviz palette validator (lightness, chroma, colour-blind separation, contrast).
CURRENT = "#009AAE"    # the run in focus (BNY teal, chroma raised to pass the checks)
SECOND = "#00539B"     # Duke Royal Blue: ground-truth passages / a second series
CONTEXT = "#A3AEBB"    # muted context: other runs and baselines
INK, INK_2 = "#04243C", "#475569"  # text: BNY navy, slate
GRID = "#E5E7EB"

# How window choices are named in charts and tables. Result folders and --windows keep the short names.
WINDOW_NAMES = {"pipeline": "original keyword windows", "learned": "learned windows",
                "fulltext": "full filing text", "combined": "best method per field"}


def windows_label(name: str) -> str:
    return WINDOW_NAMES.get(name, f"{name} windows")


def _is_original(strategy: pd.Series) -> pd.Series:
    """The original keyword windows in answer_recall.csv (older files call them 'pipeline keyword windows')."""
    return strategy.str.startswith(("original", "pipeline"))


FIELD_NAMES = {
    "acquirer": "Acquirer", "target": "Target", "merger_subsidiary": "Merger subsidiary",
    "security_description": "Security description", "cash_consideration": "Cash consideration",
    "stock_exchange_ratio": "Exchange ratio", "shareholder_vote_date": "Shareholder vote date",
    "effective_date": "Effective date", "election_deadline": "Election deadline",
    "expected_closing": "Expected closing",
}

plt.rcParams.update({
    "font.family": "Helvetica Neue", "font.size": 11, "text.color": INK, "axes.labelcolor": INK_2,
    "xtick.color": INK_2, "ytick.color": INK_2, "axes.edgecolor": GRID, "axes.linewidth": 1,
    "axes.spines.top": False, "axes.spines.right": False, "axes.spines.left": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 1, "axes.axisbelow": True,
    "figure.dpi": 100, "savefig.dpi": 200, "savefig.bbox": "tight", "savefig.facecolor": "white",
})


# ---------------------------------------------------------------- loading
def window_mode(per_field: pd.DataFrame) -> str:
    """The window choice a run was scored with: the *_f1 column that is not the ground-truth passages."""
    return next(c[:-3] for c in per_field.columns if c.endswith("_f1") and c != "oracle_f1")


def discover_runs(root: Path = common.OUTPUTS) -> pd.DataFrame:
    """One row per scored run, newest first."""
    rows = []
    for summary_path in root.rglob("summary.json"):
        folder = summary_path.parent
        if not (folder / "per_field.csv").exists():
            continue  # e.g. training_data/summary.json
        summary = json.loads(summary_path.read_text())
        per_field = pd.read_csv(folder / "per_field.csv")
        mode = window_mode(per_field)
        model = str(summary.get("model", ""))
        finetuned = "merger_gliner" in model  # fine-tuned weights live in models/merger_gliner/<name>/final
        # a new method can name itself with "method" (and "model") in its summary.json
        method = summary.get("method") or ("fine-tuned GLiNER" if finetuned else "zero-shot GLiNER")
        model_name = Path(model).parent.name if finetuned else model.split("/")[-1]
        micro = summary.get("micro", {})
        rows.append({
            "run": str(folder.relative_to(root)),
            "method": method,
            "model": model_name,
            "windows": mode,
            "split": summary.get("split", "all"),
            "filings": summary.get("filings"),
            "records": summary.get("records"),
            "micro_f1": micro.get(mode, {}).get("f1"),
            "micro_precision": micro.get(mode, {}).get("precision"),
            "micro_recall": micro.get(mode, {}).get("recall"),
            "micro_f1_gt_passages": micro.get("oracle", {}).get("f1"),
            "fields_scored": len(per_field),
            "modified": pd.Timestamp.fromtimestamp(os.path.getmtime(summary_path)).floor("min"),
            "path": folder,
        })
    runs = pd.DataFrame(rows)
    if runs.empty:
        return runs
    return runs.sort_values("modified", ascending=False).reset_index(drop=True)


def comparable(runs: pd.DataFrame, focus: pd.Series) -> pd.DataFrame:
    """Runs scored on the same held-out set as the focus run (same split, filings and records)."""
    same = (runs["split"] == focus["split"]) & (runs["filings"] == focus["filings"]) & (runs["records"] == focus["records"])
    return runs[same]


def default_focus(runs: pd.DataFrame) -> pd.Series:
    """Newest fine-tuned run, preferring learned windows."""
    tuned = runs[runs["method"] == "fine-tuned GLiNER"]
    tuned = tuned.sort_values(["windows", "modified"], key=lambda c: c.eq("learned") if c.name == "windows" else c,
                              ascending=False)
    return tuned.iloc[0] if len(tuned) else runs.iloc[0]


def baseline_for(runs: pd.DataFrame, focus: pd.Series) -> pd.Series | None:
    """Zero-shot GLiNER on the same held-out set and window choice, if it was scored."""
    same = comparable(runs, focus)
    same = same[(same["method"] == "zero-shot GLiNER") & (same["windows"] == focus["windows"])]
    return same.iloc[0] if len(same) else None


def _cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def label(run: pd.Series) -> str:
    return f"{run['method']}, {windows_label(run['windows'])} ({run['model']}, {run['filings']} {run['split']} filings)"


def per_field(run: pd.Series) -> pd.DataFrame:
    """Per-field scores of one run with generic column names: f1 / precision / recall and gt_passages_f1."""
    df = pd.read_csv(Path(run["path"]) / "per_field.csv").set_index("field")
    mode = window_mode(df.reset_index())
    out = df[["tp", "fp", "fn", "gt_absence_values"]].copy()
    for metric in ("precision", "recall", "f1"):
        out[metric] = df[f"{mode}_{metric}"]
    out["gt_passages_f1"] = df["oracle_f1"] if "oracle_f1" in df else float("nan")
    coverage = [c for c in df.columns if c.startswith("quotes_in_")]
    if coverage:
        out["quotes_in_windows"] = df[coverage[0]]
    return out


def field_table(runs: pd.DataFrame, fields=None, metric: str = "f1") -> pd.DataFrame:
    """Field x run table of a per-field metric: "f1", "precision", "recall", or "fp" (wrong answers)."""
    cols = {}
    for _, run in runs.iterrows():
        f1 = per_field(run)[metric].astype(float)
        f1.loc["MICRO"] = run[f"micro_{metric}"] if f"micro_{metric}" in run else f1.sum()
        cols[f"{run['method']} | {windows_label(run['windows'])} | {run['model']} | {run['filings']} filings"] = f1
    table = pd.DataFrame(cols)
    if fields is not None:
        table = table.loc[[f for f in list(fields) + ["MICRO"] if f in table.index]]
    return table


# ---------------------------------------------------------------- chart helpers
def _title(ax, text, sub, legend_above=False):
    lift = 0.075 if legend_above else 0.0
    ax.set_title(text, loc="left", fontsize=14, fontweight="bold", color=INK, pad=28 + (26 if lift else 0))
    ax.text(0, 1.035 + lift, sub, transform=ax.transAxes, fontsize=10.5, color=INK_2, va="bottom")


def _legend_above(ax, ncol):
    ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), ncol=ncol, frameon=False, fontsize=9.5,
              handletextpad=0.3, columnspacing=1.5, borderaxespad=0.2)


def _clean_y(ax):
    ax.tick_params(axis="y", length=0, labelcolor=INK)
    ax.grid(axis="y", visible=False)


def save(fig, name: str, folder: Path = FIGURES) -> Path:
    folder.mkdir(exist_ok=True)
    fig.savefig(folder / name)
    return folder / name


# ---------------------------------------------------------------- charts
def overall_chart(runs: pd.DataFrame, focus: pd.Series):
    """Micro-F1 of several runs on the same held-out set; the focus run is highlighted and its ground-truth-passage
    score shown as an outlined bar. Only runs scored on the same fields are compared: micro-F1 over 3 date fields
    and over 10 span fields are not comparable."""
    runs = runs[runs["fields_scored"] == focus["fields_scored"]].sort_values("micro_f1")
    rows = [(_cap(f"{r['method']}, {windows_label(r['windows'])}"), r["micro_f1"], CURRENT if r["run"] == focus["run"] else CONTEXT)
            for _, r in runs.iterrows()]
    if pd.notna(focus["micro_f1_gt_passages"]):
        rows.append((_cap(f"{focus['method']}, given the ground-truth passages") +
                     "\n(reads only the passages the ground truth quotes)", focus["micro_f1_gt_passages"], None))
    fig, ax = plt.subplots(figsize=(9, 1.2 + 0.6 * len(rows)))
    for i, (name, value, colour) in enumerate(rows):
        if colour is None:
            ax.barh(i, value, height=0.5, facecolor="white", edgecolor=SECOND, linewidth=1.5)
        else:
            ax.barh(i, value, height=0.5, color=colour)
        ax.text(value + 0.01, i, f"{value:.2f}", va="center", fontsize=11,
                fontweight="bold" if colour == CURRENT else "normal", color=INK)
    ax.set_yticks(range(len(rows)), [r[0] for r in rows])
    ax.invert_yaxis()
    ax.set_xlim(0, max(r[1] for r in rows) * 1.2)
    _clean_y(ax)
    ax.set_xlabel(f"Micro-F1, {focus['filings']} {focus['split']} filings")
    low = runs["micro_f1"].min()
    _title(ax, f"Micro-F1 from {low:.2f} to {focus['micro_f1']:.2f} ({focus['model']})",
           "Agreement with the unverified LLM ground truth")
    return fig


def per_field_chart(focus: pd.Series, baseline: pd.Series | None = None):
    """Dumbbell per field: baseline -> focus run, with the focus run's ground-truth-passage score."""
    f = per_field(focus).dropna(subset=["f1"])
    f = f[f.index.isin(FIELD_NAMES)].sort_values("f1")
    fig, ax = plt.subplots(figsize=(9, 1.5 + 0.42 * len(f)))
    y = list(range(len(f)))
    if baseline is not None:
        b = per_field(baseline)["f1"].reindex(f.index).fillna(0)
        for i, field in enumerate(f.index):
            ax.plot([b[field], f.loc[field, "f1"]], [i, i], color=GRID, linewidth=3, solid_capstyle="round", zorder=1)
        ax.scatter(b, y, s=70, color=CONTEXT, edgecolor="white", linewidth=2, zorder=3,
                   label=_cap(f"{baseline['method']}, {windows_label(baseline['windows'])}"))
    if f["gt_passages_f1"].notna().any():
        ax.scatter(f["gt_passages_f1"], y, s=70, facecolor="white", edgecolor=SECOND, linewidth=2, zorder=2,
                   label="Given the ground-truth passages")
    ax.scatter(f["f1"], y, s=80, color=CURRENT, edgecolor="white", linewidth=2, zorder=4,
               label=_cap(f"{focus['method']}, {windows_label(focus['windows'])}"))
    ax.set_yticks(y, [FIELD_NAMES.get(i, i) for i in f.index])
    _clean_y(ax)
    ax.set_xlim(0, 1)
    ax.set_xlabel(f"F1 per field, {focus['filings']} {focus['split']} filings")
    _legend_above(ax, 3)
    _title(ax, f"F1 per field: {focus['model']}", "Values in the table below the chart", legend_above=True)
    return fig


def window_budget_chart(path: Path = common.OUTPUTS / "window_selector" / "answer_recall.csv"):
    rec = pd.read_csv(path)
    first = rec[rec["strategy"].str.startswith("first")]
    learned = rec[rec["strategy"].str.startswith("learned")]
    pipe = rec[_is_original(rec["strategy"])].iloc[0]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    ax.plot(first["avg_windows"], first["overall"] * 100, color=CONTEXT, linewidth=2, marker="o", markersize=7,
            markeredgecolor="white", markeredgewidth=2, label="First N windows of the filing")
    ax.plot(learned["avg_windows"], learned["overall"] * 100, color=CURRENT, linewidth=2, marker="o", markersize=8,
            markeredgecolor="white", markeredgewidth=2, label="Learned selector (1, 2, 3, 5 per field)")
    ax.scatter([pipe["avg_windows"]], [pipe["overall"] * 100], s=80, color=SECOND, edgecolor="white", linewidth=2,
               zorder=5, label="Original keyword windows")
    ax.annotate(f"Original keyword windows: {pipe['overall']:.0%}", (pipe["avg_windows"], pipe["overall"] * 100), xytext=(8, -16),
                textcoords="offset points", fontsize=10, color=INK)
    last = learned.iloc[-1]
    ax.annotate(f"Learned, 5 per field: {last['overall']:.0%}\nwith {last['avg_windows']:.0f} windows",
                (last["avg_windows"], last["overall"] * 100), xytext=(10, -8), textcoords="offset points",
                fontsize=10, color=INK)
    end = first.iloc[-1]
    ax.annotate(f"First {end['avg_windows']:.0f}: {end['overall']:.0%}", (end["avg_windows"], end["overall"] * 100),
                xytext=(-10, 10), textcoords="offset points", ha="right", fontsize=10, color=INK)
    ax.set_xlim(0, max(100, first["avg_windows"].max() + 5))
    ax.set_ylim(0, 100)
    ax.set_xlabel("Windows read per filing (900 characters each)")
    ax.set_ylabel("Held-out answers inside the windows (%)")
    ax.legend(loc="upper left", frameon=False, fontsize=9.5)
    _title(ax, f"Learned windows: {last['overall']:.0%} of answers from {last['avg_windows']:.0f} windows",
           "Share of ground-truth values that fall inside the windows GLiNER reads, held-out filings")
    return fig


def window_fields_chart(path: Path = common.OUTPUTS / "window_selector" / "answer_recall.csv"):
    rec = pd.read_csv(path).set_index("strategy")
    pipe = rec.loc[_is_original(rec.index.to_series())].iloc[0]
    learned = rec.loc[rec.index.str.startswith("learned")].iloc[-1]
    fields = [f for f in FIELD_NAMES if f in rec.columns and f != "effective_date"]
    fields = sorted(fields, key=lambda f: learned[f])
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for i, f in enumerate(fields):
        ax.plot([pipe[f] * 100, learned[f] * 100], [i, i], color=GRID, linewidth=3, solid_capstyle="round", zorder=1)
        ax.text(max(pipe[f], learned[f]) * 100 + 2.5, i, f"{learned[f]:.0%}", va="center", fontsize=10, color=INK)
    ax.scatter(pipe[fields] * 100, range(len(fields)), s=70, color=SECOND, edgecolor="white", linewidth=2, zorder=3,
               label=f"Original keyword windows ({pipe['avg_windows']:.0f} per filing)")
    ax.scatter(learned[fields] * 100, range(len(fields)), s=80, color=CURRENT, edgecolor="white", linewidth=2,
               zorder=4, label=f"Learned windows ({learned['avg_windows']:.0f} per filing)")
    ax.set_yticks(range(len(fields)), [FIELD_NAMES[f] for f in fields])
    _clean_y(ax)
    ax.set_xlim(0, 105)
    ax.set_xlabel("Held-out answers inside the windows (%)")
    _legend_above(ax, 2)
    _title(ax, "Answers inside the windows, by field", "Label = learned windows. Effective date omitted: too few values",
           legend_above=True)
    return fig


def training_data_chart(path: Path = common.TRAINING_DATA / "coverage.csv"):
    cov = pd.read_csv(path)
    cov["usable"] = cov["records_with_value"] - cov["stated_absences"]
    cov = cov[cov["usable"] > 0].sort_values("located_share")
    summary = json.loads((path.parent / "summary.json").read_text())
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for i, (_, r) in enumerate(cov.iterrows()):
        ax.barh(i, r["located_share"] * 100, height=0.5, color=CURRENT)
        ax.text(r["located_share"] * 100 + 1.5, i, f"{r['records_located']:,} of {r['usable']:,}", va="center",
                fontsize=10, color=INK)
    ax.set_yticks(range(len(cov)), [FIELD_NAMES[f] for f in cov["field"]])
    _clean_y(ax)
    ax.set_xlim(0, 115)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel(f"Ground-truth values found in the filing text (%), {summary['filings']} filings")
    _title(ax, "Ground-truth values that become training examples",
           "Only values found in the filing text can be trained on")
    return fig


def training_loss_chart(model: str):
    meta_path = common.MODELS / model / "train_meta.json"
    copy = common.OUTPUTS / f"gliner_finetuned_{model}_holdout" / "train_meta.json"
    if meta_path.exists() and copy.parent.exists():  # models/ is gitignored, so keep a copy next to the results
        copy.write_text(meta_path.read_text())
    path = meta_path if meta_path.exists() else copy
    if not path.exists():
        raise FileNotFoundError(f"no train_meta.json for {model}")
    meta = json.loads(path.read_text())
    hist = pd.DataFrame([h for h in meta["loss_history"] if "loss" in h])
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.plot(hist["step"], hist["loss"], color=CURRENT, linewidth=2, solid_capstyle="round")
    ax.scatter(hist["step"].iloc[[-1]], hist["loss"].iloc[[-1]], s=60, color=CURRENT, edgecolor="white", linewidth=2,
               zorder=3)
    ax.annotate(f"{hist['loss'].iloc[-1]:.2f}", (hist["step"].iloc[-1], hist["loss"].iloc[-1]), xytext=(8, 0),
                textcoords="offset points", va="center", fontsize=10, color=INK)
    ax.set_ylim(0, None)
    ax.set_xlabel("Training step (batch of 2 passages)")
    ax.set_ylabel("Training loss")
    _title(ax, f"Training loss: {model}",
           f"{meta['train_examples']:,} training passages, {meta['max_steps']} steps, learning rate {meta['lr']}, "
           f"{meta['train_seconds'] / 60:.0f} minutes")
    return fig


def methods_chart(runs: pd.DataFrame, focus: pd.Series):
    """Per field: the focus GLiNER run's F1 against the best other method scored on the same held-out filings,
    labelled with that method's name. Fields GLiNER does not answer are shown with the other method alone."""
    others = runs[runs["method"].str.contains("GLiNER") == False]  # noqa: E712
    base = per_field(focus)["f1"]
    rows = []
    fields = list(dict.fromkeys(list(FIELD_NAMES) + [f for _, r in others.iterrows() for f in per_field(r).index]))
    for field in fields:
        best = None
        for _, r in others.iterrows():
            f = per_field(r)
            if field in f.index and pd.notna(f.loc[field, "f1"]) and (best is None or f.loc[field, "f1"] > best[1]):
                best = (r["method"], f.loc[field, "f1"])
        g = base.get(field)
        if best is None and (g is None or pd.isna(g)):
            continue
        rows.append((field, g if g is not None and pd.notna(g) else None, best))
    rows.sort(key=lambda r: max(r[1] or 0, r[2][1] if r[2] else 0))
    fig, ax = plt.subplots(figsize=(9, 1.6 + 0.42 * len(rows)))
    for i, (field, g, best) in enumerate(rows):
        values = [v for v in (g, best[1] if best else None) if v is not None]
        if len(values) == 2:
            ax.plot(values, [i, i], color=GRID, linewidth=3, solid_capstyle="round", zorder=1)
        if best:
            ax.text(max(values) + 0.025, i, best[0], va="center", fontsize=9, color=INK_2)
    ax.scatter([r[1] for r in rows if r[1] is not None], [i for i, r in enumerate(rows) if r[1] is not None], s=80,
               color=CURRENT, edgecolor="white", linewidth=2, zorder=3, label=_cap(f"{focus['method']}, {windows_label(focus['windows'])}"))
    ax.scatter([r[2][1] for r in rows if r[2]], [i for i, r in enumerate(rows) if r[2]], s=80, color=SECOND,
               edgecolor="white", linewidth=2, zorder=4, label="Best other method (named)")
    ax.set_yticks(range(len(rows)), [FIELD_NAMES.get(r[0], r[0].replace("_", " ").capitalize()) for r in rows])
    _clean_y(ax)
    ax.set_xlim(0, 1.25)
    ax.set_xticks([0, 0.2, 0.4, 0.6, 0.8, 1.0])
    ax.set_xlabel(f"F1 per field, {focus['filings']} {focus['split']} filings")
    _legend_above(ax, 2)
    _title(ax, "Best method per field", "Fine-tuned GLiNER against date rules, temporal NER, filters, role rule and Qwen",
           legend_above=True)
    return fig
