#!/usr/bin/env python3
"""Redraw merger figures 14 (stack ladder) and 15 (per-field F1, before → now).

Example:
  python scripts/plot_merger_stack_figures.py --extra probe_merger_target_sec_ctype:target
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load(name: str, path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


S = _load("_stack_merger_fig", "scripts/stack_merger_preds.py")
FIGDIR = ROOT / "outputs/merger_eval/figures"
ACCENT, MUTE, REF, GOAL, INK = "#2F6FED", "#9AA3AD", "#5C6570", "#2A7A4B", "#1A1F26"
ORACLE_F1 = 0.837
LABEL = {
    "acquirer": "Acquirer", "target": "Target", "consideration_type": "Consideration type",
    "cash_consideration": "Cash consideration", "stock_exchange_ratio": "Stock exchange ratio",
    "shareholder_vote_date": "Shareholder vote date", "election_deadline": "Election deadline",
    "effective_date": "Effective date", "security_description": "Security description",
    "ticker": "Ticker", "cusip": "CUSIP", "isin": "ISIN",
}
STEP_LABEL = {
    "base": "Frozen oneshot",
    "cdrop_restore": "+ keep soft-match",
    "date_abstain": "+ date FP abstain",
    "prompt_fewshot": "+ prompt / few-shot",
    "probe_merger_packfix_ticker_ratio": "+ packfix ticker/ratio",
    "probe_merger_target_sec_ctype": "+ target prompt",
    "cross_field": "+ cross-field rules",
}


def _style() -> None:
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
        "axes.linewidth": 0.6, "figure.facecolor": "white",
    })


def _axes(ax, xlabel: str) -> None:
    ax.set_xlim(0, 1.05)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1])
    ax.set_xticklabels(["0", ".25", ".50", ".75", "1.0"])
    ax.set_xlabel(xlabel)
    ax.xaxis.grid(True, color="#E6E8EB", lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)


def _live_cdrop(base: dict, gold: dict) -> float:
    live = dict(base)
    ck = S.RUNS / "probe_merger_cdrop_validate_fix/checkpoint.jsonl"
    for line in ck.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        pred = row.get("pred") or ""
        if "result" in row:
            pred = (row.get("result") or {}).get("pred") or ""
        live[(int(row["ei"]), str(row["field"]))] = S._clean(pred)
    return S.score(live, gold)[0]["f1"]


def plot_ladder(steps, gold, live_f1: float) -> dict:
    scored = [(STEP_LABEL.get(name, name), S.score(p, gold)[0]) for name, p in steps]
    ladder = [(scored[0][0], scored[0][1]["f1"]), ("+ C_drop replay", live_f1)]
    ladder += [(lab, m["f1"]) for lab, m in scored[1:]]
    final = scored[-1][1]

    fig, ax = plt.subplots(figsize=(10.0, 5.8), dpi=160)
    y = np.arange(len(ladder))[::-1]
    vals = [v for _, v in ladder]
    ax.barh(y, vals, height=0.55, color=[MUTE] * (len(ladder) - 1) + [ACCENT],
            edgecolor="none", zorder=3)
    ax.axvline(ORACLE_F1, color=REF, ls="--", lw=1.1)
    ax.text(ORACLE_F1 + 0.012, y[0] + 0.35, f"oracle {ORACLE_F1:.2f}", color=REF, fontsize=9)
    ax.axvline(0.60, color=GOAL, ls=":", lw=1.1)
    for i, (yi, v) in enumerate(zip(y, vals)):
        txt = f"{v:.3f}" if i == 0 else f"{v:.3f}  ({v - vals[i - 1]:+.3f})"
        ax.text(v + 0.012, yi, txt, va="center", fontsize=9.5,
                color=INK, fontweight="bold" if i == len(vals) - 1 else "normal")
    ax.set_yticks(y)
    ax.set_yticklabels([lab for lab, _ in ladder], fontsize=10)
    _axes(ax, "Soft-match micro F1")
    fig.suptitle(f"Merger balanced200: stacked soft F1 reaches {final['f1']:.2f}",
                 x=0.02, y=0.98, ha="left", fontsize=13, fontweight="500")
    ax.set_title("qwen3-finance · prompts + few-shot + refreshed bags + cross-field rules · 200 cells",
                 loc="left", fontsize=9, color=REF, pad=8)
    fig.text(0.98, 0.97, f"Now {final['f1']:.3f}\nP {final['p']:.2f} · R {final['r']:.2f}",
             ha="right", va="top", fontsize=9,
             bbox=dict(boxstyle="round,pad=0.35", facecolor="#F4F6F8", edgecolor="#D5DAE0", lw=0.8))
    fig.tight_layout(rect=[0.02, 0.04, 0.98, 0.88])
    fig.savefig(FIGDIR / "14_merger_prompt_stack_soft_f1.png", dpi=160, bbox_inches="tight")
    plt.close(fig)
    return {lab: round(v, 4) for lab, v in ladder}


def plot_per_field(before: dict, now: dict, micro: dict) -> None:
    rows = sorted(now, key=lambda f: (-now[f]["f1"], LABEL.get(f, f)))
    y = np.arange(len(rows))[::-1]
    vals = [now[f]["f1"] for f in rows]
    prev = [before[f]["f1"] for f in rows]

    fig, ax = plt.subplots(figsize=(9.6, 6.2), dpi=160)
    ax.barh(y, vals, height=0.68, color=[ACCENT if v >= micro["f1"] else MUTE for v in vals],
            edgecolor="none", zorder=3)
    moved = [i for i, (a, b) in enumerate(zip(prev, vals)) if abs(b - a) > 1e-9]
    ax.scatter([prev[i] for i in moved], [y[i] for i in moved], marker="|", s=260,
               color=INK, linewidths=1.6, zorder=4)
    ax.axvline(micro["f1"], color=REF, ls="--", lw=1.1)
    ax.text(micro["f1"] + 0.012, y[0] + 0.55, f"micro {micro['f1']:.2f}", color=REF, fontsize=9)
    for i, (yi, v) in enumerate(zip(y, vals)):
        inside = v >= 0.97
        txt = f"{v:.2f}" if i not in moved else f"{v:.2f}  (+{v - prev[i]:.2f})"
        ax.text(v - 0.02 if inside else v + 0.015, yi, txt, va="center",
                ha="right" if inside else "left", fontsize=9,
                color="white" if inside else INK)
    ax.set_yticks(y)
    ax.set_yticklabels([LABEL.get(f, f) for f in rows], fontsize=10)
    _axes(ax, "Per-field soft-match F1")
    fig.suptitle("Cross-field rules and target prompt lift four fields; election still a GT issue",
                 x=0.02, y=0.98, ha="left", fontsize=12.5, fontweight="500")
    ax.set_title("Merger balanced200 soft-match · black tick = per-field F1 before this round (0.693 stack)",
                 loc="left", fontsize=9, color=REF, pad=8)
    fig.text(0.98, 0.97, f"Micro F1  {micro['f1']:.3f}\nP {micro['p']:.2f} · R {micro['r']:.2f}",
             ha="right", va="top", fontsize=9,
             bbox=dict(boxstyle="round,pad=0.35", facecolor="#F4F6F8", edgecolor="#D5DAE0", lw=0.8))
    fig.tight_layout(rect=[0.02, 0.04, 0.98, 0.90])
    fig.savefig(FIGDIR / "15_merger_best_stacked_per_field_f1.png", dpi=160, bbox_inches="tight")
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--extra", action="append", default=[])
    args = p.parse_args(argv)

    _style()
    records, gold = S.load_gold()
    steps: list = []
    S.build_stack(records, gold, args.extra, cross_field=True, steps=steps)
    by_name = dict(steps)
    before = S.score(by_name["probe_merger_packfix_ticker_ratio"], gold)[1]
    micro, now = S.score(steps[-1][1], gold)

    ladder = plot_ladder(steps, gold, _live_cdrop(by_name["base"], gold))
    plot_per_field(before, now, micro)
    (S.RUNS / "stack_merger_crossfield_target/figure_summary.json").write_text(json.dumps(
        {"ladder": ladder, "micro": micro,
         "per_field_before": {f: round(v["f1"], 4) for f, v in before.items()},
         "per_field_now": {f: round(v["f1"], 4) for f, v in now.items()}}, indent=2))
    print("ladder:", ladder)
    print("wrote", FIGDIR / "14_merger_prompt_stack_soft_f1.png")
    print("wrote", FIGDIR / "15_merger_best_stacked_per_field_f1.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
