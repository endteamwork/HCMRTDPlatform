# Polarapt HCM Real-Time Data Platform

AWS implementation of the Data Engineering Batch 05 hackathon: three public HR
data feeds ingested on a schedule into S3, routed by source through SNS/SQS
FIFO, and processed into S3, SQL Server, and Snowflake.

Region: `eu-north-1` · Schedule: every **30 minutes** (hackathon spec says
every minute; 30 was chosen to keep API usage and cost down).

## Architecture

```
EventBridge rate(30 min) ─► lambda_jobs_ingest ───────► s3://data-hackathon-smit-ali/raw/jobs/YYYY/MM/DD/HHMM.json
EventBridge rate(30 min) ─► lambda_benchmarks_scraper ► .../raw/benchmarks/YYYY/MM/DD/HHMM.json
EventBridge rate(30 min) ─► lambda_fx_ingest ─────────► .../raw/fx/YYYY/MM/DD/HHMM.json
         (every raw object carries a metadata contract: source, ingested-at,
          record-count, response-status — as S3 object metadata and in-file)

S3 ObjectCreated raw/ ─► lambda_event_router ─► SNS FIFO hcm-routed-events.fifo
                                                 (MessageAttribute: source)
      filter policies ─► jobs-queue.fifo | benchmarks-queue.fifo | fx-queue.fifo

EventBridge rate(30 min) ─► lambda_benchmarks_processor ─► s3 processed/benchmarks/
EventBridge rate(30 min) ─► lambda_fx_processor ─────────► RDS SQL Server dbo.fx_rates
Glue trigger cron(0/30)  ─► glue_jobs_to_snowflake ──────► Snowflake HCM.JOBS.JOB_POSTINGS
```

## Data sources

| Source | Lambda | Target |
|---|---|---|
| [USAJOBS Search API](https://data.usajobs.gov/api/search) (500 postings/call) | `lambda_jobs_ingest` | Snowflake via Glue |
| [BLS highest-paying occupations](https://www.bls.gov/ooh/highest-paying.htm) (top 10 by median pay, scraped with requests + BeautifulSoup) | `lambda_benchmarks_scraper` | S3 `processed/` |
| [Open Exchange Rates](https://openexchangerates.org/) (USD → PKR, SAR, AED, GBP, EUR, INR) | `lambda_fx_ingest` | SQL Server |

Notes:
- All Lambdas run Python **3.11 / x86_64** — the provided `snowflake-connector`
  layer is built for cp311 manylinux x86_64, which is why the earlier
  python3.12 function failed to import it.
- BLS blocks scripted requests pretending to be browsers; the scraper follows
  the BLS policy of identifying itself with contact info in the User-Agent.
- `lambda_fx_processor` runs inside the default VPC (same security group as
  the RDS instance) and reaches AWS APIs through VPC endpoints (S3 gateway,
  SQS + Secrets Manager interface endpoints).
- SQL Server access uses `python-tds` (pure Python), bundled in the zip.
- Credentials live in `.env` (gitignored) and AWS Secrets Manager
  (`hcm/sqlserver`, `hcm/snowflake`).

## Repo layout

- `src/common/contract.py` — contract builder + raw/processed key layout
- `src/lambdas/<name>/handler.py` — one folder per Lambda
- `src/glue/jobs_to_snowflake.py` — Glue python-shell job script
- `scripts/package.ps1` — builds `dist/<name>.zip` with Linux wheels
- `scripts/deploy_messaging.py` — idempotent SNS/SQS/S3-notification setup
- `scripts/sql/`, `scripts/snowflake/` — DDL
- `tests/` — pytest unit tests for the jobs and fx modules; evidence in
  `tests/evidence/`

## Running the tests

```
pip install -r requirements-dev.txt
pytest tests -v
```

## Deploying a code change

```
powershell -File scripts\package.ps1
aws lambda update-function-code --function-name <fn> --zip-file fileb://dist/<name>.zip
```
