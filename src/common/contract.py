"""Shared helpers for the metadata contract and raw S3 layout.

Every raw file is stored as:
    raw/{source}/YYYY/MM/DD/{HHMM}.json
with a contract describing the ingestion, set both as S3 object metadata
and embedded in the file body:
    {"contract": {...}, "data": [...]}
"""

import json
from datetime import datetime, timezone

import boto3

CONTRACT_KEYS = ("source", "ingested_at", "record_count", "response_status")


def utc_now():
    return datetime.now(timezone.utc)


def build_contract(source, record_count, response_status, ingested_at=None):
    """Build the metadata contract for one ingested file."""
    ingested_at = ingested_at or utc_now()
    return {
        "source": source,
        "ingested_at": ingested_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "record_count": int(record_count),
        "response_status": int(response_status),
    }


def raw_key(source, dt=None):
    """Raw S3 key: raw/{source}/YYYY/MM/DD/{HHMM}.json"""
    dt = dt or utc_now()
    return f"raw/{source}/{dt:%Y}/{dt:%m}/{dt:%d}/{dt:%H%M}.json"


def processed_key(source, dt=None):
    """Processed S3 key: processed/{source}/YYYY/MM/DD/{HHMM}.json"""
    dt = dt or utc_now()
    return f"processed/{source}/{dt:%Y}/{dt:%m}/{dt:%d}/{dt:%H%M}.json"


def put_raw(bucket, source, records, response_status, dt=None, s3=None):
    """Write records + contract to the raw area.

    The contract is stored as S3 object metadata (string values) and
    embedded in the file under "contract".
    Returns (key, contract).
    """
    s3 = s3 or boto3.client("s3")
    dt = dt or utc_now()
    contract = build_contract(source, len(records), response_status, ingested_at=dt)
    key = raw_key(source, dt)
    body = json.dumps({"contract": contract, "data": records}, default=str)
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode("utf-8"),
        ContentType="application/json",
        # HTTP header names normalize underscores to hyphens, so metadata
        # keys use hyphens: source, ingested-at, record-count, response-status
        Metadata={k.replace("_", "-"): str(v) for k, v in contract.items()},
    )
    return key, contract
