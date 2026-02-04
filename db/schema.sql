-- Drop tables if they exist (for clean setup)
DROP TABLE IF EXISTS economic_indicators;
DROP TABLE IF EXISTS indicator_metadata;

-- Metadata about each economic indicator
CREATE TABLE indicator_metadata (
    indicator_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    frequency VARCHAR(50),
    units VARCHAR(100),
    source VARCHAR(100) DEFAULT 'FRED'
);

-- Historical data for all indicators
CREATE TABLE economic_indicators (
    id SERIAL PRIMARY KEY,
    indicator_id VARCHAR(50) REFERENCES indicator_metadata(indicator_id),
    date DATE NOT NULL,
    value DECIMAL(15,4),
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(indicator_id, date)  -- Prevent duplicate data for same indicator/date
);

-- Insert metadata for our 3 indicators
INSERT INTO indicator_metadata (indicator_id, name, description, frequency, units) VALUES
('GDP', 'Gross Domestic Product', 'Total market value of goods and services', 'quarterly', 'billions USD'),
('FEDFUNDS', 'Federal Funds Rate', 'Interest rate banks charge each other for overnight loans', 'daily', 'percent'),
('UMCSENT', 'Consumer Sentiment Index', 'University of Michigan Consumer Sentiment', 'monthly', 'index');