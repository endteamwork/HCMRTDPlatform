"""Glue Python-shell job: glue_jobs_to_snowflake.

Drains jobs-queue.fifo, reads each referenced raw USAJOBS file from S3,
parses the postings, and inserts them into Snowflake HCM.JOBS.JOB_POSTINGS.

Job arguments / env:
    --QUEUE_URL          jobs-queue.fifo URL
    --SNOWFLAKE_SECRET   Secrets Manager secret id (username/password/account_name)
    --SNOWFLAKE_DB       database (default HCM)
    --SNOWFLAKE_SCHEMA   schema (default JOBS)
    --SNOWFLAKE_WH       warehouse
    --SNOWFLAKE_ROLE     role
    --REGION             AWS region for boto3 clients
"""

import json
import sys

import boto3
from snowflake import connector


def get_arg(name, default=None):
    flag = f"--{name}"
    if flag in sys.argv:
        return sys.argv[sys.argv.index(flag) + 1]
    if default is None:
        raise KeyError(f"Missing required job argument {flag}")
    return default


def get_snowflake_conn(region, secret_id, database, schema, warehouse, role):
    secrets = boto3.client("secretsmanager", region_name=region)
    creds = json.loads(secrets.get_secret_value(SecretId=secret_id)["SecretString"])
    return connector.connect(
        user=creds["username"],
        password=creds["password"],
        account=creds["account_name"],
        role=role,
        warehouse=warehouse,
        database=database,
        schema=schema,
    )


INSERT_SQL = """
INSERT INTO JOB_POSTINGS (
    POSITION_ID, TITLE, ORGANIZATION, DEPARTMENT, LOCATION,
    SALARY_MIN, SALARY_MAX, SALARY_INTERVAL,
    OPEN_DATE, CLOSE_DATE, URL, SOURCE_FILE, INGESTED_AT
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def rows_from_raw(raw_doc, key):
    contract = raw_doc.get("contract", {})
    ingested_at = contract.get("ingested_at")
    rows = []
    for rec in raw_doc.get("data", []):
        rows.append(
            (
                rec.get("position_id"),
                rec.get("title"),
                rec.get("organization"),
                rec.get("department"),
                rec.get("location"),
                rec.get("salary_min"),
                rec.get("salary_max"),
                rec.get("salary_interval"),
                rec.get("open_date"),
                rec.get("close_date"),
                rec.get("url"),
                key,
                ingested_at,
            )
        )
    return rows


def main():
    region = get_arg("REGION", "eu-north-1")
    queue_url = get_arg("QUEUE_URL")
    secret_id = get_arg("SNOWFLAKE_SECRET", "hcm/snowflake")
    database = get_arg("SNOWFLAKE_DB", "HCM")
    schema = get_arg("SNOWFLAKE_SCHEMA", "JOBS")
    warehouse = get_arg("SNOWFLAKE_WH", "COMPUTE_WH")
    role = get_arg("SNOWFLAKE_ROLE", "ACCOUNTADMIN")

    sqs = boto3.client("sqs", region_name=region)
    s3 = boto3.client("s3", region_name=region)

    conn = get_snowflake_conn(region, secret_id, database, schema, warehouse, role)
    cur = conn.cursor()
    total_rows = 0
    total_files = 0

    try:
        for _ in range(50):  # drain up to 500 messages per run
            resp = sqs.receive_message(
                QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=1
            )
            messages = resp.get("Messages", [])
            if not messages:
                break
            for msg in messages:
                body = json.loads(msg["Body"])
                obj = s3.get_object(Bucket=body["bucket"], Key=body["key"])
                raw_doc = json.loads(obj["Body"].read())
                rows = rows_from_raw(raw_doc, body["key"])
                if rows:
                    cur.executemany(INSERT_SQL, rows)
                sqs.delete_message(
                    QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"]
                )
                total_rows += len(rows)
                total_files += 1
        print(f"Inserted {total_rows} rows from {total_files} files into {database}.{schema}.JOB_POSTINGS")
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
