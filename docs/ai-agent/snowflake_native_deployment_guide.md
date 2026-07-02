# POV-4 Snowflake Native Deployment Guide

This guide provides instructions on how to deploy and run the **POV-4 Query Performance Monitoring Agent** directly inside Snowflake. 

The architecture is designed to be **fully dynamic**: you use the exact same `src.zip` and `handler.py` package regardless of whether you are deploying on a trial account or a production enterprise account.

---

## Architecture Modes

Depending on your Snowflake account permissions, you can run the agent in one of two modes:

| Feature | 1. Production Account (Native EAI Mode) | 2. Trial Account (Hybrid Enrichment Mode) |
| :--- | :--- | :--- |
| **stored procedure** | Runs query ingestion, deterministic rule detection, **AND** LLM root cause analysis. | Runs query ingestion and deterministic rule detection. Writes findings to database with `ANALYSIS = NULL`. |
| **LLM Call Location** | Inside the Snowflake Sandbox. | Locally on your VM/Terminal using a python script. |
| **Network Requirements** | Egress Network Rule allowed for `integrate.api.nvidia.com`. | No outbound network access required in Snowflake. |
| **Zip/Handler Code** | Same (`src.zip` and `handler.py`). | Same (`src.zip` and `handler.py`). |

---

## Option A: Production Accounts (Native EAI Mode)

Use this approach when deploying to an enterprise account that supports **External Access Integrations (EAI)** and **Secrets**.

### Step 1: Create the Stage & Upload Files
Run the following SQL commands in your Snowflake Worksheet to create your monitoring database, schema, and secure stage:

```sql
CREATE DATABASE IF NOT EXISTS POV4_DB;
CREATE SCHEMA IF NOT EXISTS POV4_DB.MONITORING;

CREATE OR REPLACE STAGE POV4_DB.MONITORING.POV4_CODE_STAGE
    DIRECTORY = (ENABLE = TRUE)
    ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');
```

Then, upload the newly generated local files in `snowflake_native/procedure/` to the stage using the Snowsight Stage Web UI:
1. Upload **`snowflake_native/procedure/src.zip`** to `@POV4_DB.MONITORING.POV4_CODE_STAGE`.
2. Upload **`snowflake_native/procedure/handler.py`** to `@POV4_DB.MONITORING.POV4_CODE_STAGE`.

### Step 2: Configure Network Egress & Secrets
Run these commands as `ACCOUNTADMIN` (or a role with EAI privileges) to securely save your API key and allow outbound internet traffic to the Nvidia AI Endpoints:

```sql
-- 1. Create a Secret containing your Nvidia API key
CREATE OR REPLACE SECRET POV4_DB.MONITORING.NVIDIA_API_KEY_SECRET
  TYPE = GENERIC_STRING
  SECRET_STRING = 'your_nvidia_api_key_here';

-- 2. Define an Egress Network Rule for the NVIDIA Endpoint
CREATE OR REPLACE NETWORK RULE POV4_DB.MONITORING.NVIDIA_API_NETWORK_RULE
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = ('integrate.api.nvidia.com');

-- 3. Create the External Access Integration linking the Network Rule and Secret
CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION NVIDIA_API_INTEGRATION
  ALLOWED_NETWORK_RULES = (POV4_DB.MONITORING.NVIDIA_API_NETWORK_RULE)
  ALLOWED_AUTHENTICATION_SECRETS = (POV4_DB.MONITORING.NVIDIA_API_KEY_SECRET)
  ENABLED = TRUE;

-- 4. Grant usage privileges to the monitoring role
GRANT USAGE ON INTEGRATION NVIDIA_API_INTEGRATION TO ROLE POV4_MONITOR_ROLE;
GRANT USAGE ON SECRET POV4_DB.MONITORING.NVIDIA_API_KEY_SECRET TO ROLE POV4_MONITOR_ROLE;
```

### Step 3: Register the LLM-Enabled Stored Procedure
Compile the stored procedure linking it to the integration and secret:

```sql
CREATE OR REPLACE PROCEDURE POV4_DB.MONITORING.RUN_POV4_DETECTION()
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'pydantic', 'typing-extensions', 'tenacity', 'pydantic-settings', 'requests')
IMPORTS = (
    '@POV4_DB.MONITORING.POV4_CODE_STAGE/src.zip',
    '@POV4_DB.MONITORING.POV4_CODE_STAGE/handler.py'
)
EXTERNAL_ACCESS_INTEGRATIONS = (NVIDIA_API_INTEGRATION)
SECRETS = ('NVIDIA_API_KEY_SECRET' = POV4_DB.MONITORING.NVIDIA_API_KEY_SECRET)
HANDLER = 'handler.run_detection'
EXECUTE AS CALLER;
```

### Step 4: Initial Run & Watermark Seeding
Trigger a manual run once. The procedure will automatically detect and run the DDL schema to create findings and watermark tables if they do not exist:
```sql
CALL POV4_DB.MONITORING.RUN_POV4_DETECTION();
```

By default, an empty watermark table will fetch query history starting from **1 hour ago**. If you are setting up a new account and want to collect historical data starting from a specific date (e.g., June 1st), seed the watermark:
```sql
-- Seed the watermark cursor to start historical collection
INSERT INTO POV4_DB.MONITORING.POV4_WATERMARKS (SOURCE_NAME, LAST_PROCESSED_TIMESTAMP)
VALUES ('QUERY_HISTORY', '2026-06-01 00:00:00+00:00'::TIMESTAMP_TZ);
```
*(To modify or reset this date in the future, run: `UPDATE POV4_DB.MONITORING.POV4_WATERMARKS SET LAST_PROCESSED_TIMESTAMP = '2026-mm-dd...' WHERE SOURCE_NAME = 'QUERY_HISTORY';`)*

### Step 5: Automate with a Snowflake Task
Schedule it to run automatically every 10 minutes:
```sql
CREATE OR REPLACE TASK POV4_DB.MONITORING.POV4_DETECTION_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = '10 MINUTE'
AS
  CALL POV4_DB.MONITORING.RUN_POV4_DETECTION();

ALTER TASK POV4_DB.MONITORING.POV4_DETECTION_TASK RESUME;
```

---

## Option B: Trial Accounts (Hybrid Enrichment Mode)

Use this fallback approach on trial accounts where External Access Integrations are blocked.

### Step 1: Create the Stage, Upload Files & Register the Procedure (Without EAI / Secrets)
Run the following SQL commands in your Snowflake Worksheet to create your monitoring database, schema, and secure stage:

```sql
CREATE DATABASE IF NOT EXISTS POV4_DB;
CREATE SCHEMA IF NOT EXISTS POV4_DB.MONITORING;

CREATE OR REPLACE STAGE POV4_DB.MONITORING.POV4_CODE_STAGE
    DIRECTORY = (ENABLE = TRUE)
    ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');
```

Then, upload the identical `src.zip` and `handler.py` files to the stage using the Snowsight Stage Web UI:
1. Upload **`snowflake_native/procedure/src.zip`** to `@POV4_DB.MONITORING.POV4_CODE_STAGE`.
2. Upload **`snowflake_native/procedure/handler.py`** to `@POV4_DB.MONITORING.POV4_CODE_STAGE`.

After uploading, run this register command to compile the procedure:

```sql
CREATE OR REPLACE PROCEDURE POV4_DB.MONITORING.RUN_POV4_DETECTION()
RETURNS STRING
LANGUAGE PYTHON
RUNTIME_VERSION = '3.11'
PACKAGES = ('snowflake-snowpark-python', 'pydantic', 'typing-extensions', 'tenacity', 'pydantic-settings')
IMPORTS = (
    '@POV4_DB.MONITORING.POV4_CODE_STAGE/src.zip',
    '@POV4_DB.MONITORING.POV4_CODE_STAGE/handler.py'
)
HANDLER = 'handler.run_detection'
EXECUTE AS CALLER;
```

### Step 2: Initial Run & Watermark Seeding
Call the procedure natively inside Snowflake. It creates database tables automatically on this run:
```sql
CALL POV4_DB.MONITORING.RUN_POV4_DETECTION();
```

To seed the cursor date for historical catchup:
```sql
-- Seed the watermark cursor to start historical collection
INSERT INTO POV4_DB.MONITORING.POV4_WATERMARKS (SOURCE_NAME, LAST_PROCESSED_TIMESTAMP)
VALUES ('QUERY_HISTORY', '2026-06-01 00:00:00+00:00'::TIMESTAMP_TZ);
```

### Step 3: Run the Local Enrichment Script
Run the local daemon script to retrieve the unenriched findings, call Llama 3.1 8B, and merge the diagnostics back to your Snowflake table:

```bash
# Processes findings from the last 2 hours, capped at 30 records
python scratch/enrich_findings_llm.py --hours 2 --limit 30
```
