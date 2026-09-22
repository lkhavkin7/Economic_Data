# Economic Data Pipeline with MCP Integration

Automated ETL pipeline for fetching, validating, and storing economic indicators from the FRED API, with Model Context Protocol (MCP) integration for AI assistant access. Deployed and verified end-to-end on AWS (Lambda, RDS, VPC); the paid infrastructure has since been torn down, but the deployment tooling to stand it back up remains in the repo.

## Overview

This project demonstrates production-grade data engineering practices by building a pipeline that:
- Fetches economic data (GDP, Federal Funds Rate, Consumer Sentiment) from FRED API
- Validates data quality with range checks and error handling
- Stores time-series data in PostgreSQL with proper normalization
- Exposes data via MCP server for AI assistant integration
- Runs as an AWS Lambda function inside a custom VPC, reaching the FRED API through a NAT Gateway and RDS PostgreSQL through a security group scoped specifically to that Lambda function

**Current status**: the AWS deployment was built and proven working (see [Deployment](#deployment)), then deliberately torn down — the NAT Gateway and RDS instance were deleted to stop ongoing cost, since this is a portfolio/learning project rather than a running service. The VPC, subnets, security groups, IAM role, and the Lambda function itself remain in place (none of those cost anything idle), and the `deploy/` tooling can redeploy a fresh RDS instance and re-point the Lambda at it. As of now, invoking the Lambda will fail because it has no database to reach.

## Features

- **FRED Data Fetching**: Pulls GDP, Federal Funds Rate, and Consumer Sentiment from the FRED API
- **Data Validation**: Range checks, date validation, and error handling
- **PostgreSQL Storage**: Normalized database schema with proper constraints
- **MCP Integration**: AI assistants can query economic data via MCP protocol
- **AWS Lambda Deployment**: Runs the same fetch logic serverlessly, with `setup`/`fetch`/`verify` invocation modes
- **Secrets Manager Credentials**: Database credentials are resolved at runtime from AWS Secrets Manager, not stored in the codebase
- **Error Recovery**: Graceful failure handling with detailed error messages

## Tech Stack

- **Python 3.13**
- **PostgreSQL 18**
- **AWS**: Lambda, RDS, VPC (NAT Gateway, security groups, IAM), Secrets Manager
- **Libraries**:
  - `psycopg2` - PostgreSQL adapter
  - `requests` - HTTP client for FRED API
  - `mcp` - Model Context Protocol SDK
  - `boto3` - AWS SDK (Secrets Manager integration)

## Project Structure
```
Economic_Data/
├── src/
│   ├── db_connection.py        # DB connection handler; resolves credentials via AWS Secrets Manager
│   ├── fetch_data.py           # Main ETL logic
│   ├── validate_data.py        # Data validation rules
│   └── mcp_server.py           # MCP server implementation
├── db/
│   └── schema.sql              # Database schema
├── deploy/
│   ├── iam/
│   │   ├── trust-policy.json   # Lambda execution role trust policy
│   │   └── lambda-policy.json  # Lambda execution role permissions
│   └── scripts/
│       ├── rezip.py            # Rebuilds the Lambda layer/function zip archives
│       └── verify_zips.py      # Validates zip contents (no backslashes, no .pyd files)
├── tests/
│   ├── test_economic_lambda.py
│   ├── test_fetch_data.py
│   ├── test_mcp_server.py
│   └── test_validate_data.py
├── config/
│   └── .env.example            # Local environment variable template
├── lambda_function.py          # AWS Lambda entry point (setup / fetch / verify modes)
├── mcp_config.json             # MCP client configuration
├── pytest.ini                  # pytest configuration
├── requirements.txt            # Python dependencies
├── .gitignore
└── README.md
```

## Setup Instructions

### Prerequisites

- Python 3.13+
- FRED API Key ([Get one here](https://fred.stlouisfed.org/docs/api/api_key.html))
- AWS credentials configured (`aws configure` or environment variables) — **required for local development too**, see below

### Important: there is no local-only credential path anymore

`src/db_connection.py` resolves database credentials exclusively through AWS Secrets Manager (`boto3`, `DB_SECRET_ARN`). There is no fallback to a plain `POSTGRES_PASSWORD` environment variable. This means even running `fetch_data.py` against a local Postgres instance requires working AWS credentials and a real Secrets Manager secret containing `{"username": ..., "password": ...}` — not just a local `.env` file. `config/.env.example`'s `POSTGRES_PASSWORD` entry is legacy from before this change and is no longer read by the code.

### Installation

1. **Clone the repository**
```bash
git clone https://github.com/lkhavkin7/Economic_Data.git
cd Economic_Data
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Set up environment variables**

- `FRED_API_KEY`: Your FRED API key
- `DB_HOST`: Postgres host (e.g. `localhost` for local Postgres, or an RDS endpoint)
- `DB_NAME`: Database name (defaults to `econ_mcp` if unset)
- `DB_SECRET_ARN`: ARN of an AWS Secrets Manager secret holding `{"username": "...", "password": "..."}` for that Postgres instance

4. **Create database and schema**

There are two ways to run this project, depending on where Postgres lives:

**Path 1 — Local Postgres, AWS-managed credentials**: run Postgres locally, create a Secrets Manager secret matching your local user/password, and set `DB_HOST=localhost` with `DB_SECRET_ARN` pointing at that secret. Then apply the schema:
```bash
# In psql:
CREATE DATABASE econ_mcp;
\c econ_mcp
\i db/schema.sql
```

**Path 2 — Full AWS deployment**: deploy Lambda + RDS using the tooling in `deploy/` (see [Deployment](#deployment)) and invoke the Lambda in `setup` mode to create the database and apply the schema remotely — no local Postgres needed.

### Usage

#### Local: Manual Data Fetch
```bash
python -m src.fetch_data
```

#### Local: Start MCP Server
```bash
python -m src.mcp_server
```

#### AWS Lambda

The Lambda function (`econ-mcp-fetch`) supports three invocation modes via the event payload's `mode` field:

| Mode | Purpose |
|------|---------|
| `setup` | Creates the database (if missing) and applies `db/schema.sql` |
| `fetch` | Fetches fresh FRED data and inserts new rows (default mode) |
| `verify` | Returns row counts and latest date per indicator |

```bash
aws lambda invoke --function-name econ-mcp-fetch --payload "{\"mode\":\"fetch\"}" response.json
```

**Currently, invoking this Lambda will fail** — RDS was torn down after the deployment was verified (see [Deployment](#deployment)), so there's no database for it to reach. Redeploy RDS with the `deploy/` tooling to bring it back before invoking.

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

**Constraint**: `UNIQUE(indicator_id, date)` prevents duplicates. Table creation uses `CREATE TABLE IF NOT EXISTS` and metadata inserts use `ON CONFLICT DO NOTHING`, so the schema can be safely re-applied against an existing database without dropping data.

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

## Testing

```bash
pip install -r requirements.txt
pytest -v
```

33 tests currently pass across all four modules (`fetch_data`, `validate_data`, `mcp_server`, and the Lambda handler), covering data validation boundaries, insert/skip logic, MCP tool responses, and the Lambda's `setup`/`fetch`/`verify` modes.

## Architecture

### Code / data flow
```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌────────────┐
│   FRED API  │────▶│ fetch_data.py│────▶│ validate_data.py│────▶│ PostgreSQL │
└─────────────┘     └──────────────┘     └─────────────────┘     └────────────┘
                                                                        │
                                                                        ▼
                                                               ┌─────────────────┐
                                                               │  mcp_server.py  │
                                                               └─────────────────┘
                                                                        │
                                                                        ▼
                                                               ┌─────────────────┐
                                                               │  AI Assistants  │
                                                               │    (Claude)     │
                                                               └─────────────────┘
```

### Deployed AWS infrastructure

Egress path — Lambda reaching the FRED API:
```
┌──────────┐   ┌────────────┐   ┌──────────────┐   ┌──────────┐
│  Lambda  │──▶│    NAT     │──▶│   Internet   │──▶│ FRED API │
│ (private │   │  Gateway   │   │   Gateway    │   │          │
│  subnet) │   │ (public    │   │              │   │          │
│          │   │  subnet)   │   │              │   │          │
└──────────┘   └────────────┘   └──────────────┘   └──────────┘
```

Internal path — Lambda reaching the database:
```
┌────────────────────┐   security group rule    ┌────────────────────┐
│      Lambda         │─────────────────────────▶│   RDS PostgreSQL    │
│  (private subnet)   │   (port 5432, SG-scoped) │   (private subnet)  │
└────────────────────┘                           └────────────────────┘
```

Both the NAT Gateway and RDS instance shown above have since been torn down — see [Deployment](#deployment).

## Deployment

The `deploy/` directory holds the tooling used to build and deploy the Lambda function, kept in the repo so the deployment can be reproduced:

- `deploy/iam/trust-policy.json` — trust policy allowing `lambda.amazonaws.com` to assume the Lambda's execution role
- `deploy/iam/lambda-policy.json` — the role's permissions (CloudWatch Logs, `secretsmanager:GetSecretValue` on the RDS-managed secret, and the ENI permissions Lambda needs to run inside a VPC)
- `deploy/scripts/rezip.py` — rebuilds `layer.zip` (the `psycopg2`/`boto3` dependency layer) and `function.zip` from the `layer/` and `package/` directories
- `deploy/scripts/verify_zips.py` — sanity-checks those zips before upload (no Windows-style backslash paths, no compiled `.pyd` files, which Lambda's Linux runtime can't use)

This tooling was used to deploy `lambda_function.py` into a Lambda function (`econ-mcp-fetch`) running inside a private VPC subnet, reaching the FRED API through a NAT Gateway and an RDS PostgreSQL instance through a security-group rule scoped to the Lambda. That deployment was verified working end-to-end (`setup`, `fetch`, and `verify` modes all invoked successfully), then the NAT Gateway and RDS instance were deleted to stop their ongoing cost. The VPC, subnets, security groups, IAM role, and Lambda function itself were left in place, since none of those incur cost while idle. To bring the database back: recreate an RDS instance in the existing DB subnet group, update the Lambda's `DB_HOST` and `DB_SECRET_ARN` environment variables to point at it, and invoke with `{"mode": "setup"}`.

## Logging

The pipeline prints progress and validation failures to stdout/CloudWatch (for the Lambda) as it runs; there is no separate log file.

## Future Enhancements

- [ ] Add more economic indicators (unemployment, inflation)
- [ ] Implement data visualizations
- [ ] EventBridge-based scheduled Lambda invocation (replacing the manual/on-demand invoke with a daily schedule)
- [ ] Restore a local-only credential fallback in `db_connection.py` so local development doesn't require AWS credentials
- [ ] Add alert system for significant economic changes
- [ ] Historical data backfill for analysis

## Author

**Leo Khavkin**
- GitHub: [@lkhavkin7](https://github.com/lkhavkin7)
- LinkedIn: [Leo Khavkin](https://linkedin.com/in/leo-khavkin-ml-ai)
