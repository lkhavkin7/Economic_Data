# Economic Data Pipeline with MCP Integration

Automated ETL pipeline for fetching, validating, and storing economic indicators from the FRED API, with Model Context Protocol (MCP) integration for AI assistant access.

## Overview

This project demonstrates production-grade data engineering practices by building an automated pipeline that:
- Fetches economic data (GDP, Federal Funds Rate, Consumer Sentiment) from FRED API
- Validates data quality with range checks and error handling
- Stores time-series data in PostgreSQL with proper normalization
- Exposes data via MCP server for AI assistant integration
- Automates daily updates with scheduled tasks and logging

## Features

- **Automated Data Fetching**: Daily scheduled updates from FRED API
- **Data Validation**: Range checks, date validation, and error handling
- **PostgreSQL Storage**: Normalized database schema with proper constraints
- **MCP Integration**: AI assistants can query economic data via MCP protocol
- **Comprehensive Logging**: File and console logging for monitoring
- **Error Recovery**: Graceful failure handling with detailed error messages

## Tech Stack

- **Python 3.13**
- **PostgreSQL 18**
- **Libraries**: 
  - `psycopg2` - PostgreSQL adapter
  - `requests` - HTTP client for FRED API
  - `schedule` - Task scheduling
  - `mcp` - Model Context Protocol SDK

## Project Structure
```
economic_data_pipeline/
├── src/
│   ├── db_connection.py       # Database connection handler
│   ├── fetch_data.py           # Main ETL logic
│   ├── validate_data.py        # Data validation rules
│   ├── mcp_server.py           # MCP server implementation
│   └── scheduler.py            # Automated scheduling
├── db/
│   └── schema.sql              # Database schema
├── config/
│   └── .env.example            # Environment variables template
├── mcp_config.json             # MCP server configuration
├── .gitignore
└── README.md
```

## Setup Instructions

### Prerequisites

- Python 3.13+
- PostgreSQL 18+
- FRED API Key ([Get one here](https://fred.stlouisfed.org/docs/api/api_key.html))

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/lkhavkin7/economic_data_pipeline.git
cd economic_data_pipeline
```

2. **Install dependencies**
```bash
pip install psycopg2-binary requests schedule mcp --break-system-packages
```

3. **Set up environment variables**

Set these as system environment variables:
- `FRED_API_KEY`: Your FRED API key
- `POSTGRES_PASSWORD`: Your PostgreSQL password

4. **Create database and schema**
```bash
# In psql:
CREATE DATABASE economic_data;
\c economic_data
\i db/schema.sql
```

### Usage

#### Manual Data Fetch
```bash
python src/fetch_data.py
```

#### Run Scheduled Updates
```bash
python src/scheduler.py
# Runs daily at 9:00 AM, checks every minute
```

#### Start MCP Server
```bash
python src/mcp_server.py
```

## Database Schema

### `indicator_metadata` Table
Stores metadata about each economic indicator.

| Column | Type | Description |
|--------|------|-------------|
| indicator_id | VARCHAR(50) | Primary key (e.g., "GDP") |
| name | VARCHAR(255) | Human-readable name |
| description | TEXT | What the indicator measures |
| frequency | VARCHAR(50) | Update frequency (daily/monthly/quarterly) |
| units | VARCHAR(100) | Measurement units |
| source | VARCHAR(100) | Data source (default: FRED) |

### `economic_indicators` Table
Stores historical time-series data.

| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Auto-increment primary key |
| indicator_id | VARCHAR(50) | Foreign key to metadata |
| date | DATE | Observation date |
| value | DECIMAL(15,4) | Indicator value |
| fetched_at | TIMESTAMP | When data was retrieved |

**Constraint**: `UNIQUE(indicator_id, date)` prevents duplicates.

## MCP Server Tools

The MCP server exposes three tools:

### 1. `get_latest_indicator`
Get the most recent value for an economic indicator.

**Input**: `{"indicator_id": "GDP" | "FEDFUNDS" | "UMCSENT"}`

**Output**:
```json
{
  "indicator": "GDP",
  "date": "2025-07-01",
  "value": 31098.027,
  "fetched_at": "2026-02-15 14:23:55"
}
```

### 2. `get_indicator_history`
Get historical data for an indicator.

**Input**: `{"indicator_id": "GDP", "limit": 10}`

**Output**:
```json
{
  "indicator": "GDP",
  "count": 10,
  "data": [
    {"date": "2025-07-01", "value": 31098.027},
    {"date": "2025-04-01", "value": 30485.729},
    ...
  ]
}
```

### 3. `fetch_fresh_data`
Fetch fresh data from FRED API and update database.

**Input**: `{"indicator_id": "all" | "GDP" | "FEDFUNDS" | "UMCSENT"}`

**Output**:
```json
{
  "GDP": "0 new records",
  "FEDFUNDS": "2 new records",
  "UMCSENT": "0 new records"
}
```

## Data Validation

The pipeline validates:
- **GDP**: $1 trillion - $100 trillion
- **Federal Funds Rate**: 0% - 20%
- **Consumer Sentiment**: 0 - 150
- **Dates**: Between 1950 and 1 year in the future

Invalid data is logged and skipped.

## Logging

Logs are written to:
- `data_pipeline.log` (file)
- Console output (real-time monitoring)

Log format: `YYYY-MM-DD HH:MM:SS - LEVEL - MESSAGE`

## Future Enhancements

- [ ] Add more economic indicators (unemployment, inflation)
- [ ] Implement data visualizations
- [ ] Cloud deployment (AWS/GCP)
- [ ] Add alert system for significant economic changes
- [ ] Historical data backfill for analysis

## Author

**Leo Khavkin**
- GitHub: [@lkhavkin7](https://github.com/lkhavkin7)
- LinkedIn: [Leo Khavkin](https://linkedin.com/in/leo-khavkin-ml-ai)

