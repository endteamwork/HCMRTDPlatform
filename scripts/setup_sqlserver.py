"""One-time SQL Server setup: update .env host, create/refresh the
hcm/sqlserver secret, create the hcm database and dbo.fx_rates table.

Usage: python scripts/setup_sqlserver.py <rds-endpoint>
"""

import json
import pathlib
import sys

import boto3
import pytds

REGION = "eu-north-1"
ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"

DDL_DB = "IF DB_ID('hcm') IS NULL CREATE DATABASE hcm;"
DDL_TABLE = """
IF OBJECT_ID('dbo.fx_rates', 'U') IS NULL
CREATE TABLE dbo.fx_rates (
    id             BIGINT IDENTITY(1,1) PRIMARY KEY,
    base_currency  VARCHAR(3)    NOT NULL,
    currency       VARCHAR(3)    NOT NULL,
    rate           DECIMAL(18,8) NOT NULL,
    rate_timestamp DATETIME2     NOT NULL,
    ingested_at    DATETIME2     NULL,
    source_file    VARCHAR(512)  NULL,
    loaded_at      DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);
"""


def read_env():
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def write_env_host(host):
    lines = []
    for line in ENV_PATH.read_text().splitlines():
        if line.startswith("SQLSERVER_HOST="):
            line = f"SQLSERVER_HOST={host}"
        lines.append(line)
    ENV_PATH.write_text("\n".join(lines) + "\n")


def main():
    host = sys.argv[1]
    write_env_host(host)
    env = read_env()

    secret = {
        "host": host,
        "port": int(env.get("SQLSERVER_PORT", 1433)),
        "username": env["SQLSERVER_USER"],
        "password": env["SQLSERVER_PASSWORD"],
        "database": env.get("SQLSERVER_DB", "hcm"),
    }
    sm = boto3.client("secretsmanager", region_name=REGION)
    try:
        sm.create_secret(Name="hcm/sqlserver", SecretString=json.dumps(secret))
        print("secret hcm/sqlserver created")
    except sm.exceptions.ResourceExistsException:
        sm.put_secret_value(
            SecretId="hcm/sqlserver", SecretString=json.dumps(secret)
        )
        print("secret hcm/sqlserver updated")

    with pytds.connect(
        server=host,
        port=secret["port"],
        user=secret["username"],
        password=secret["password"],
        database="master",
        login_timeout=60,
        autocommit=True,
    ) as conn:
        cur = conn.cursor()
        cur.execute(DDL_DB)
        print("database hcm ready")

    with pytds.connect(
        server=host,
        port=secret["port"],
        user=secret["username"],
        password=secret["password"],
        database="hcm",
        login_timeout=60,
        autocommit=True,
    ) as conn:
        cur = conn.cursor()
        cur.execute(DDL_TABLE)
        print("table dbo.fx_rates ready")


if __name__ == "__main__":
    main()
