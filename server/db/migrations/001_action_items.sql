-- Crux WhatsApp daily plan (separate from OpenClaw action_items in 03-action-tracker.sql)
CREATE TABLE IF NOT EXISTS crux_action_items (
    id          SERIAL PRIMARY KEY,
    plan_date   DATE        NOT NULL,
    number      INTEGER     NOT NULL,
    priority    VARCHAR(10) NOT NULL,
    subject     TEXT        NOT NULL,
    from_email  VARCHAR(255),
    status      VARCHAR(20) NOT NULL DEFAULT 'pending',
    source      VARCHAR(20) NOT NULL DEFAULT 'gmail',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    done_at     TIMESTAMPTZ,
    UNIQUE (plan_date, number)
);

CREATE INDEX IF NOT EXISTS idx_crux_action_items_plan_date ON crux_action_items (plan_date);
CREATE INDEX IF NOT EXISTS idx_crux_action_items_plan_date_status ON crux_action_items (plan_date, status);

CREATE TABLE IF NOT EXISTS crux_daily_runs (
    id              SERIAL PRIMARY KEY,
    plan_date       DATE        NOT NULL,
    run_type        VARCHAR(20) NOT NULL,
    run_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    item_count      INTEGER     NOT NULL DEFAULT 0,
    new_item_count  INTEGER     NOT NULL DEFAULT 0,
    whatsapp_sent   BOOLEAN     NOT NULL DEFAULT FALSE,
    char_count      INTEGER
);

CREATE INDEX IF NOT EXISTS idx_crux_daily_runs_plan_date ON crux_daily_runs (plan_date);
