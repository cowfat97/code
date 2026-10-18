CREATE SCHEMA IF NOT EXISTS qwen;

CREATE TABLE IF NOT EXISTS qwen.memory (
    id SMALLINT PRIMARY KEY CHECK (id = 1),
    revision BIGINT NOT NULL CHECK (revision > 0),
    messages JSONB NOT NULL CHECK (jsonb_typeof(messages) = 'array'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
