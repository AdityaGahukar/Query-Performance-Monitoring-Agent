# Snowflake Native Deployment Guide (Deterministic Rule Detection & LLM Diagnostics)

This directory contains the files required to run the **POV-4 Query Performance Monitoring Agent** directly inside Snowflake. 

The architecture is **fully dynamic**: you use the exact same `src.zip` and `handler.py` files regardless of whether you are deploying to a Trial Account or a Production Enterprise Account.

---

## Folder Contents
* **`src/`**: A copy of the application source modules (synced and packaged).
* **`procedure/handler.py`**: The entrypoint handler for the Snowflake Stored Procedure. It dynamically checks for the presence of the NVIDIA API secret, runs the detection rule engine, and calls the LLM root cause analysis if the secret is present.
* **`procedure/src.zip`**: The compiled zip package containing all core python modules as dependencies for imports inside Snowflake.

---

## Architecture Modes

Choose the deployment guide option below that matches your Snowflake account limitations:

| Mode | Egress Traffic | Secrets Support | Execution Flow |
| :--- | :--- | :--- | :--- |
| **Option A: Production (Native EAI)** | Enabled | Supported | The Snowflake stored procedure runs ingestion, detection, and invokes the NVIDIA LLM natively in the sandbox. |
| **Option B: Trial (Hybrid Fallback)** | Blocked | Unsupported | Stored procedure logs findings to the database with `ANALYSIS = NULL`. A local script pulls these records and runs the LLM locally. |

---

## Option A: Production Accounts (Native EAI Mode)

Use this method when deploying on a Snowflake account that supports **External Access Integrations (EAI)**.

### Step 1: Create the Stage & Upload Files
Run the following SQL commands in your Snowflake Worksheet to create your monitoring database, schema, and secure code stage:

```sql
CREATE DATABASE IF NOT EXISTS POV4_DB;
CREATE SCHEMA IF NOT EXISTS POV4_DB.MONITORING;

CREATE OR REPLACE STAGE POV4_DB.MONITORING.POV4_CODE_STAGE
    DIRECTORY = (ENABLE = TRUE)
    ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');
```

Then, upload the compiled procedure files to the newly created stage using the Snowsight Stage Web UI:
* Upload **`procedure/src.zip`** to `@POV4_DB.MONITORING.POV4_CODE_STAGE`
* Upload **`procedure/handler.py`** to `@POV4_DB.MONITORING.POV4_CODE_STAGE`

### Step 2: Configure Network Egress & Secrets in Snowflake
Run these queries as `ACCOUNTADMIN` (or a role with create integration privileges) to register your Nvidia API key and open outbound traffic:

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
Compile the stored procedure, linking the external access integration and secret parameters:

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
Trigger a manual run once. This will automatically execute the internal schema initialization DDL to create the findings and watermark tables:
```sql
CALL POV4_DB.MONITORING.RUN_POV4_DETECTION();
```

By default, an empty watermark table will fetch query history starting from **1 hour ago**. If you want to collect historical data starting from a specific date on this new account, seed the watermark:
```sql
-- Seed the watermark cursor (e.g. to catch up from 2026-06-01)
INSERT INTO POV4_DB.MONITORING.POV4_WATERMARKS (SOURCE_NAME, LAST_PROCESSED_TIMESTAMP)
VALUES ('QUERY_HISTORY', '2026-06-01 00:00:00+00:00'::TIMESTAMP_TZ);
```
*(If you ever need to reset or change this collection date in the future, run: `UPDATE POV4_DB.MONITORING.POV4_WATERMARKS SET LAST_PROCESSED_TIMESTAMP = '2026-mm-dd...' WHERE SOURCE_NAME = 'QUERY_HISTORY';`)*

### Step 5: Automate with a Task Scheduler
Schedule the procedure to run automatically every 10 minutes:
```sql
CREATE OR REPLACE TASK POV4_DB.MONITORING.POV4_DETECTION_TASK
  WAREHOUSE = COMPUTE_WH
  SCHEDULE = '10 MINUTE'
AS
  CALL POV4_DB.MONITORING.RUN_POV4_DETECTION();

-- Resume the task to start the scheduler
ALTER TASK POV4_DB.MONITORING.POV4_DETECTION_TASK RESUME;
```

---

## Option B: Trial Accounts (Hybrid Enrichment Mode)

Use this option if Snowflake returns egress network compilation errors due to trial restrictions.

### Step 1: Create the Stage, Upload Files & Register the Procedure (No EAI Setup)
Run the following SQL commands in your Snowflake Worksheet to create your monitoring database, schema, and secure code stage:

```sql
CREATE DATABASE IF NOT EXISTS POV4_DB;
CREATE SCHEMA IF NOT EXISTS POV4_DB.MONITORING;

CREATE OR REPLACE STAGE POV4_DB.MONITORING.POV4_CODE_STAGE
    DIRECTORY = (ENABLE = TRUE)
    ENCRYPTION = (TYPE = 'SNOWFLAKE_SSE');
```

Then, upload the compiled procedure files to the stage using the Snowsight Stage Web UI:
* Upload **`procedure/src.zip`** to `@POV4_DB.MONITORING.POV4_CODE_STAGE`
* Upload **`procedure/handler.py`** to `@POV4_DB.MONITORING.POV4_CODE_STAGE`

After uploading, run the compile statement to register the stored procedure:

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
Call the procedure in your Snowflake Worksheet. The code automatically sets up the findings and watermark tables on this run:
```sql
CALL POV4_DB.MONITORING.RUN_POV4_DETECTION();
```

To seed the cursor date for historical ingestion on a new account:
```sql
-- Seed the watermark cursor (e.g. to catch up from 2026-06-01)
INSERT INTO POV4_DB.MONITORING.POV4_WATERMARKS (SOURCE_NAME, LAST_PROCESSED_TIMESTAMP)
VALUES ('QUERY_HISTORY', '2026-06-01 00:00:00+00:00'::TIMESTAMP_TZ);
```

### Step 3: Run the Local Enrichment Script
To generate the root cause diagnostics and update the findings table in Snowflake, run the enrichment daemon script from your local terminal:

```bash
# Processes findings generated in the last 2 hours, capped at 30 records
python scratch/enrich_findings_llm.py --hours 2 --limit 30
```
*(Ensure your `.env` contains your active `LLM_API_KEY` when running this local script.)*
