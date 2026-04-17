# DataGuardian 🛡️

> AI-powered Compliance & Breach Impact Agent for OpenMetadata

DataGuardian is an MCP server that turns OpenMetadata into an always-on compliance analyst.
Ask natural language questions about your sensitive data — it answers using OpenMetadata's
Search, Lineage, Tags, Governance, Teams, and Data Quality APIs.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [What The Platform Does](#2-what-the-platform-does)
3. [System Overview](#3-system-overview)
4. [System Architecture](#4-system-architecture)
5. [Code Structure & Reproducibility](#5-code-structure--reproducibility)
6. [Core Logic Deep Dive](#6-core-logic-deep-dive)
7. [Architecture Decisions](#7-architecture-decisions)
8. [Performance Optimizations](#8-performance-optimizations)
9. [Setup Instructions](#9-setup-instructions)
10. [API Reference](#10-api-reference)
11. [Known Limitations](#11-known-limitations)
12. [What I'd Improve With More Time](#12-what-id-improve-with-more-time)

---

## 1. Problem Statement

When a data breach or compliance audit hits, answering "what's affected and who owns it?" takes days of manual cross-referencing across catalogs, wikis, org charts, and ticketing systems.

Data teams face three compounding problems:

- **Discovery gap** — sensitive data (PII, PHI, financial records) is scattered across hundreds of tables, dashboards, and pipelines with inconsistent or missing tags.
- **Blast radius blindness** — when an asset is compromised, nobody knows which downstream systems, reports, or ML models are affected until it's too late.
- **Governance debt** — sensitive assets accumulate with no owner, no quality tests, and no lineage, making them invisible to compliance teams until an audit or incident forces the issue.

DataGuardian answers all three in seconds, not days.

---

## 2. What The Platform Does

| Tool | What it answers |
|------|----------------|
| `search_sensitive` | Which assets are tagged PII / GDPR / HIPAA / PHI? |
| `breach_impact` | If this table is breached, what's the full blast radius? |
| `classify_table` | Auto-detect PII columns and tag them back in OpenMetadata |
| `compliance_report` | Generate a GDPR Article 30 / HIPAA / CCPA / SOC2 inventory |
| `orphaned_sensitive_assets` | Which sensitive assets have no owner, no tests, or no lineage? |
| `data_access_chain` | Who has access to this table and all downstream assets? |

### Example Queries (natural language via any MCP client)

```
"Which tables contain PII data?"
"If payments.transactions was breached, what's the blast radius?"
"Auto-classify the users table and tag any PII columns"
"Generate a GDPR compliance report for our analytics domain"
"Show me all sensitive assets with no owner — our highest risk data"
"Who do I need to notify if the customers table is compromised?"
```

---

## 3. System Overview

DataGuardian sits between your MCP client (Claude Desktop, Kiro, Cursor) and your OpenMetadata instance. It exposes six tools that each map to a specific governance workflow:

```mermaid
flowchart TD
    U(["👤 User\n(natural language)"])
    MC["MCP Client\nClaude / Kiro / Cursor"]
    DG["🛡️ DataGuardian\nMCP Server"]
    OM["OpenMetadata\nREST API"]
    LLM["🤖 OpenAI\nLLM API"]

    U -->|natural language query| MC
    MC -->|tool calls via MCP protocol| DG

    DG -->|search_sensitive| OM
    DG -->|breach_impact| OM
    DG -->|orphaned_sensitive_assets| OM
    DG -->|data_access_chain| OM
    DG -->|classify_table| OM
    DG -->|classify_table| LLM
    DG -->|compliance_report| OM
    DG -->|compliance_report| LLM

    OM --> SearchAPI["Search API\nasset discovery"]
    OM --> LineageAPI["Lineage API\ngraph traversal"]
    OM --> TablesAPI["Tables API\nschema + tags"]
    OM --> TeamsAPI["Teams/Users API\nownership"]
    OM --> QualityAPI["Data Quality API\ntest coverage"]
```

The LLM (OpenAI) is only invoked for two tools: `classify_table` (column-level PII detection) and `compliance_report` (narrative generation). All other tools are pure API orchestration.

---

## 4. System Architecture

```mermaid
graph LR
    subgraph Client["MCP Client Layer"]
        C["Claude Desktop\nKiro / Cursor"]
    end

    subgraph Server["DataGuardian MCP Server (FastMCP)"]
        SRV["server.py\ntool registration + system prompt"]
        OMC["om_client.py\nasync HTTP wrapper"]
        CLS["classifier.py\nLLM PII classifier"]

        subgraph Tools["tools/"]
            T1["search_sensitive.py"]
            T2["breach_impact.py\nBFS traversal"]
            T3["auto_classify.py\nLLM + tag write-back"]
            T4["compliance_report.py"]
            T5["orphan_finder.py\nrisk scoring"]
            T6["access_chain.py"]
        end

        SRV --> Tools
        Tools --> OMC
        T3 --> CLS
        T4 --> CLS
    end

    subgraph External["External APIs"]
        OM["OpenMetadata\nREST API"]
        OAI["OpenAI API"]
    end

    C -->|MCP protocol| SRV
    OMC -->|httpx async| OM
    CLS -->|chat completions| OAI
```

### Component Responsibilities

**`server.py`** — FastMCP server entrypoint. Registers all six tools and holds the system prompt that shapes how the LLM agent uses them. Initializes the OpenMetadata client on startup.

**`om_client.py`** — Thin async HTTP wrapper around the OpenMetadata REST API. Provides `get`, `put`, and `patch` (JSON Patch / RFC 6902) methods. All tools use this exclusively — no direct HTTP calls in tool code.

**`classifier.py`** — Standalone LLM classifier. Sends column names + data types to OpenAI and returns structured PII category + confidence + tag FQN mappings. Used by `auto_classify`.

**`tools/`** — One file per tool. Each tool is a self-contained async function that composes `om_client` calls and optional LLM calls into a structured response.

---

## 5. Code Structure & Reproducibility

```
dataguardian/
├── dataguardian/
│   ├── __init__.py
│   ├── server.py              # FastMCP server, tool registration
│   ├── om_client.py           # Async OpenMetadata REST client
│   └── tools/
│       ├── __init__.py
│       ├── search_sensitive.py    # Tag-based asset search
│       ├── breach_impact.py       # BFS lineage traversal
│       ├── auto_classify.py       # LLM PII classification + tag write-back
│       ├── compliance_report.py   # Regulation-scoped compliance inventory
│       ├── orphan_finder.py       # Risk scoring for ungoverned assets
│       └── access_chain.py        # Ownership + notification chain builder
├── classifier.py              # Standalone LLM PII classifier module
├── pyproject.toml             # Package definition and dependencies
├── requirements.txt           # Pip-installable dependencies
├── mcp.json                   # MCP client configuration template
└── .env.example               # Environment variable template
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `fastmcp>=2.0.0` | MCP server framework |
| `httpx>=0.27.0` | Async HTTP client for OpenMetadata API |
| `openai>=1.30.0` | LLM calls for classification and report generation |
| `python-dotenv>=1.0.0` | Environment variable loading |
| `pydantic>=2.0.0` | Data validation |
| `rich>=13.0.0` | Terminal output formatting |

---

## 6. Core Logic Deep Dive

### `search_sensitive` — Tag-based Asset Discovery

Queries the OpenMetadata Search API using `tags.tagFQN:<tag>` against the unified `all` index (or a specific entity index). Results are grouped by entity type and enriched with owner, tier, and tag metadata.

Supported tags out of the box: `PII`, `Sensitive`, `GDPR`, `HIPAA`, `Confidential`, `PHI`.

### `breach_impact` — BFS Lineage Traversal

Implements a breadth-first search over the OpenMetadata lineage graph starting from a given asset FQN. At each hop it fetches the lineage node, collects downstream (or upstream) edges, and enqueues unvisited neighbors up to `max_depth` hops.

```mermaid
flowchart TD
    START(["breach_impact(fqn)"])
    RESOLVE["_resolve_entity(fqn)\ntry tables → dashboards\n→ pipelines → topics → mlmodels"]
    QUEUE["Init BFS queue\n(entity_id, entity_type, depth=0)"]
    POP["Pop (id, type, depth)"]
    VISITED{"Already\nvisited?"}
    DEPTH{"depth >\nmax_depth?"}
    FETCH["GET /lineage/{type}/{id}\ndownstreamDepth=1"]
    COLLECT["Collect node + edges\nEnqueue unvisited neighbors"]
    MARK["Mark visited"]
    DONE{"Queue\nempty?"}
    DEDUP["Deduplicate nodes by ID"]
    OWNERS["Build owners_to_notify\n(deduplicated set)"]
    RESULT(["Return blast radius\nnodes, edges, owners"])

    START --> RESOLVE --> QUEUE --> POP
    POP --> VISITED
    VISITED -->|yes| DONE
    VISITED -->|no| DEPTH
    DEPTH -->|yes| DONE
    DEPTH -->|no| FETCH --> COLLECT --> MARK --> DONE
    DONE -->|no| POP
    DONE -->|yes| DEDUP --> OWNERS --> RESULT
```

The result includes:
- All affected nodes with type, owner, and FQN
- A deduplicated `owners_to_notify` list for incident response
- An `affected_by_type` summary (tables, dashboards, pipelines, ML models)

Entity resolution tries `tables` first, then `dashboards`, `pipelines`, `topics`, and `mlmodels` — the first successful lookup wins.

### `classify_table` — Closed-Loop PII Tagging

```mermaid
sequenceDiagram
    participant Agent as MCP Agent
    participant Tool as auto_classify.py
    participant OM as OpenMetadata API
    participant LLM as OpenAI API

    Agent->>Tool: classify_table(table_fqn, dry_run)
    Tool->>OM: GET /tables/name/{fqn}?fields=columns,id
    OM-->>Tool: table schema (columns + data types)
    Tool->>Tool: Build column summary string
    Tool->>LLM: chat.completions (column names + types)
    LLM-->>Tool: JSON [{column, category, confidence, reason}]
    Tool->>Tool: Map category → TAG_MAP FQN
    Tool->>Tool: Build JSON Patch ops (add /columns/{idx}/tags/-)
    alt dry_run = false
        Tool->>OM: PATCH /tables/{id} (RFC 6902 JSON Patch)
        OM-->>Tool: updated table
    end
    Tool-->>Agent: {columns_analyzed, sensitive_columns_found, tags_applied}
```

1. Fetches the full table schema from OpenMetadata (`/tables/name/{fqn}`)
2. Builds a column summary (name + data type + description) and sends it to OpenAI
3. Parses the structured JSON response mapping columns to PII categories
4. Constructs JSON Patch operations (`add` to `/columns/{idx}/tags/-`) for each detected column
5. Applies the patch to OpenMetadata via `PATCH /tables/{id}` (skipped in `dry_run` mode)

Tag FQN mapping (configurable in `TAG_MAP`):

| Category | Tag FQN |
|----------|---------|
| email | `PII.Email` |
| phone | `PII.Phone` |
| ssn | `PII.SSN` |
| name | `PII.Name` |
| address | `PII.Address` |
| date_of_birth | `PII.DateOfBirth` |
| credit_card | `PII.CreditCard` |
| ip_address | `PII.IPAddress` |
| health | `PHI.HealthData` |
| financial | `Sensitive.Financial` |
| password / token | `Sensitive.Credential` |

### `compliance_report` — Regulation-Scoped Inventory

Maps each regulation to a set of relevant tags, then fans out `search_sensitive` calls to collect all matching assets. Deduplicates by FQN, optionally filters by OpenMetadata domain, identifies orphaned assets (no owner), and passes the inventory to OpenAI to generate a structured markdown report.

```mermaid
flowchart TD
    START(["compliance_report(regulation, domain)"])
    TAGS["Look up regulation → tags\nGDPR: PII, GDPR, Sensitive\nHIPAA: PHI, HIPAA, HealthData\nCCPA: PII, CCPA, Sensitive\nSOC2: Sensitive, Confidential"]
    FAN["Fan-out search_sensitive\n× N tags (parallel)"]
    DEDUP["Deduplicate assets by FQN"]
    DOMAIN{"domain\nfilter?"}
    FILTER["Filter to domain assets\nGET /search/query?q=domain.name:X"]
    ORPHAN["Identify orphaned assets\n(no owner field)"]
    LLM["Send top-50 assets to OpenAI\nGenerate markdown report"]
    RESULT(["Return {inventory, report,\norphaned_count}"])

    START --> TAGS --> FAN --> DEDUP
    DEDUP --> DOMAIN
    DOMAIN -->|yes| FILTER --> ORPHAN
    DOMAIN -->|no| ORPHAN
    ORPHAN --> LLM --> RESULT
```

Regulation → tag mapping:

| Regulation | Tags searched |
|------------|--------------|
| GDPR | PII, GDPR, Sensitive |
| HIPAA | PHI, HIPAA, HealthData |
| CCPA | PII, CCPA, Sensitive |
| SOC2 | Sensitive, Confidential |

### `orphaned_sensitive_assets` — Risk Scoring

Scans all sensitive assets across all default tags, deduplicates, then scores each asset:

```mermaid
flowchart LR
    subgraph Scan["1 · Scan & Deduplicate"]
        TAGS["Default tags:\nPII, Sensitive, GDPR\nHIPAA, Confidential, PHI"]
        SEARCH["search_sensitive\n× 6 tags"]
        DEDUP["Deduplicate by FQN"]
        TAGS --> SEARCH --> DEDUP
    end

    subgraph Score["2 · Risk Scoring per Asset"]
        direction TB
        O{"No owner?"}  -->|+40| S
        Q{"No quality\ntests?"}  -->|+25| S
        L{"No lineage?"}  -->|+15| S
        D{"No description?"}  -->|+10| S
        T{"No tier?"}  -->|+10| S
        S["risk_score"]
    end

    subgraph Level["3 · Risk Level"]
        C["CRITICAL ≥ 65"]
        H["HIGH ≥ 40"]
        M["MEDIUM ≥ 20"]
        LW["LOW < 20"]
    end

    DEDUP --> Score
    S --> Level
```

| Risk Flag | Score |
|-----------|-------|
| NO_OWNER | +40 |
| NO_QUALITY_TESTS | +25 |
| NO_LINEAGE | +15 |
| NO_DESCRIPTION | +10 |
| NO_TIER | +10 |

Risk levels: `CRITICAL` (≥65), `HIGH` (≥40), `MEDIUM` (≥20), `LOW` (<20).

Results are sorted by risk score descending, with `CRITICAL` and `HIGH` assets surfaced first.

### `data_access_chain` — Ownership & Notification

Fetches the table's direct owner, followers, domain, and data products. Resolves the owner's team memberships. Runs a 3-hop downstream lineage traversal to collect all downstream asset owners. Returns a deduplicated `notification_list` ready for incident response.

```mermaid
flowchart TD
    START(["data_access_chain(table_fqn)"])
    FETCH["GET /tables/name/{fqn}\nfields: owner, followers, domain, dataProducts"]
    OWNER["Resolve direct owner\nGET /users or /teams"]
    LINEAGE["breach_impact(fqn, depth=3)\ndownstream traversal"]
    DNODES["Collect downstream node owners"]
    RESOLVE["Resolve each downstream owner\ntry /users → /teams"]
    NOTIFY["Build notification_list\n(deduplicated union)"]
    RESULT(["Return access chain\n+ notification_list"])

    START --> FETCH --> OWNER
    FETCH --> LINEAGE --> DNODES --> RESOLVE
    OWNER --> NOTIFY
    RESOLVE --> NOTIFY
    NOTIFY --> RESULT
```

---

## 7. Architecture Decisions

**FastMCP over raw MCP SDK** — FastMCP provides decorator-based tool registration, automatic schema generation from type hints, and a clean `run()` entrypoint. This keeps `server.py` focused on tool definitions rather than protocol plumbing.

**Single shared `om_client` module** — All tools import from one place. This makes it trivial to swap the HTTP client, add retry logic, or inject auth headers globally without touching tool code.

**Async throughout** — Every tool and HTTP call is `async`. This matters for `compliance_report` and `orphaned_sensitive_assets` which fan out multiple concurrent API calls. Using `httpx.AsyncClient` with a 30-second timeout keeps things responsive without blocking.

**LLM only where necessary** — OpenAI is only called in `classify_table` and `compliance_report`. Everything else is deterministic API orchestration. This keeps costs low and latency predictable for the four non-LLM tools.

**BFS with visited set for lineage** — Lineage graphs can have cycles (e.g. a pipeline that reads and writes to the same domain). The visited set in `breach_impact` prevents infinite loops and redundant API calls.

**JSON Patch for tag write-back** — OpenMetadata's column tag API uses RFC 6902 JSON Patch. Using `PATCH` with `add` operations is the correct idiomatic approach — it appends tags without overwriting existing ones.

**`dry_run` mode on classify** — Lets teams preview what would be tagged before committing. Useful for auditing LLM accuracy before enabling automated tagging in production.

---

## 8. Performance Optimizations

- **Deduplication by FQN** — `compliance_report` and `orphan_finder` both fan out multiple tag searches that can return overlapping assets. FQN-based deduplication ensures each asset is processed once.
- **Lineage depth cap** — `LINEAGE_MAX_DEPTH` (default 5, configurable via env) prevents runaway traversal on deeply connected graphs.
- **Asset cap on LLM calls** — `compliance_report` caps the asset list at 50 items before sending to OpenAI to stay within token limits while still covering the most important assets.
- **Entity type resolution short-circuit** — `breach_impact` tries entity types in order of likelihood (tables first) and stops at the first successful lookup.
- **Per-request `httpx.AsyncClient`** — Each API call creates and closes its own client. This avoids connection pool state issues in long-running MCP server processes at the cost of connection reuse. A shared client with connection pooling would be a straightforward improvement.

---

## 9. Setup Instructions

### Prerequisites

- Python 3.11+
- A running OpenMetadata instance (local or cloud)
- Gemini API key (required for `classify_table` and `compliance_report`) — get one free at [aistudio.google.com](https://aistudio.google.com)

### 1. Install

```bash
cd dataguardian
pip install -e .
```

Or install dependencies directly:

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

```env
# OpenMetadata connection
OPENMETADATA_HOST=http://localhost:8585
OPENMETADATA_JWT_TOKEN=your-jwt-token-here

# LLM for auto-classification and compliance reports
OPENAI_API_KEY=your-openai-key-here
OPENAI_MODEL=gpt-4o-mini

# Optional: max lineage traversal depth (default: 5)
LINEAGE_MAX_DEPTH=5
```

To get your OpenMetadata JWT token: Settings → Bots → Ingestion Bot → copy the token.

### 3. Run the MCP server

```bash
fastmcp run dataguardian/server.py
```

Or using the installed entrypoint:

```bash
dataguardian
```

### 4. Connect to your MCP client

Copy `mcp.json` to your MCP client's config location and update the environment values.

For Claude Desktop, add to `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows).

For Kiro, add to `.kiro/settings/mcp.json` in your workspace.

---

## 10. API Reference

The diagram below shows which OpenMetadata endpoints each tool calls.

```mermaid
graph LR
    subgraph Tools
        SS["search_sensitive"]
        BI["breach_impact"]
        CT["classify_table"]
        CR["compliance_report"]
        OS["orphaned_sensitive_assets"]
        AC["data_access_chain"]
    end

    subgraph OM_APIs["OpenMetadata REST API"]
        SEARCH["/search/query"]
        LINEAGE["/lineage/{type}/{id}"]
        TABLES_GET["/tables/name/{fqn}"]
        TABLES_PATCH["/tables/{id} PATCH"]
        QUALITY["/dataQuality/testSuites"]
        USERS["/users/name/{name}"]
        TEAMS["/teams/name/{name}"]
        DOMAINS["/domains"]
    end

    subgraph LLM_API["OpenAI API"]
        CHAT["chat.completions"]
    end

    SS --> SEARCH
    BI --> LINEAGE
    CT --> TABLES_GET
    CT --> TABLES_PATCH
    CT --> CHAT
    CR --> SEARCH
    CR --> DOMAINS
    CR --> CHAT
    OS --> SEARCH
    OS --> TABLES_GET
    OS --> QUALITY
    OS --> LINEAGE
    AC --> TABLES_GET
    AC --> LINEAGE
    AC --> USERS
    AC --> TEAMS
```

### `search_sensitive`

Search for data assets tagged with a sensitivity label.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tag` | `str` | `"PII"` | Tag to search for: PII, GDPR, HIPAA, PHI, Sensitive, Confidential |
| `entity_type` | `str` | `"all"` | Filter by type: table, dashboard, pipeline, topic, mlmodel, or all |
| `limit` | `int` | `50` | Maximum results to return |

Returns: `{ tag_searched, total_found, assets_by_type }`

---

### `breach_impact`

Traverse the lineage graph from a given asset to find the full blast radius.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fqn` | `str` | required | Fully qualified asset name (e.g. `mysql_prod.analytics.public.users`) |
| `direction` | `str` | `"downstream"` | `downstream` (what's affected) or `upstream` (data sources) |
| `depth` | `int` | `5` | Lineage hops to traverse |

Returns: `{ breached_asset, total_affected, owners_to_notify, affected_by_type, nodes, edges }`

---

### `classify_table`

Auto-classify a table's columns for PII using LLM, then write tags to OpenMetadata.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `table_fqn` | `str` | required | Fully qualified table name |
| `dry_run` | `bool` | `False` | Preview tags without writing to OpenMetadata |

Returns: `{ table, dry_run, columns_analyzed, sensitive_columns_found, tags_applied, written_to_openmetadata }`

---

### `compliance_report`

Generate a compliance inventory report for a given regulation.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `regulation` | `str` | `"GDPR"` | GDPR, HIPAA, CCPA, or SOC2 |
| `domain` | `str \| None` | `None` | Scope report to an OpenMetadata domain |
| `output_format` | `str` | `"markdown"` | `markdown` or `json` |

Returns: `{ regulation, total_sensitive_assets, orphaned_assets_count, asset_inventory, report }`

---

### `orphaned_sensitive_assets`

Find sensitive assets with no owner, no quality tests, or no lineage.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `check_quality` | `bool` | `True` | Flag assets with no data quality test suites |
| `check_lineage` | `bool` | `True` | Flag assets with no lineage connections |

Returns: `{ total_sensitive_assets_scanned, critical_risk_count, high_risk_count, critical_assets, high_risk_assets, all_assets_by_risk }`

---

### `data_access_chain`

Get the complete ownership and access chain for a sensitive table.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `table_fqn` | `str` | required | Fully qualified table name |

Returns: `{ table, direct_owner, owner_details, followers, domain, downstream_owners, notification_list }`

---

### OpenMetadata APIs Used

| Endpoint | Used by |
|----------|---------|
| `GET /api/v1/search/query` | search_sensitive, compliance_report, orphan_finder |
| `GET /api/v1/lineage/{type}/{id}` | breach_impact, access_chain |
| `GET /api/v1/tables/name/{fqn}` | classify_table, access_chain, orphan_finder |
| `PATCH /api/v1/tables/{id}` | classify_table (tag write-back) |
| `GET /api/v1/dataQuality/testSuites` | orphan_finder |
| `GET /api/v1/users/name/{name}` | access_chain |
| `GET /api/v1/teams/name/{name}` | access_chain |
| `GET /api/v1/domains` | compliance_report (domain filter) |

---

## 11. Known Limitations

- **OpenMetadata version compatibility** — Tested against OpenMetadata 1.x REST API. Lineage and tag endpoints may differ on older versions.
- **LLM accuracy on classify_table** — PII detection quality depends on column names and descriptions. Columns with cryptic names (e.g. `col_a`, `field_23`) and no descriptions will have lower confidence. Always review `dry_run` output before enabling automated tagging.
- **Token limits on compliance_report** — The asset list is capped at 50 items before being sent to OpenAI. Large catalogs with hundreds of sensitive assets will produce reports based on a sample.
- **Per-request HTTP clients** — `om_client` creates a new `httpx.AsyncClient` per call. This works fine for typical MCP usage but is not optimal for high-frequency batch operations.
- **No authentication beyond JWT** — Only Bearer token auth is supported. OAuth, mTLS, or API key auth would require changes to `om_client.py`.
- **Lineage graph cycles** — The BFS visited set prevents infinite loops, but very large or densely connected lineage graphs may hit the depth cap before full traversal.
- **Single OpenMetadata instance** — The client is initialized once at startup from environment variables. Multi-tenant or multi-instance setups are not supported.

---

## 12. What I'd Improve With More Time

- **Shared HTTP connection pool** — Replace per-request `httpx.AsyncClient` instances with a single shared client using connection pooling. This would meaningfully reduce latency for tools like `orphan_finder` that make many sequential API calls.

- **Streaming compliance reports** — Large compliance reports currently block until the full LLM response is ready. Streaming the response back through the MCP tool would improve perceived responsiveness.

- **Configurable tag taxonomy** — `TAG_MAP` in `auto_classify.py` and `REGULATION_TAGS` in `compliance_report.py` are hardcoded. Externalizing these to a config file or OpenMetadata custom properties would make DataGuardian adaptable to any organization's tag structure without code changes.

- **Retry and circuit breaker on `om_client`** — Currently any API failure raises immediately. Adding exponential backoff retries and a circuit breaker would make the server more resilient to transient OpenMetadata outages.

- **Parallel fan-out in `orphan_finder`** — Quality and lineage checks for each asset are currently sequential. Running them concurrently with `asyncio.gather` would dramatically reduce scan time for large catalogs.

- **Caching for lineage and ownership** — Lineage graphs and team memberships change infrequently. A short TTL cache (e.g. 5 minutes) on these calls would reduce API load significantly during repeated queries.

- **Test suite** — Unit tests for the BFS traversal logic, risk scoring, and tag patch construction. Integration tests against a local OpenMetadata sandbox.

- **Support for more entity types in breach_impact** — Currently resolves FQNs as tables, dashboards, pipelines, topics, and ML models. Stored procedures and data products are not yet handled.
