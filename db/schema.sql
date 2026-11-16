-- Safe to run repeatedly: every statement uses IF NOT EXISTS and none removes data.
-- This file only creates tables; the rows of indicator_metadata are written
-- by the pipeline from config.

-- Definition of each indicator.
CREATE TABLE IF NOT EXISTS indicator_metadata (
    indicator_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    frequency VARCHAR(50),
    units VARCHAR(100),
    source VARCHAR(100) DEFAULT 'FRED'
);

-- Stored observations: one row per indicator per date.
CREATE TABLE IF NOT EXISTS economic_indicators (
    id SERIAL PRIMARY KEY,
    indicator_id VARCHAR(50) REFERENCES indicator_metadata(indicator_id),
    date DATE NOT NULL,
    value DECIMAL(15,4),
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(indicator_id, date)  -- the pipeline's upsert relies on this
);