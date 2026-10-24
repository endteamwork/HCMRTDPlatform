"""lambda_benchmarks_processor: triggered by EventBridge every 30 minutes.

Drains benchmarks-queue.fifo, reads each referenced raw benchmarks file,
transforms it, and writes the result to the processed S3 area.

Env vars:
    QUEUE_URL   benchmarks-queue.fifo URL
    S3_BUCKET   target bucket for processed output
"""

import json
import os
from datetime import datetime, timezone

import boto3

from common.contract import processed_key

s3 = boto3.client("s3")
sqs = boto3.client("sqs")


def transform(raw_doc, key):
    """Clean the scraped benchmark rows into the processed shape."""
    contract = raw_doc.get("contract", {})
    rows = []
    for rec in raw_doc.get("data", []):
        rows.append(
            {
                "rank": rec.get("rank"),
                "occupation": rec.get("occupation"),
                "median_annual_pay_usd": rec.get("median_annual_pay"),
                "source_file": key,
                "ingested_at": contract.get("ingested_at"),
                "processed_at": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
            }
        )
    return rows


def drain_queue(queue_url, max_batches=20):
    """Yield (message, body) for everything currently in the queue."""
    for _ in range(max_batches):
        resp = sqs.receive_message(
            QueueUrl=queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=1
        )
        messages = resp.get("Messages", [])
        if not messages:
            return
        for msg in messages:
            yield msg, json.loads(msg["Body"])


def lambda_handler(event, context):
    queue_url = os.environ["QUEUE_URL"]
    bucket = os.environ["S3_BUCKET"]
    processed = []

    for msg, body in drain_queue(queue_url):
        obj = s3.get_object(Bucket=body["bucket"], Key=body["key"])
        raw_doc = json.loads(obj["Body"].read())
        rows = transform(raw_doc, body["key"])

        out_key = processed_key("benchmarks")
        s3.put_object(
            Bucket=bucket,
            Key=out_key,
            Body=json.dumps({"records": rows}, default=str).encode("utf-8"),
            ContentType="application/json",
            Metadata={
                "source": "benchmarks",
                "record_count": str(len(rows)),
                "source_file": body["key"],
            },
        )
        sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=msg["ReceiptHandle"])
        processed.append({"in": body["key"], "out": out_key, "rows": len(rows)})

    return {"statusCode": 200, "processed": processed}
