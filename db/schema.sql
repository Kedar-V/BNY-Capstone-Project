-- BNY Capstone event datastore
-- Pipeline: public SEC docs → versioned events → BNY field values → notification drafts

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ---------------------------------------------------------------------------
-- Reference: BNY notification schema catalog
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS schema_fields (
    field_name          TEXT PRIMARY KEY,
    field_group         TEXT NOT NULL,
    source_class        TEXT NOT NULL,
    explicit_or_derived TEXT,
    ground_truth_class  TEXT,
    difficulty          TEXT,
    datastore_role      TEXT NOT NULL,
    in_v1_benchmark     BOOLEAN NOT NULL DEFAULT FALSE,
    notification_ready  TEXT,
    relevant_mvp_types  TEXT,
    relevance_note      TEXT
);

-- ---------------------------------------------------------------------------
-- Events (SEC file_num keyed corporate-action lifecycle)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS events (
    event_id                TEXT PRIMARY KEY,
    mvp_event_type          TEXT,          -- tender_offer | exchange_offer | ...
    primary_form_family     TEXT,
    primary_entity          TEXT,
    primary_cik             TEXT,
    forms                   TEXT[],
    form_families           TEXT[],
    entity_names            TEXT[],
    ciks                    TEXT[],
    tickers                 TEXT[],
    first_file_date         DATE,
    last_file_date          DATE,
    event_span_days         INTEGER,
    n_documents             INTEGER,
    n_filings               INTEGER,
    n_amendment_filings     INTEGER,
    n_initial_filings       INTEGER,
    n_exhibits              INTEGER,
    n_primary_docs          INTEGER,
    has_amendment           BOOLEAN,
    has_to_t                BOOLEAN,
    has_to_i                BOOLEAN,
    has_14d9                BOOLEAN,
    in_mvp_core             BOOLEAN DEFAULT FALSE,
    in_mvp_preferred        BOOLEAN DEFAULT FALSE,
    in_mvp_stretch          BOOLEAN DEFAULT FALSE,
    amendment_eval_band     TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_mvp_type ON events (mvp_event_type);
CREATE INDEX IF NOT EXISTS idx_events_mvp_core ON events (in_mvp_core) WHERE in_mvp_core;
CREATE INDEX IF NOT EXISTS idx_events_primary_cik ON events (primary_cik);

-- ---------------------------------------------------------------------------
-- Documents / filing hits (EFTS rows + optional local download)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS documents (
    hit_id                  TEXT PRIMARY KEY,
    event_id                TEXT REFERENCES events (event_id) ON DELETE CASCADE,
    accession               TEXT,
    filename                TEXT,
    form                    TEXT,
    form_family             TEXT,
    file_type               TEXT,
    file_description        TEXT,
    file_date               DATE,
    sequence                INTEGER,
    primary_cik             TEXT,
    entity_name             TEXT,
    primary_file_num        TEXT,
    ciks                    TEXT[],
    tickers                 TEXT[],
    file_nums               TEXT[],
    display_names           TEXT[],
    is_amendment            BOOLEAN,
    is_exhibit              BOOLEAN,
    is_primary_form_doc     BOOLEAN,
    format_guess            TEXT,
    doc_ext                 TEXT,
    -- download / content sample fields (nullable until fetched)
    edgar_url               TEXT,
    local_path              TEXT,
    download_status         TEXT,
    download_error          TEXT,
    content_sha1            TEXT,
    bytes                   INTEGER,
    words                   INTEGER,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_documents_event ON documents (event_id);
CREATE INDEX IF NOT EXISTS idx_documents_accession ON documents (accession);
CREATE INDEX IF NOT EXISTS idx_documents_form ON documents (form);
CREATE INDEX IF NOT EXISTS idx_documents_file_date ON documents (file_date);

-- ---------------------------------------------------------------------------
-- Versioned event timeline (initial → amendment(s) → final)
-- One version per distinct filing (accession) on the event
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS event_versions (
    version_id              BIGSERIAL PRIMARY KEY,
    event_id                TEXT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    version_no              INTEGER NOT NULL,
    accession               TEXT NOT NULL,
    form                    TEXT,
    file_date               DATE,
    is_amendment            BOOLEAN,
    version_status          TEXT NOT NULL DEFAULT 'active',
    -- active | superseded | cancelled | withdrawn | completed
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (event_id, version_no),
    UNIQUE (event_id, accession)
);

CREATE INDEX IF NOT EXISTS idx_event_versions_event ON event_versions (event_id, version_no);

-- ---------------------------------------------------------------------------
-- Extracted / derived BNY notification fields (the discussed schema)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS event_field_values (
    id                      BIGSERIAL PRIMARY KEY,
    event_id                TEXT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    version_id              BIGINT REFERENCES event_versions (version_id) ON DELETE CASCADE,
    field_name              TEXT NOT NULL REFERENCES schema_fields (field_name),
    value_text              TEXT,
    value_normalized        TEXT,
    value_json              JSONB,
    source_hit_id           TEXT REFERENCES documents (hit_id) ON DELETE SET NULL,
    source_accession        TEXT,
    source_section          TEXT,
    source_quote            TEXT,
    confidence              REAL,
    extraction_method       TEXT NOT NULL DEFAULT 'unknown',
    -- metadata | regex | llm | manual | derived | placeholder
    is_current              BOOLEAN NOT NULL DEFAULT TRUE,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (version_id, field_name)
);

CREATE INDEX IF NOT EXISTS idx_field_values_event ON event_field_values (event_id);
CREATE INDEX IF NOT EXISTS idx_field_values_field ON event_field_values (field_name);
CREATE INDEX IF NOT EXISTS idx_field_values_current ON event_field_values (event_id, field_name)
    WHERE is_current;

-- ---------------------------------------------------------------------------
-- Optional notification draft rows (BNY-shaped output for demos)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notification_drafts (
    draft_id                BIGSERIAL PRIMARY KEY,
    event_id                TEXT NOT NULL REFERENCES events (event_id) ON DELETE CASCADE,
    version_id              BIGINT REFERENCES event_versions (version_id) ON DELETE SET NULL,
    notification_family     TEXT DEFAULT 'Corporate Action Notification',
    notification_type       TEXT,          -- ANNOUNCEMENT | REMINDER | CANCELLED ...
    notification_status     TEXT,
    payload_json            JSONB NOT NULL DEFAULT '{}'::jsonb,
    generation_method       TEXT DEFAULT 'template',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notification_drafts_event ON notification_drafts (event_id);

-- ---------------------------------------------------------------------------
-- Convenient current-state view (latest version fields pivoted later in app)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW v_event_current_fields AS
SELECT
    e.event_id,
    e.mvp_event_type,
    e.primary_entity,
    e.primary_form_family,
    e.in_mvp_preferred,
    f.field_name,
    f.field_group,
    f.datastore_role,
    v.value_text,
    v.value_normalized,
    v.value_json,
    v.extraction_method,
    v.confidence,
    v.source_accession,
    v.source_quote
FROM events e
JOIN event_field_values v ON v.event_id = e.event_id AND v.is_current
JOIN schema_fields f ON f.field_name = v.field_name;
