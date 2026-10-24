"""lambda_benchmarks_scraper: scrape the BLS highest-paying occupations table
and store the top 10 occupations by median annual pay in the raw S3 area.

Env vars:
    S3_BUCKET     target bucket
    BLS_URL       optional, defaults to https://www.bls.gov/ooh/highest-paying.htm
    TOP_N         optional, defaults to 10
"""

import os
import re

import requests
from bs4 import BeautifulSoup

from common.contract import put_raw

SOURCE = "benchmarks"
DEFAULT_URL = "https://www.bls.gov/ooh/highest-paying.htm"
# bls.gov rejects scripted requests pretending to be browsers, but accepts
# clients that identify themselves with contact info (BLS scraping policy).
BROWSER_HEADERS = {
    "User-Agent": "PolaraptHCM-DataHackathon/1.0 (contact: ali.jamil@gorelo.io)",
    "Accept": "text/html,application/xhtml+xml",
}


def parse_pay(text):
    """'$239,200 or more' / '$157,740' -> 239200.0 / 157740.0, else None."""
    m = re.search(r"\$?([\d,]+(?:\.\d+)?)", text or "")
    return float(m.group(1).replace(",", "")) if m else None


def scrape_highest_paying(url, top_n=10):
    """Scrape the occupations table; return (records, status_code).

    Records are the top N occupations sorted by median annual pay descending.
    Raises on non-200 responses or if no table rows can be parsed.
    """
    resp = requests.get(url, headers=BROWSER_HEADERS, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(
            f"BLS page request failed with status {resp.status_code}"
        )

    soup = BeautifulSoup(resp.text, "html.parser")
    records = []
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 2 or row.find("th") and not row.find("td"):
                continue  # header row
            occupation = cells[0].get_text(" ", strip=True)
            pay_text = cells[1].get_text(" ", strip=True)
            pay = parse_pay(pay_text)
            if occupation and pay is not None:
                records.append(
                    {
                        "occupation": occupation,
                        "median_annual_pay": pay,
                        "median_annual_pay_text": pay_text,
                    }
                )
        if records:
            break  # first table with parseable rows is the rankings table

    if not records:
        raise RuntimeError("Could not parse any occupation rows from the BLS page")

    records.sort(key=lambda r: r["median_annual_pay"], reverse=True)
    records = records[:top_n]
    for rank, rec in enumerate(records, start=1):
        rec["rank"] = rank
    return records, resp.status_code


def lambda_handler(event, context):
    bucket = os.environ["S3_BUCKET"]
    url = os.environ.get("BLS_URL", DEFAULT_URL)
    top_n = int(os.environ.get("TOP_N", "10"))

    records, status = scrape_highest_paying(url, top_n)
    key, contract = put_raw(bucket, SOURCE, records, status)

    return {"statusCode": 200, "s3_key": key, "contract": contract}
