"""Unit tests for lambda_fx_ingest (Open Exchange Rates ingestion module)."""

import json

import pytest
import responses

from conftest import BUCKET, load_handler

handler = load_handler("fx_ingest")

API_URL = "https://openexchangerates.org/api/latest.json"


def oer_payload():
    return {
        "timestamp": 1792836000,  # 2026-10-24T10:00:00Z
        "base": "USD",
        "rates": {
            "PKR": 278.5,
            "SAR": 3.75,
            "AED": 3.6725,
            "GBP": 0.79,
            "EUR": 0.92,
            "INR": 84.1,
            "JPY": 151.2,  # not requested — must be filtered out
            "CAD": 1.38,
        },
    }


@responses.activate
def test_fetch_fx_rates_filters_to_requested_currencies():
    responses.add(responses.GET, API_URL, json=oer_payload(), status=200)

    records, status = handler.fetch_fx_rates(API_URL, "test-app-id")

    assert status == 200
    currencies = {r["currency"] for r in records}
    assert currencies == {"PKR", "SAR", "AED", "GBP", "EUR", "INR"}
    pkr = next(r for r in records if r["currency"] == "PKR")
    assert pkr["rate"] == 278.5
    assert pkr["base_currency"] == "USD"
    assert pkr["rate_timestamp"] == "2026-10-24T10:00:00Z"


@responses.activate
def test_fetch_fx_rates_sends_app_id_and_base():
    responses.add(responses.GET, API_URL, json=oer_payload(), status=200)

    handler.fetch_fx_rates(API_URL, "my-app-id", base_currency="USD")

    url = responses.calls[0].request.url
    assert "app_id=my-app-id" in url
    assert "base=USD" in url


@responses.activate
def test_fetch_fx_rates_custom_symbols_subset():
    responses.add(responses.GET, API_URL, json=oer_payload(), status=200)

    records, _ = handler.fetch_fx_rates(API_URL, "k", symbols="GBP, EUR")
    assert {r["currency"] for r in records} == {"GBP", "EUR"}


@responses.activate
def test_fetch_fx_rates_raises_on_api_error():
    responses.add(responses.GET, API_URL, json={"error": True}, status=403)

    with pytest.raises(RuntimeError, match="status 403"):
        handler.fetch_fx_rates(API_URL, "bad-app-id")


@responses.activate
def test_fetch_fx_rates_skips_missing_currency():
    payload = oer_payload()
    del payload["rates"]["PKR"]
    responses.add(responses.GET, API_URL, json=payload, status=200)

    records, _ = handler.fetch_fx_rates(API_URL, "k")
    currencies = {r["currency"] for r in records}
    assert "PKR" not in currencies
    assert currencies == {"SAR", "AED", "GBP", "EUR", "INR"}


@responses.activate
def test_lambda_handler_writes_raw_file_with_contract(aws_s3, monkeypatch):
    responses.add(responses.GET, API_URL, json=oer_payload(), status=200)
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    monkeypatch.setenv("OER_APP_ID", "test-app-id")

    result = handler.lambda_handler({}, None)

    assert result["statusCode"] == 200
    key = result["s3_key"]
    parts = key.split("/")
    assert parts[0] == "raw" and parts[1] == "fx" and key.endswith(".json")
    assert len(parts) == 6

    obj = aws_s3.get_object(Bucket=BUCKET, Key=key)
    meta = obj["Metadata"]
    assert meta["source"] == "fx"
    assert meta["record-count"] == "6"
    assert meta["response-status"] == "200"
    assert "ingested-at" in meta

    doc = json.loads(obj["Body"].read())
    assert doc["contract"]["source"] == "fx"
    assert doc["contract"]["record_count"] == 6
    assert len(doc["data"]) == 6
    assert all(r["base_currency"] == "USD" for r in doc["data"])
