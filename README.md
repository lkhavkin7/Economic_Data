# Economic Data Pipeline

Loads US economic and market indicators from the [FRED API](https://fred.stlouisfed.org/docs/api/fred/) into PostgreSQL, and serves them to AI assistants through an [MCP](https://modelcontextprotocol.io) server.

It tracks six series: three federal funds rates, the monthly average of the funds rate, the S&P 500 and the VIX. Each run fetches the latest observations (or the full history), checks them against valid ranges, and upserts them in one database transaction, so a rerun changes nothing and a value FRED later revises is overwritten.

## Status

| | |
|---|---|
| Runs locally | Yes. Docker Compose starts PostgreSQL; the pipeline loads real FRED data. A full backfill has been run against it. |
| Tests | Unit tests, plus integration tests that run against a real PostgreSQL server. See [Tests](#tests). |
| MCP server | Works over stdio. A Streamable HTTP mode exists but is bound to localhost and has no authentication. |
| AWS | Built with Terraform and tested: a VPC, a private RDS database and a Lambda, with the `setup`, `fetch` and `verify` modes run by hand against real FRED data. The stack is destroyed when it is not in use, because it costs about $1.65 a day while running, so it is usually **not running**. See [Deploying to AWS](#deploying-to-aws). |
| Scheduling | A daily EventBridge rule is defined in Terraform. A scheduled run has not been observed yet. |
| CI, monitoring | Not built yet. See [Roadmap](#roadmap). |

## Architecture

```mermaid
flowchart LR
    FRED["FRED API"] --> client["fred_client<br/>timeout, retries"]
    client --> pipeline["pipeline<br/>validate, then upsert<br/>one transaction per run"]
    pipeline --> db[("PostgreSQL")]

    cli["cli<br/>python -m src.econ_data"] --> pipeline
    lambda["lambda_handler<br/>fetch / verify / setup"] --> pipeline
    fetchtool["mcp_server<br/>fetch_fresh_data tool"] --> pipeline

    db --> reads["mcp_server<br/>read tools and resources"]
    reads --> host["MCP host<br/>for example Claude"]
```

Three entry points (the command line, the Lambda handler and the MCP `fetch_fresh_data` tool) call the same pipeline. The MCP read tools and resources query the database directly and never write to it.

| Module | Job |
|---|---|
| `config` | The six indicators (id, name, units, frequency, valid range, lookback) and the settings read from environment variables and `.env`. Every other module reads from here. |
| `db` | Opens connections. Credentials come from `DB_PASSWORD`, or from AWS Secrets Manager when `DB_SECRET_ARN` is set. |
| `fred_client` | Requests observations from FRED with a timeout and retries. Fails with an error that starts with the series id and never contains the API key. |
| `validate` | Checks each date and value. |
| `pipeline` | Fetch, validate, upsert. Returns one summary per indicator. |
| `cli` | The command line, with a per-indicator table and exit codes. |
| `lambda_handler` | AWS Lambda entry point with `fetch`, `verify` and `setup` modes. |
| `mcp_server` | The MCP server. |

### On AWS

```mermaid
flowchart TB
    internet(["Internet<br/>FRED API"])

    subgraph region["AWS region us-east-1"]
        eb["EventBridge rule<br/>daily at 13:00 UTC"]
        secret["Secrets Manager<br/>RDS-managed password"]

        subgraph vpc["VPC 10.20.0.0/16"]
            igw["Internet gateway"]

            subgraph public["Public subnet 10.20.0.0/24"]
                nat["NAT gateway<br/>fixed public IP"]
            end

            subgraph privA["Private subnet 10.20.10.0/24, us-east-1a"]
                rds[("RDS PostgreSQL<br/>accepts only the Lambda")]
            end

            subgraph privB["Private subnet 10.20.11.0/24, us-east-1b"]
                fn["Lambda<br/>no inbound rules"]
            end
        end
    end

    eb -->|"invokes"| fn
    fn -->|"port 5432"| rds
    fn -->|"outbound"| nat
    nat --> igw
    igw --> internet
    fn -.->|"password, via the NAT"| secret
```

The database and the Lambda sit in private subnets with no route in from the internet. The database's security group accepts port 5432 from the Lambda's security group and from nothing else. The Lambda reaches FRED and Secrets Manager through the NAT gateway. It is attached to both private subnets and is drawn in one of them. EventBridge and Secrets Manager are regional services outside the VPC, and EventBridge calls the Lambda through the Lambda service, not through the network.

## Quick start

You need Python 3.11 or newer, Docker, and a free [FRED API key](https://fred.stlouisfed.org/docs/api/api_key.html).

```
git clone https://github.com/lkhavkin7/Economic_Data.git
cd Economic_Data
python -m venv .venv
```

Activate the virtual environment: `.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on macOS and Linux. Then:

```
pip install -r requirements-dev.txt
```

Create your settings file from the template (`copy .env.example .env` on Windows, `cp .env.example .env` elsewhere). Open `.env` and fill in `DB_PASSWORD` (choose any password) and `FRED_API_KEY`. `.env` is ignored by git; never commit it.

Start the database and load the data:

```
docker compose up -d --wait
python -m src.econ_data --backfill
```

Check what was stored:

```
docker compose exec db psql -U econ -d econ_data -c "SELECT indicator_id, COUNT(*), MAX(date) FROM economic_indicators GROUP BY 1 ORDER BY 1"
```

From then on, `python -m src.econ_data` fetches only the latest observations.

The database schema (`db/schema.sql`) is applied only the first time the container starts with an empty data volume. `docker compose down` stops the database and keeps the data. `docker compose down -v` also deletes the data, so the next start begins from scratch.

## Configuration

Settings come from environment variables or from `.env` in the folder you run from. If both set the same value, the environment variable wins.

| Variable | Default | Meaning |
|---|---|---|
| `DB_PASSWORD` | none | Database password. Required unless `DB_SECRET_ARN` is set. |
| `DB_SECRET_ARN` | none | ARN of an AWS Secrets Manager secret holding `{"username": ..., "password": ...}`. Used only when `DB_PASSWORD` is empty. |
| `FRED_API_KEY` | none | Your FRED API key. |
| `DB_HOST` | `localhost` | Use `127.0.0.1` on Windows: `localhost` tries IPv6 first and every connection stalls. |
| `DB_PORT` | `5432` | Also the host port Docker Compose publishes the database on. |
| `DB_NAME` | `econ_data` | |
| `DB_USER` | `econ` | |

## Running the pipeline

```
python -m src.econ_data                          latest observations of every indicator
python -m src.econ_data --backfill               full history of every indicator
python -m src.econ_data --indicator DFF SP500    only the named indicators
```

Each run prints one line per indicator (example output):

```
indicator    fetched   inserted    updated  unchanged    missing   rejected  status
DFF               10          1          0          9          0          0  ok
DFEDTARU          10          0          0         10          0          0  ok
DFEDTARL          10          0          0         10          0          0  ok
FEDFUNDS           3          0          1          2          0          0  ok
SP500             10          1          0          8          1          0  ok
VIXCLS            10          1          0          9          0          0  ok

6 indicators: 6 ok, 0 failed
```

The columns of a successful run add up: `fetched = missing + rejected + inserted + updated + unchanged`.

| Exit code | Meaning |
|---|---|
| 0 | Every indicator succeeded. |
| 1 | At least one indicator failed, for example FRED returned an error. The indicators that succeeded were still saved. |
| 2 | The run could not complete: bad arguments, bad settings or a database error. Nothing from that run was saved. |

## MCP server

Tools (actions a model can call):

| Tool | Returns |
|---|---|
| `get_latest_indicator` | The newest stored observation of one indicator. |
| `get_indicator_history` | The newest stored observations of one indicator, newest first. `limit` is 1 to 1000, default 10. |
| `fetch_fresh_data` | Runs the pipeline for one indicator or `all`, and returns a summary per indicator. This is the only tool that writes. |

Resources (read-only context, addressed by URI):

| URI | Content |
|---|---|
| `fred://catalog` | Every indicator in the database, with its row count and latest date. |
| `fred://series/{indicator_id}` | The newest 100 stored observations of one indicator. |

Start it:

```
python -m src.econ_data.mcp_server          stdio, launched by an MCP host
python -m src.econ_data.mcp_server http     Streamable HTTP at http://127.0.0.1:8765/mcp
```

`mcp_config.json` is a template for an MCP host's configuration. The server reads its settings the same way the pipeline does, so either start it from the repository folder (where `.env` is) or put the real values in the `env` block of the host's configuration. Not every host expands `${...}` placeholders.

The HTTP mode has no authentication. Keep it on localhost.

## AWS Lambda entry point

`lambda_handler` in `src/econ_data/lambda_handler.py` runs the mode named by the event's `mode` key:

| Mode | Does |
|---|---|
| `fetch` (default) | Runs the pipeline for every indicator. If any indicator failed, raises an error after all have been processed, so Lambda records the invocation as failed. |
| `verify` | Returns the row count and latest date stored for each indicator. |
| `setup` | Creates the database if it is missing, then applies `db/schema.sql`. Safe to repeat. |

## Deploying to AWS

The `infra/` folder is Terraform for everything in the [AWS diagram](#on-aws). You need an AWS account, [Terraform](https://developer.hashicorp.com/terraform/install) 1.6 or newer, the AWS CLI v2 signed in to that account, and the FRED API key.

| File in `infra/` | Creates |
|---|---|
| `network.tf` | The VPC, one public and two private subnets, the internet gateway and the route tables. |
| `security.tf` | The security groups and their rules, and locks down the VPC's default security group. |
| `nat.tf` | The NAT gateway, its fixed public IP and the private subnets' route to it. |
| `database.tf` | The RDS PostgreSQL 16 server. RDS creates the master password and keeps it in Secrets Manager. |
| `iam.tf` | The Lambda's role: VPC and logging access, plus permission to read that one secret. |
| `lambda.tf` | The Lambda function and its log group. |
| `schedule.tf` | The daily EventBridge rule and the permission that lets it call the Lambda. |

Build the package, then create the stack (Windows `cmd` syntax; on macOS and Linux use `export TF_VAR_fred_api_key=...`):

```
python scripts/build_lambda.py
cd infra
terraform init
set TF_VAR_fred_api_key=your-fred-key
terraform apply
```

`scripts/build_lambda.py` writes `build/lambda.zip`. It downloads the dependencies as Linux builds, so it works from Windows, and it produces the same bytes when nothing changed.

Run each mode of the Lambda by hand (on macOS and Linux, write the payload as `'{"mode":"setup"}'`):

```
aws lambda invoke --function-name econ-data --cli-binary-format raw-in-base64-out --payload "{\"mode\":\"setup\"}" out.json
aws lambda invoke --function-name econ-data --cli-binary-format raw-in-base64-out --payload "{\"mode\":\"fetch\"}" out.json
aws lambda invoke --function-name econ-data --cli-binary-format raw-in-base64-out --payload "{\"mode\":\"verify\"}" out.json
aws logs tail /aws/lambda/econ-data --since 15m
```

Remove everything with `terraform destroy`. The Lambda's network interfaces can take 10 to 20 minutes to be released, so the subnets and the Lambda's security group are the slowest part of a destroy. If it times out, run it again.

**Cost.** While it runs, the NAT gateway costs about $0.045 an hour plus $0.045 per GB, its public IP about $0.005 an hour, and the `db.t4g.micro` database about $0.016 an hour plus storage: roughly $0.07 an hour, or $1.65 a day. Destroy the stack when you are not using it, and set an AWS budget alert.

**Secrets.**
- The database password is created by RDS and never appears in these files or in the Terraform state.
- The FRED API key is passed as a sensitive variable. It ends up in the Lambda's environment settings and in the local `terraform.tfstate`.
- Never commit `terraform.tfstate`, `.terraform/` or `*.tfvars`. They are in `.gitignore`.

Terraform state is kept locally. Use a remote backend before sharing this with anyone else.

## Data notes

| Indicator | Series | Frequency | Valid range |
|---|---|---|---|
| `DFF` | Effective federal funds rate | daily | 0 to 25 |
| `DFEDTARU` | Federal funds target, upper limit | daily | 0 to 20 |
| `DFEDTARL` | Federal funds target, lower limit | daily | 0 to 20 |
| `FEDFUNDS` | Federal funds rate, monthly average | monthly | 0 to 25 |
| `SP500` | S&P 500 closing level | daily | 100 to 50,000 |
| `VIXCLS` | VIX closing level | daily | 5 to 100 |

The ranges live in `config`. They were checked against the full history of each series; the effective funds rate reached 22.36% in 1981, which is why its maximum is 25.

- **Revisions.** An existing row is overwritten, and its `fetched_at` renewed, only when FRED returns a different value. A row with the same value is left untouched.
- **Missing and rejected.** An observation FRED has no value for is counted as *missing* and not stored. One that fails validation is counted as *rejected*, not stored, and the first few reasons are logged. Neither is an error.
- **Daily series have no rows for market holidays.** FRED reports those days with no value.
- **S&P 500 history is short.** FRED serves only about the latest year of S&P 500 values for licensing reasons, so older observations come back as missing, even in a backfill.
- **A FRED failure for one indicator** (timeout, HTTP error, empty answer) is recorded in its summary and the other indicators still run. **A database error** stops the run and rolls back everything it wrote.

## Database schema

| Table | Holds |
|---|---|
| `indicator_metadata` | One row per indicator: id, name, description, frequency, units, source. Written by the pipeline from `config` on every run. |
| `economic_indicators` | One row per indicator per date: `value DECIMAL(15,4)` and `fetched_at`. `UNIQUE(indicator_id, date)` is what the upsert relies on. |

`db/schema.sql` only creates tables that do not exist and never deletes anything, so it is safe to apply again.

## Tests

```
python -m pytest tests                       everything
python -m pytest tests -m "not integration"  fast tests only, no database needed
python -m pytest tests -m integration        only the tests that use a real database
```

The integration tests need the Docker database running (`docker compose up -d --wait`) and the same `.env` or environment variables as the pipeline. They create and use their own database, `econ_data_test`, on the same server, and never touch `econ_data`. If the server cannot be reached they are skipped, unless the `CI` environment variable is set, in which case they fail. FRED and AWS Secrets Manager are the only things replaced by fakes.

## Troubleshooting

- **`docker compose up` fails with "forbidden by access permissions" on a port (Windows).** Another program, often a second local PostgreSQL, is using that port. Set `DB_PORT` in `.env` to a free port, for example `15432`, and start again.
- **The tests or the pipeline are very slow on Windows.** Set `DB_HOST=127.0.0.1` in `.env`.
- **FRED says the API key "is not registered" although `.env` is right.** A variable named `FRED_API_KEY` in your environment overrides `.env`. Check with `echo %FRED_API_KEY%` (cmd) or `echo $FRED_API_KEY` (macOS and Linux), remove it, and open a new terminal.
- **The database container does not turn healthy.** Run `docker compose logs db`. A common cause is a missing `DB_PASSWORD` in `.env`.

## Project layout

```
.env.example            template for .env
docker-compose.yml      local PostgreSQL
mcp_config.json         template for an MCP host's configuration
pytest.ini              test settings
requirements.txt        runtime dependencies
requirements-dev.txt    runtime plus test dependencies
requirements-lambda.txt dependencies packaged into the Lambda zip
db/
  schema.sql            tables
infra/                  Terraform for the AWS deployment
scripts/
  build_lambda.py       builds build/lambda.zip (generated, ignored by git)
src/econ_data/          the package (see Architecture)
tests/                  unit tests
tests/integration/      tests that use a real PostgreSQL server
```

## Roadmap

- Watch the daily schedule fire, and verify a scheduled run end to end on a stack built from nothing.
- A backfill mode for the Lambda. It currently loads only each indicator's recent observations.
- CI: lint and tests on every push, deploy from `main`.
- Monitoring: structured logs and an alarm when the daily run fails or stores nothing.
- Authentication (OAuth 2.1) in front of the HTTP MCP server.
- Stricter validation: ranges catch impossible values but not a plausible-looking jump from one day to the next.

## Author

Leo Khavkin, [@lkhavkin7](https://github.com/lkhavkin7)