"""lambda_fx_ingest: fetch live USD exchange rates from Open Exchange Rates
and store them in the raw S3 area with a metadata contract.

Env vars:
    S3_BUCKET          target bucket
    OER_APP_ID         Open Exchange Rates App ID
    OER_BASE_URL       optional, defaults to the public latest.json endpoint
    OER_BASE_CURRENCY  optional, defaults to USD
    OER_SYMBOLS        optional comma list, defaults to PKR,SAR,AED,GBP,EUR,INR
"""

import os
from datetime import datetime, timezone

import requests

from common.contract import put_raw

SOURCE = "fx"
DEFAULT_BASE_URL = "https://openexchangerates.org/api/latest.json"
DEFAULT_SYMBOLS = "PKR,SAR,AED,GBP,EUR,INR"


def fetch_fx_rates(base_url, app_id, base_currency="USD", symbols=DEFAULT_SYMBOLS):
    """Call Open Exchange Rates and return one record per requested currency.

    Returns (records, status_code). Raises on non-200 responses.
    """
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    resp = requests.get(
        base_url,
        params={"app_id": app_id, "base": base_currency},
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Open Exchange Rates request failed with status {resp.status_code}: {resp.text[:500]}"
        )

    data = resp.json()
    rate_ts = datetime.fromtimestamp(data["timestamp"], tz=timezone.utc)
    rates = data.get("rates", {})
    records = [
        {
            "base_currency": data.get("base", base_currency),
            "currency": code,
            "rate": rates[code],
            "rate_timestamp": rate_ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        for code in wanted
        if code in rates
    ]
    return records, resp.status_code


def lambda_handler(event, context):
    bucket = os.environ["S3_BUCKET"]
    base_url = os.environ.get("OER_BASE_URL", DEFAULT_BASE_URL)
    app_id = os.environ["OER_APP_ID"]
    base_currency = os.environ.get("OER_BASE_CURRENCY", "USD")
    symbols = os.environ.get("OER_SYMBOLS", DEFAULT_SYMBOLS)

    records, status = fetch_fx_rates(base_url, app_id, base_currency, symbols)
    key, contract = put_raw(bucket, SOURCE, records, status)

    return {"statusCode": 200, "s3_key": key, "contract": contract}
