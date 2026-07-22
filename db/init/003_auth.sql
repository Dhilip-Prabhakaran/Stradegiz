-- Provider access tokens, stored in the DB rather than .env because they
-- change daily. Keeping them here means a new token takes effect on the next
-- poll with no container restart.
--
-- Only ever holds short-lived market-data tokens. Not user credentials.
CREATE TABLE auth_token (
    provider     TEXT PRIMARY KEY,        -- 'upstox'
    access_token TEXT        NOT NULL,
    issued_at    TIMESTAMPTZ NOT NULL,
    expires_at   TIMESTAMPTZ NOT NULL,    -- Upstox: next 03:30 IST after issue
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
