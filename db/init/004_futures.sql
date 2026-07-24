-- Futures candles reuse the ohlcv table, which was built for price bars, but
-- a futures bar also carries open interest — a core signal for F&O work.
ALTER TABLE ohlcv ADD COLUMN IF NOT EXISTS oi BIGINT;

-- Front-month continuous futures series, the convention traders chart against.
-- Symbols are suffixed so they cannot collide with the cash/equity series.
INSERT INTO symbols (symbol, name, exchange, sector) VALUES
    ('NIFTY-FUT',     'NIFTY 50 Futures (front month)',   'NSE', 'Index'),
    ('BANKNIFTY-FUT', 'Nifty Bank Futures (front month)', 'NSE', 'Index'),
    ('SENSEX-FUT',    'SENSEX Futures (front month)',     'BSE', 'Index'),
    ('BANKEX-FUT',    'BANKEX Futures (front month)',     'BSE', 'Index')
ON CONFLICT (symbol) DO NOTHING;
