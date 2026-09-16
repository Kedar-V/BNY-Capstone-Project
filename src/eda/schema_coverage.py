"""BNY schema coverage estimation from metadata + sampled document text."""

from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from .bny_schema import BNY_SCHEMA, RELEVANCE_BY_ACTION, SCHEMA_BY_NAME
from .documents import html_to_text


def _load_text(path: str | None) -> str:
    if not path:
        return ""
    raw = Path(path).read_bytes().decode("utf-8", errors="replace")
    if "<html" in raw[:1200].lower() or raw.lstrip().lower().startswith("<!doctype"):
        return html_to_text(raw)
    return raw


def scan_document_fields(text: str) -> dict[str, bool]:
    out: dict[str, bool] = {}
    for field in BNY_SCHEMA:
        if field.source_class == "bny_internal_only" or not field.patterns:
            out[field.name] = False
            continue
        out[field.name] = any(p.search(text or "") for p in field.patterns)
    return out


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, float) and pd.isna(value):
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return value.tolist()
    except Exception:  # noqa: BLE001
        pass
    return [value]


def _metadata_event_signals(events: pd.DataFrame, docs: pd.DataFrame) -> pd.DataFrame:
    """Observed metadata that can populate a subset of BNY fields without text."""
    rows = []
    for _, ev in events.iterrows():
        tickers = _as_list(ev.get("tickers"))
        rows.append(
            {
                "event_id": ev["event_id"],
                "corporate_action_type_meta": True,  # from form family
                "ticker_meta": len(tickers) > 0,
                "security_description_meta": bool(ev.get("primary_entity")),
                "notification_status_meta": bool(ev.get("has_amendment")),
                "primary_form_family": ev.get("primary_form_family"),
            }
        )
    return pd.DataFrame(rows)


def analyze_schema_coverage(
    docs: pd.DataFrame,
    events: pd.DataFrame,
    content_sample: pd.DataFrame,
) -> dict[str, Any]:
    """
    Compute field coverage.

    Important:
    - Public coverage % for text fields is computed on the **sample of events that have
      successfully downloaded document text**, then reported with denominator notes.
    - Internal-only fields are reported as 0% public coverage by definition (not fabricated).
    - Metadata-backed fields can also be scored on the full event table.
    """
    meta_signals = _metadata_event_signals(events, docs)

    # Attach scanned flags to sample docs
    scanned_rows = []
    for _, row in content_sample.iterrows():
        base = {
            "event_id": row.get("event_id"),
            "accession": row.get("accession"),
            "form": row.get("form"),
            "status": row.get("status"),
            "filename": row.get("filename"),
        }
        if row.get("status") != "ok":
            base["scan_ok"] = False
            scanned_rows.append(base)
            continue
        text = _load_text(row.get("local_path"))
        flags = scan_document_fields(text)
        base.update(flags)
        base["scan_ok"] = True
        base["words"] = len(text.split())
        scanned_rows.append(base)
    doc_scans = pd.DataFrame(scanned_rows)

    ok_docs = doc_scans[doc_scans.get("scan_ok") == True] if "scan_ok" in doc_scans else doc_scans.iloc[0:0]  # noqa: E712
    sample_event_ids = sorted(ok_docs["event_id"].dropna().unique()) if not ok_docs.empty else []

    # Event-level OR across sampled docs for that event
    event_text_flags = pd.DataFrame({"event_id": sample_event_ids})
    if sample_event_ids and not ok_docs.empty:
        field_names = [f.name for f in BNY_SCHEMA if f.patterns]
        agg = ok_docs.groupby("event_id")[field_names].any().reset_index()
        event_text_flags = agg

    event_text_flags = event_text_flags.merge(
        events[["event_id", "primary_form_family", "has_amendment"]],
        on="event_id",
        how="left",
    )
    event_text_flags = event_text_flags.merge(meta_signals, on="event_id", how="left", suffixes=("", "_m"))

    n_sample_events = len(event_text_flags)
    n_all_events = len(events)

    matrix_rows = []
    for field in BNY_SCHEMA:
        name = field.name
        if field.source_class == "bny_internal_only":
            public_cov = 0.0
            missing = 100.0
            primary_source = "internal BNY"
            evidence = "internal_only"
            n_detected = 0
            denom = n_all_events
            denom_note = "all_events_definitional_zero"
        elif name == "corporate_action_type":
            # Observed for all events via form family mapping
            public_cov = 100.0 if n_all_events else 0.0
            missing = 0.0
            primary_source = "EFTS form family"
            evidence = "observed_metadata"
            n_detected = n_all_events
            denom = n_all_events
            denom_note = "all_events_metadata"
        elif name == "ticker":
            n_detected = int(meta_signals["ticker_meta"].sum())
            # Also count text detections in sample, but report metadata coverage on full set
            # plus sample text uplift separately in notes.
            public_cov = round(100.0 * n_detected / n_all_events, 2) if n_all_events else 0.0
            missing = round(100.0 - public_cov, 2)
            primary_source = "EFTS display_names (metadata)"
            evidence = "observed_metadata"
            denom = n_all_events
            denom_note = "all_events_metadata"
            if n_sample_events and name in event_text_flags.columns:
                text_rate = 100.0 * event_text_flags[name].mean()
                denom_note += f"; sample_text_detection_pct={text_rate:.1f}"
        elif name == "security_description":
            n_detected = int(meta_signals["security_description_meta"].sum())
            public_cov = round(100.0 * n_detected / n_all_events, 2) if n_all_events else 0.0
            missing = round(100.0 - public_cov, 2)
            primary_source = "EFTS entity_name / filing text"
            evidence = "observed_metadata"
            denom = n_all_events
            denom_note = "all_events_metadata"
        elif not field.patterns:
            public_cov = 0.0
            missing = 100.0
            primary_source = "not measured"
            evidence = "not_measured"
            n_detected = 0
            denom = n_sample_events
            denom_note = "no_public_patterns_or_internal"
        else:
            if n_sample_events == 0 or name not in event_text_flags.columns:
                public_cov = float("nan")
                missing = float("nan")
                n_detected = 0
                denom = 0
                denom_note = "no_successful_text_sample"
                primary_source = "insufficient sample"
                evidence = "not_measured"
            else:
                n_detected = int(event_text_flags[name].sum())
                public_cov = round(100.0 * n_detected / n_sample_events, 2)
                missing = round(100.0 - public_cov, 2)
                # Primary source = form with highest detection rate among ok docs
                if name in ok_docs.columns and not ok_docs.empty:
                    by_form = ok_docs.groupby("form")[name].mean().sort_values(ascending=False)
                    primary_source = str(by_form.index[0]) if len(by_form) else "sample text"
                else:
                    primary_source = "sample text"
                evidence = "inferred_regex_presence"
                denom = n_sample_events
                denom_note = "sample_events_with_downloaded_text"

        matrix_rows.append(
            {
                "field": name,
                "group": field.group,
                "public_coverage_pct": public_cov,
                "missing_pct": missing,
                "n_detected_events": n_detected,
                "n_events_denominator": denom,
                "denominator_note": denom_note,
                "primary_source": primary_source,
                "explicit_or_derived": field.explicit_or_derived,
                "difficulty": field.default_difficulty,
                "source_class": field.source_class,
                "ground_truth_class": field.ground_truth,
                "evidence_type": evidence,
                "relevance_note": field.relevance_note,
            }
        )

    schema_coverage = pd.DataFrame(matrix_rows)

    # Event-type × field coverage on sample events
    type_rows = []
    if n_sample_events and not event_text_flags.empty:
        for action, g in event_text_flags.groupby(event_text_flags["primary_form_family"].fillna("unknown")):
            for field in BNY_SCHEMA:
                name = field.name
                rel = RELEVANCE_BY_ACTION.get(str(action), {}).get(name, "relevant")
                if field.source_class == "bny_internal_only":
                    cov = 0.0
                    evidence = "internal_only"
                elif name == "corporate_action_type":
                    cov = 100.0
                    evidence = "observed_metadata"
                elif name in g.columns:
                    cov = round(100.0 * g[name].mean(), 2)
                    evidence = "inferred_regex_presence"
                elif name == "ticker":
                    cov = round(100.0 * g.get("ticker_meta", pd.Series(dtype=float)).mean(), 2) if "ticker_meta" in g else float("nan")
                    evidence = "observed_metadata"
                else:
                    cov = float("nan")
                    evidence = "not_measured"
                type_rows.append(
                    {
                        "corporate_action_type": action,
                        "field": name,
                        "coverage_pct": cov,
                        "n_sample_events": int(len(g)),
                        "relevance_assumption": rel,
                        "evidence_type": evidence,
                    }
                )
    event_type_coverage = pd.DataFrame(type_rows)

    # Which source form most often contains each field (sample docs)
    source_pref = []
    if not ok_docs.empty:
        for field in BNY_SCHEMA:
            if field.name not in ok_docs.columns:
                continue
            rates = ok_docs.groupby("form")[field.name].mean().sort_values(ascending=False)
            for form, rate in rates.items():
                source_pref.append(
                    {
                        "field": field.name,
                        "form": form,
                        "doc_detection_rate_pct": round(100.0 * rate, 2),
                        "n_docs": int((ok_docs["form"] == form).sum()),
                    }
                )
    source_preference = pd.DataFrame(source_pref)

    return {
        "schema_coverage": schema_coverage,
        "event_type_coverage": event_type_coverage,
        "source_preference": source_preference,
        "doc_scans": doc_scans,
        "event_text_flags": event_text_flags,
        "n_sample_events": n_sample_events,
        "n_all_events": n_all_events,
        "note": (
            "Text-field coverage percentages are inferred from regex presence on downloaded "
            f"sample documents covering {n_sample_events} events. "
            "They measure mention detection, not successful structured extraction. "
            "Internal-only fields are definitionally 0% public coverage."
        ),
    }
