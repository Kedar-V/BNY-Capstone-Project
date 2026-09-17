"""Load parquet corpus + EDA catalog into Postgres event datastore."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import psycopg

from eda.config import PROCESSED_DIR, PROJECT_ROOT
from eda.mvp import build_datastore_field_catalog, tag_mvp_events
from .connection import connect


OUTPUTS = PROJECT_ROOT / "outputs"


def _as_str_list(value: Any) -> list[str] | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, list):
        return [str(x) for x in value if x is not None and not (isinstance(x, float) and pd.isna(x))]
    try:
        import numpy as np

        if isinstance(value, np.ndarray):
            return [str(x) for x in value.tolist()]
    except Exception:  # noqa: BLE001
        pass
    return [str(value)]


def _date(value: Any):
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    ts = pd.to_datetime(value, errors="coerce")
    if pd.isna(ts):
        return None
    return ts.date()


def _bool(value: Any) -> bool | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    return bool(value)


def _int(value: Any) -> int | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return None


def apply_schema(conn: psycopg.Connection, schema_path: Path | None = None) -> None:
    schema_path = schema_path or (PROJECT_ROOT / "db" / "schema.sql")
    sql = schema_path.read_text(encoding="utf-8")
    conn.execute(sql)


def truncate_all(conn: psycopg.Connection) -> None:
    conn.execute(
        """
        TRUNCATE TABLE
            notification_drafts,
            event_field_values,
            event_versions,
            documents,
            events,
            schema_fields
        RESTART IDENTITY CASCADE
        """
    )


def load_schema_fields(conn: psycopg.Connection, catalog: pd.DataFrame | None = None) -> int:
    if catalog is None:
        catalog_path = OUTPUTS / "datastore_field_catalog.csv"
        catalog = pd.read_csv(catalog_path) if catalog_path.exists() else build_datastore_field_catalog()

    rows = []
    for _, r in catalog.iterrows():
        rows.append(
            (
                r["field"],
                r.get("group"),
                r.get("source_class"),
                r.get("explicit_or_derived"),
                r.get("ground_truth_class"),
                r.get("difficulty"),
                r.get("datastore_role"),
                bool(r.get("in_v1_benchmark", False)),
                r.get("notification_ready"),
                r.get("relevant_mvp_types"),
                r.get("relevance_note"),
            )
        )
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO schema_fields (
                field_name, field_group, source_class, explicit_or_derived,
                ground_truth_class, difficulty, datastore_role, in_v1_benchmark,
                notification_ready, relevant_mvp_types, relevance_note
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
            )
            ON CONFLICT (field_name) DO UPDATE SET
                field_group = EXCLUDED.field_group,
                source_class = EXCLUDED.source_class,
                datastore_role = EXCLUDED.datastore_role,
                in_v1_benchmark = EXCLUDED.in_v1_benchmark,
                notification_ready = EXCLUDED.notification_ready,
                relevant_mvp_types = EXCLUDED.relevant_mvp_types,
                relevance_note = EXCLUDED.relevance_note
            """,
            rows,
        )
    return len(rows)


def load_events(conn: psycopg.Connection, events: pd.DataFrame) -> int:
    tagged = tag_mvp_events(events)
    rows = []
    for _, r in tagged.iterrows():
        rows.append(
            (
                r["event_id"],
                r.get("mvp_event_type_provisional"),
                r.get("primary_form_family"),
                r.get("primary_entity"),
                r.get("primary_cik"),
                _as_str_list(r.get("forms")),
                _as_str_list(r.get("form_families")),
                _as_str_list(r.get("entity_names")),
                _as_str_list(r.get("ciks")),
                _as_str_list(r.get("tickers")),
                _date(r.get("first_file_date")),
                _date(r.get("last_file_date")),
                _int(r.get("event_span_days")),
                _int(r.get("n_documents")),
                _int(r.get("n_filings")),
                _int(r.get("n_amendment_filings")),
                _int(r.get("n_initial_filings")),
                _int(r.get("n_exhibits")),
                _int(r.get("n_primary_docs")),
                _bool(r.get("has_amendment")),
                _bool(r.get("has_to_t")),
                _bool(r.get("has_to_i")),
                _bool(r.get("has_14d9")),
                _bool(r.get("in_mvp_core")),
                _bool(r.get("in_mvp_preferred")),
                _bool(r.get("in_mvp_stretch")),
                r.get("amendment_eval_band"),
            )
        )
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO events (
                event_id, mvp_event_type, primary_form_family, primary_entity, primary_cik,
                forms, form_families, entity_names, ciks, tickers,
                first_file_date, last_file_date, event_span_days,
                n_documents, n_filings, n_amendment_filings, n_initial_filings,
                n_exhibits, n_primary_docs, has_amendment,
                has_to_t, has_to_i, has_14d9,
                in_mvp_core, in_mvp_preferred, in_mvp_stretch, amendment_eval_band
            ) VALUES (
                %s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,
                %s,%s,%s,%s
            )
            ON CONFLICT (event_id) DO UPDATE SET
                mvp_event_type = EXCLUDED.mvp_event_type,
                primary_form_family = EXCLUDED.primary_form_family,
                primary_entity = EXCLUDED.primary_entity,
                n_documents = EXCLUDED.n_documents,
                n_filings = EXCLUDED.n_filings,
                in_mvp_core = EXCLUDED.in_mvp_core,
                in_mvp_preferred = EXCLUDED.in_mvp_preferred,
                updated_at = NOW()
            """,
            rows,
        )
    return len(rows)


def load_documents(conn: psycopg.Connection, docs: pd.DataFrame, content_sample: pd.DataFrame | None) -> int:
    sample_map: dict[tuple[str, str], dict] = {}
    if content_sample is not None and not content_sample.empty:
        for _, s in content_sample.iterrows():
            key = (str(s.get("accession")), str(s.get("filename")))
            sample_map[key] = s.to_dict()

    # Ensure parent events exist for any orphan docs (shouldn't happen)
    event_ids = set(docs["event_id"].dropna().astype(str))
    with conn.cursor() as cur:
        cur.execute("SELECT event_id FROM events")
        existing = {r["event_id"] for r in cur.fetchall()}
    missing = event_ids - existing
    if missing:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO events (event_id) VALUES (%s) ON CONFLICT DO NOTHING",
                [(e,) for e in sorted(missing)],
            )

    rows = []
    for _, r in docs.iterrows():
        accession = r.get("accession")
        filename = r.get("filename")
        sample = sample_map.get((str(accession), str(filename)), {})
        cik = r.get("primary_cik")
        edgar_url = sample.get("url")
        if not edgar_url and accession and filename and cik:
            edgar_url = (
                f"https://www.sec.gov/Archives/edgar/data/{int(str(cik))}/"
                f"{str(accession).replace('-', '')}/{filename}"
            )
        rows.append(
            (
                r["hit_id"],
                r.get("event_id"),
                accession,
                filename,
                r.get("form"),
                r.get("form_family"),
                r.get("file_type"),
                r.get("file_description"),
                _date(r.get("file_date")),
                _int(r.get("sequence")),
                cik,
                r.get("entity_name"),
                r.get("primary_file_num"),
                _as_str_list(r.get("ciks")),
                _as_str_list(r.get("tickers")),
                _as_str_list(r.get("file_nums")),
                _as_str_list(r.get("display_names")),
                _bool(r.get("is_amendment")),
                _bool(r.get("is_exhibit")),
                _bool(r.get("is_primary_form_doc")),
                r.get("format_guess"),
                r.get("doc_ext"),
                edgar_url,
                sample.get("local_path"),
                sample.get("status"),
                sample.get("error"),
                sample.get("content_sha1"),
                _int(sample.get("bytes")),
                _int(sample.get("words")),
            )
        )

    with conn.cursor() as cur:
        # batch insert in chunks
        chunk = 2000
        sql = """
            INSERT INTO documents (
                hit_id, event_id, accession, filename, form, form_family, file_type,
                file_description, file_date, sequence, primary_cik, entity_name,
                primary_file_num, ciks, tickers, file_nums, display_names,
                is_amendment, is_exhibit, is_primary_form_doc, format_guess, doc_ext,
                edgar_url, local_path, download_status, download_error, content_sha1,
                bytes, words
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,
                %s,%s,%s,%s,%s,
                %s,%s
            )
            ON CONFLICT (hit_id) DO UPDATE SET
                event_id = EXCLUDED.event_id,
                local_path = COALESCE(EXCLUDED.local_path, documents.local_path),
                download_status = COALESCE(EXCLUDED.download_status, documents.download_status),
                content_sha1 = COALESCE(EXCLUDED.content_sha1, documents.content_sha1)
        """
        for i in range(0, len(rows), chunk):
            cur.executemany(sql, rows[i : i + chunk])
    return len(rows)


def build_event_versions(conn: psycopg.Connection) -> int:
    """Create one version row per accession, ordered by file_date within event."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO event_versions (
                event_id, version_no, accession, form, file_date, is_amendment, version_status
            )
            SELECT
                event_id,
                ROW_NUMBER() OVER (
                    PARTITION BY event_id
                    ORDER BY file_date NULLS LAST, accession
                )::int AS version_no,
                accession,
                form,
                file_date,
                is_amendment,
                CASE WHEN is_amendment THEN 'amended' ELSE 'initial' END AS version_status
            FROM (
                SELECT
                    event_id,
                    accession,
                    MIN(form) AS form,
                    MIN(file_date) AS file_date,
                    BOOL_OR(COALESCE(is_amendment, FALSE)) AS is_amendment
                FROM documents
                WHERE event_id IS NOT NULL AND accession IS NOT NULL
                GROUP BY event_id, accession
            ) filing
            ON CONFLICT (event_id, accession) DO NOTHING
            """
        )
        return cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0


def seed_metadata_field_values(conn: psycopg.Connection) -> int:
    """Seed BNY fields that are directly available from event metadata."""
    with conn.cursor() as cur:
        # corporate_action_type
        cur.execute(
            """
            INSERT INTO event_field_values (
                event_id, version_id, field_name, value_text, value_normalized,
                extraction_method, confidence, is_current
            )
            SELECT
                e.event_id,
                v.version_id,
                'corporate_action_type',
                COALESCE(e.mvp_event_type, e.primary_form_family),
                COALESCE(e.mvp_event_type, e.primary_form_family),
                'derived',
                0.9,
                TRUE
            FROM events e
            JOIN LATERAL (
                SELECT version_id
                FROM event_versions ev
                WHERE ev.event_id = e.event_id
                ORDER BY version_no DESC
                LIMIT 1
            ) v ON TRUE
            ON CONFLICT (version_id, field_name) DO NOTHING
            """
        )
        n = cur.rowcount or 0

        cur.execute(
            """
            INSERT INTO event_field_values (
                event_id, version_id, field_name, value_text, value_normalized,
                extraction_method, confidence, is_current
            )
            SELECT
                e.event_id, v.version_id, 'security_description',
                e.primary_entity, e.primary_entity, 'metadata', 0.6, TRUE
            FROM events e
            JOIN LATERAL (
                SELECT version_id FROM event_versions ev
                WHERE ev.event_id = e.event_id ORDER BY version_no DESC LIMIT 1
            ) v ON TRUE
            WHERE e.primary_entity IS NOT NULL
            ON CONFLICT (version_id, field_name) DO NOTHING
            """
        )
        n += cur.rowcount or 0

        cur.execute(
            """
            INSERT INTO event_field_values (
                event_id, version_id, field_name, value_text, value_normalized,
                value_json, extraction_method, confidence, is_current
            )
            SELECT
                e.event_id, v.version_id, 'ticker',
                COALESCE(e.tickers[1], NULL),
                COALESCE(e.tickers[1], NULL),
                to_jsonb(e.tickers),
                'metadata', 0.55, TRUE
            FROM events e
            JOIN LATERAL (
                SELECT version_id FROM event_versions ev
                WHERE ev.event_id = e.event_id ORDER BY version_no DESC LIMIT 1
            ) v ON TRUE
            WHERE e.tickers IS NOT NULL AND cardinality(e.tickers) > 0
            ON CONFLICT (version_id, field_name) DO NOTHING
            """
        )
        n += cur.rowcount or 0

        cur.execute(
            """
            INSERT INTO event_field_values (
                event_id, version_id, field_name, value_text, value_normalized,
                extraction_method, confidence, is_current
            )
            SELECT
                e.event_id, v.version_id, 'notification_status',
                CASE WHEN e.has_amendment THEN 'AMENDED' ELSE 'ANNOUNCEMENT' END,
                CASE WHEN e.has_amendment THEN 'AMENDED' ELSE 'ANNOUNCEMENT' END,
                'derived', 0.5, TRUE
            FROM events e
            JOIN LATERAL (
                SELECT version_id FROM event_versions ev
                WHERE ev.event_id = e.event_id ORDER BY version_no DESC LIMIT 1
            ) v ON TRUE
            ON CONFLICT (version_id, field_name) DO NOTHING
            """
        )
        n += cur.rowcount or 0

        # Internal placeholders on preferred MVP events (demo parity)
        for field in (
            "processing_status",
            "eligible_quantity",
            "position_quantity",
            "debit_credit_indicator",
        ):
            cur.execute(
                f"""
                INSERT INTO event_field_values (
                    event_id, version_id, field_name, value_text, value_normalized,
                    extraction_method, confidence, is_current
                )
                SELECT
                    e.event_id, v.version_id, %s,
                    NULL, NULL, 'placeholder', 0.0, TRUE
                FROM events e
                JOIN LATERAL (
                    SELECT version_id FROM event_versions ev
                    WHERE ev.event_id = e.event_id ORDER BY version_no DESC LIMIT 1
                ) v ON TRUE
                WHERE e.in_mvp_preferred
                ON CONFLICT (version_id, field_name) DO NOTHING
                """,
                (field,),
            )
            n += cur.rowcount or 0

    return n


def load_all(
    *,
    reset: bool = True,
    dsn: str | None = None,
) -> dict[str, int]:
    docs = pd.read_parquet(PROCESSED_DIR / "documents.parquet")
    events = pd.read_parquet(PROCESSED_DIR / "events.parquet")
    sample_path = PROCESSED_DIR / "content_sample.parquet"
    content_sample = pd.read_parquet(sample_path) if sample_path.exists() else None

    with connect(dsn) as conn:
        apply_schema(conn)
        if reset:
            truncate_all(conn)
        counts = {
            "schema_fields": load_schema_fields(conn),
            "events": load_events(conn, events),
            "documents": load_documents(conn, docs, content_sample),
        }
        counts["event_versions"] = build_event_versions(conn)
        counts["event_field_values_seeded"] = seed_metadata_field_values(conn)
    return counts
