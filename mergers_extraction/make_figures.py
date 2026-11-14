#!/usr/bin/env python3
"""Save the charts used in FINETUNING.md to figures/, from the saved result files (no model runs).

    python mergers_extraction/make_figures.py
The same charts, for any run, are in visualize_mergers_results.ipynb.
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import results  # noqa: E402

if __name__ == "__main__":
    runs = results.discover_runs()
    focus = results.default_focus(runs)
    figures = {
        "01_overall_micro_f1.png": results.overall_chart(results.comparable(runs, focus), focus),
        "02_per_field_f1.png": results.per_field_chart(focus, results.baseline_for(runs, focus)),
        "03_window_coverage.png": results.window_budget_chart(),
        "04_window_coverage_by_field.png": results.window_fields_chart(),
        "05_training_values_located.png": results.training_data_chart(),
        "06_training_loss.png": results.training_loss_chart(focus["model"]),
        "07_best_method_per_field.png": results.methods_chart(results.comparable(runs, focus), focus),
    }
    for name, fig in figures.items():
        print("wrote", results.save(fig, name))
        plt.close(fig)
