-- Схема PostgreSQL для сервиса моделирования трасс (Спринт 1).

CREATE TABLE IF NOT EXISTS jobs (
    id            UUID PRIMARY KEY,
    filename      VARCHAR(512) NOT NULL,
    size_bytes    BIGINT       NOT NULL DEFAULT 0,
    status        VARCHAR(32)  NOT NULL DEFAULT 'QUEUED',
    input_path    VARCHAR(1024),
    result_path   VARCHAR(1024),
    error_message TEXT,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- До трёх вариантов трассировки на задание (§2.8 ТЗ) — наполнение со Спринта 3.
CREATE TABLE IF NOT EXISTS variants (
    id             UUID PRIMARY KEY,
    job_id         UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    rank           INT  NOT NULL,
    score          NUMERIC(14, 4),
    cost_total     NUMERIC(16, 2),
    length_total_m NUMERIC(14, 2),
    payload        JSONB,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Файлы-артефакты задания (вход, результат, отчёты).
CREATE TABLE IF NOT EXISTS artifacts (
    id         UUID PRIMARY KEY,
    job_id     UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    kind       VARCHAR(64)   NOT NULL,
    path       VARCHAR(1024) NOT NULL,
    size_bytes BIGINT        NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ   NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_variants_job  ON variants(job_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_job ON artifacts(job_id);
