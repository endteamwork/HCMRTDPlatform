IF DB_ID('hcm') IS NULL
    CREATE DATABASE hcm;
GO
USE hcm;
GO
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
GO
