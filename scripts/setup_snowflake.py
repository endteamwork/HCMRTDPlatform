"""One-time Snowflake setup: create/refresh the hcm/snowflake secret from
.env and create the HCM.JOBS.JOB_POSTINGS table.

Usage: python scripts/setup_snowflake.py
"""

import json
import pathlib

import boto3
from snowflake import connector

REGION = "eu-north-1"
ROOT = pathlib.Path(__file__).resolve().parents[1]

DDL = [
    "CREATE DATABASE IF NOT EXISTS HCM",
    "CREATE SCHEMA IF NOT EXISTS HCM.JOBS",
    """
    CREATE TABLE IF NOT EXISTS HCM.JOBS.JOB_POSTINGS (
        POSITION_ID     VARCHAR,
        TITLE           VARCHAR,
        ORGANIZATION    VARCHAR,
        DEPARTMENT      VARCHAR,
        LOCATION        VARCHAR,
        SALARY_MIN      VARCHAR,
        SALARY_MAX      VARCHAR,
        SALARY_INTERVAL VARCHAR,
        OPEN_DATE       VARCHAR,
        CLOSE_DATE      VARCHAR,
        URL             VARCHAR,
        SOURCE_FILE     VARCHAR,
        INGESTED_AT     TIMESTAMP_NTZ,
        LOADED_AT       TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
    )
    """,
]


def read_env():
    env = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip("'\"")
    return env


def main():
    env = read_env()
    for key in ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PASSWORD"):
        if not env.get(key):
            raise SystemExit(f"{key} is empty in .env")

    secret = {
        "username": env["SNOWFLAKE_USER"],
        "password": env["SNOWFLAKE_PASSWORD"],
        "account_name": env["SNOWFLAKE_ACCOUNT"],
    }
    sm = boto3.client("secretsmanager", region_name=REGION)
    try:
        sm.create_secret(Name="hcm/snowflake", SecretString=json.dumps(secret))
        print("secret hcm/snowflake created")
    except sm.exceptions.ResourceExistsException:
        sm.put_secret_value(SecretId="hcm/snowflake", SecretString=json.dumps(secret))
        print("secret hcm/snowflake updated")

    conn = connector.connect(
        user=secret["username"],
        password=secret["password"],
        account=secret["account_name"],
        role=env.get("SNOWFLAKE_ROLE", "ACCOUNTADMIN"),
        warehouse=env.get("SNOWFLAKE_WAREHOUSE", "COMPUTE_WH"),
    )
    cur = conn.cursor()
    for stmt in DDL:
        cur.execute(stmt)
    print("HCM.JOBS.JOB_POSTINGS ready")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
