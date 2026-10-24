"""lambda_jobs_ingest: fetch US federal job postings from the USAJOBS
Search API and store them in the raw S3 area with a metadata contract.

Env vars:
    S3_BUCKET           target bucket
    USAJOBS_API_KEY     Authorization-Key header value
    USAJOBS_USER_AGENT  registered email for the User-Agent header
    USAJOBS_BASE_URL    optional, defaults to the public search endpoint
    RESULTS_PER_PAGE    optional, defaults to 500 (API maximum)
"""

import os

import requests

from common.contract import put_raw

SOURCE = "jobs"
DEFAULT_BASE_URL = "https://data.usajobs.gov/api/search"


def fetch_job_postings(base_url, api_key, user_agent, results_per_page=500):
    """Call the USAJOBS search API and flatten the postings.

    Returns (records, status_code). Raises on non-200 responses.
    """
    headers = {
        "Authorization-Key": api_key,
        "User-Agent": user_agent,
        "Host": "data.usajobs.gov",
    }
    resp = requests.get(
        base_url,
        headers=headers,
        params={"ResultsPerPage": results_per_page},
        timeout=60,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"USAJOBS API request failed with status {resp.status_code}: {resp.text[:500]}"
        )

    items = resp.json().get("SearchResult", {}).get("SearchResultItems", [])
    records = [flatten_posting(item) for item in items]
    return records, resp.status_code


def flatten_posting(item):
    """Extract the fields the hackathon asks for from one search result item."""
    d = item.get("MatchedObjectDescriptor", {})
    remuneration = (d.get("PositionRemuneration") or [{}])[0]
    return {
        "position_id": item.get("MatchedObjectId"),
        "title": d.get("PositionTitle"),
        "organization": d.get("OrganizationName"),
        "department": d.get("DepartmentName"),
        "location": d.get("PositionLocationDisplay"),
        "salary_min": remuneration.get("MinimumRange"),
        "salary_max": remuneration.get("MaximumRange"),
        "salary_interval": remuneration.get("RateIntervalCode"),
        "open_date": d.get("PositionStartDate"),
        "close_date": d.get("ApplicationCloseDate"),
        "url": d.get("PositionURI"),
    }


def lambda_handler(event, context):
    bucket = os.environ["S3_BUCKET"]
    base_url = os.environ.get("USAJOBS_BASE_URL", DEFAULT_BASE_URL)
    api_key = os.environ["USAJOBS_API_KEY"]
    user_agent = os.environ["USAJOBS_USER_AGENT"]
    results_per_page = int(os.environ.get("RESULTS_PER_PAGE", "500"))

    records, status = fetch_job_postings(base_url, api_key, user_agent, results_per_page)
    key, contract = put_raw(bucket, SOURCE, records, status)

    return {"statusCode": 200, "s3_key": key, "contract": contract}
