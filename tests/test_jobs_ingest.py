"""Unit tests for lambda_jobs_ingest (USAJOBS ingestion module)."""

import json

import pytest
import responses

from conftest import BUCKET, load_handler

handler = load_handler("jobs_ingest")

API_URL = "https://data.usajobs.gov/api/search"


def usajobs_payload(n=2):
    items = []
    for i in range(n):
        items.append(
            {
                "MatchedObjectId": f"80000{i}",
                "MatchedObjectDescriptor": {
                    "PositionTitle": f"Data Engineer {i}",
                    "OrganizationName": "Department of Testing",
                    "DepartmentName": "DOT",
                    "PositionLocationDisplay": "Washington, DC",
                    "PositionRemuneration": [
                        {
                            "MinimumRange": "90000",
                            "MaximumRange": "140000",
                            "RateIntervalCode": "PA",
                        }
                    ],
                    "PositionStartDate": "2026-10-01",
                    "ApplicationCloseDate": "2026-11-15",
                    "PositionURI": f"https://usajobs.gov/job/80000{i}",
                },
            }
        )
    return {"SearchResult": {"SearchResultItems": items}}


@responses.activate
def test_fetch_job_postings_flattens_fields():
    responses.add(responses.GET, API_URL, json=usajobs_payload(3), status=200)

    records, status = handler.fetch_job_postings(
        API_URL, "test-key", "me@example.com", results_per_page=500
    )

    assert status == 200
    assert len(records) == 3
    rec = records[0]
    assert rec["title"] == "Data Engineer 0"
    assert rec["organization"] == "Department of Testing"
    assert rec["location"] == "Washington, DC"
    assert rec["salary_min"] == "90000"
    assert rec["salary_max"] == "140000"
    assert rec["open_date"] == "2026-10-01"
    assert rec["close_date"] == "2026-11-15"


@responses.activate
def test_fetch_job_postings_sends_auth_headers_and_page_size():
    responses.add(responses.GET, API_URL, json=usajobs_payload(1), status=200)

    handler.fetch_job_postings(API_URL, "secret-key", "me@example.com")

    req = responses.calls[0].request
    assert req.headers["Authorization-Key"] == "secret-key"
    assert req.headers["User-Agent"] == "me@example.com"
    assert "ResultsPerPage=500" in req.url


@responses.activate
def test_fetch_job_postings_raises_on_api_error():
    responses.add(responses.GET, API_URL, json={"error": "nope"}, status=401)

    with pytest.raises(RuntimeError, match="status 401"):
        handler.fetch_job_postings(API_URL, "bad-key", "me@example.com")


@responses.activate
def test_fetch_job_postings_empty_results():
    responses.add(
        responses.GET,
        API_URL,
        json={"SearchResult": {"SearchResultItems": []}},
        status=200,
    )

    records, status = handler.fetch_job_postings(API_URL, "k", "ua")
    assert records == []
    assert status == 200


@responses.activate
def test_lambda_handler_writes_raw_file_with_contract(aws_s3, monkeypatch):
    responses.add(responses.GET, API_URL, json=usajobs_payload(5), status=200)
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    monkeypatch.setenv("USAJOBS_API_KEY", "test-key")
    monkeypatch.setenv("USAJOBS_USER_AGENT", "me@example.com")

    result = handler.lambda_handler({}, None)

    assert result["statusCode"] == 200
    key = result["s3_key"]
    # Key layout: raw/jobs/YYYY/MM/DD/HHMM.json
    parts = key.split("/")
    assert parts[0] == "raw" and parts[1] == "jobs" and key.endswith(".json")
    assert len(parts) == 6

    obj = aws_s3.get_object(Bucket=BUCKET, Key=key)
    # Contract as S3 object metadata
    meta = obj["Metadata"]
    assert meta["source"] == "jobs"
    assert meta["record-count"] == "5"
    assert meta["response-status"] == "200"
    assert "ingested-at" in meta

    # Contract embedded in the file body + data integrity
    doc = json.loads(obj["Body"].read())
    assert doc["contract"]["source"] == "jobs"
    assert doc["contract"]["record_count"] == 5
    assert doc["contract"]["response_status"] == 200
    assert len(doc["data"]) == 5
    assert doc["data"][2]["title"] == "Data Engineer 2"
