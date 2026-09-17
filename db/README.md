# Postgres event datastore

Local Postgres holds the **versioned corporate-action event store** used for the
notification MVP:

```text
schema_fields          BNY notification field catalog
events                 SEC file_num–keyed events (+ MVP flags)
documents              EFTS filing/document hits (+ optional downloads)
event_versions         initial → amendment timeline per event
event_field_values     extracted/derived BNY fields with evidence columns
notification_drafts    optional BNY-shaped draft payloads
```

## Start database

```bash
docker compose up -d
# waits on localhost:5433  (host 5432 left free)
```

Default credentials (dev only):

| Setting | Value |
|---------|-------|
| user | `bny` |
| password | `bny` |
| database | `bny_capstone` |
| URL | `postgresql://bny:bny@localhost:5433/bny_capstone` |

Copy `.env.example` → `.env` if you want to override `DATABASE_URL`.

## Load corpus

Requires processed parquet from `scripts/build_corpus.py` / prior EDA run.

```bash
pip install -r requirements.txt
python scripts/init_db.py
```

This truncates and reloads:

1. `schema_fields` from the datastore field catalog  
2. `events` + MVP tags  
3. `documents` (+ content-sample download paths when present)  
4. `event_versions` (one row per accession)  
5. seed `event_field_values` for metadata-backed fields (`corporate_action_type`, `security_description`, `ticker`, `notification_status`) and internal placeholders on preferred MVP events  

## Quick checks

```bash
psql postgresql://bny:bny@localhost:5433/bny_capstone -c "
SELECT
  (SELECT COUNT(*) FROM events) AS events,
  (SELECT COUNT(*) FROM documents) AS documents,
  (SELECT COUNT(*) FROM event_versions) AS versions,
  (SELECT COUNT(*) FROM event_field_values) AS fields,
  (SELECT COUNT(*) FROM events WHERE in_mvp_preferred) AS mvp_preferred;
"
```

View current extracted fields:

```sql
SELECT * FROM v_event_current_fields LIMIT 20;
```
