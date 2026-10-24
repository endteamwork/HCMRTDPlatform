"""lambda_fx_processor: triggered by EventBridge every 30 minutes.

Drains fx-queue.fifo, reads each referenced raw FX file, and inserts the
exchange rates into SQL Server (RDS) using python-tds (pure Python driver).

Env vars:
    QUEUE_URL           fx-queue.fifo URL
    SQLSERVER_SECRET_ID Secrets Manager secret with host/port/username/password/database
"""

import json
import os
from datetime import datetime, timezone

import boto3
import pytds

s3 = boto3.client("s3")
sqs = boto3.client("sqs")
secrets = boto3.client("secretsmanager")

INSERT_SQL = (
    "INSERT INTO dbo.fx_rates "
    "(base_currency, currency, rate, rate_timestamp, ingested_at, source_file) "
    "VALUES (%s, %s, %s, %s, %s, %s)"
)


def get_sqlserver_creds(secret_id):
    value = secrets.get_secret_value(SecretId=secret_id)
    return json.loads(value["SecretString"])


def drain_queue(queue_url, max_batches=20):
    for _ in range(max_batches):
        resp = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=1
        )
        messages = resp.get("Messages", [])
        if not messages:
            return
        for msg in messages:
            yield msg, json.loads(msg["Body"])


def rows_from_raw(raw_doc, key):
    contract = raw_doc.get("contract", {})
    ingested_at = contract.get("ingested_at")
    return [
        (
            rec["base_currency"],
            rec["currency"],
            float(rec["rate"]),
            rec["rate_timestamp"],
            ingested_at,
            key,
        )
        for rec in raw_doc.get("data", [])
    ]


def lambda_handler(event, context):
    queue_url = os.environ["QUEUE_URL"]
    creds = get_sqlserver_creds(os.environ["SQLSERVER_SECRET_ID"])
    inserted = []

    with pytds.connect(
        server=creds["host"],
        port=int(creds.get("port", 1433)),
        user=creds["username"],
        password=creds["password"],
        database=creds.get("database", "hcm"),
        login_timeout=30,
        autocommit=True,
    ) as conn:
        cur = conn.cursor()
        for msg, body in drain_queue(queue_url):
            obj = s3.get_object(Bucket=body["bucket"], Key=body["key"])
            raw_doc = json.loads(obj["Body"].read())
            rows = rows_from_raw(raw_doc, body["key"])
            if rows:
                cur.executemany(INSERT_SQL, rows)
            sqs.delete_message(
                QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"]
            )
            inserted.append({"key": body["key"], "rows": len(rows)})

    return {"statusCode": 200, "inserted": inserted}
