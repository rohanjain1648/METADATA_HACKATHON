# DataGuardian 🛡️

> AI-powered Compliance & Breach Impact Agent for OpenMetadata

DataGuardian is an MCP server that turns OpenMetadata into an always-on compliance analyst.
Ask natural language questions about your sensitive data — it answers using OpenMetadata's
Search, Lineage, Tags, Governance, Teams, and Data Quality APIs.

## The Problem

When a data breach or compliance audit hits, answering "what's affected and who owns it?"
takes days of manual cross-referencing. DataGuardian answers in seconds.

## What It Does

| Tool | What it answers |
|------|----------------|
| `search_sensitive` | Which assets are tagged PII / GDPR / HIPAA? |
| `breach_impact` | If this table is breached, what's the blast radius? |
| `classify_table` | Auto-detect PII columns and tag them in OpenMetadata |
| `compliance_report` | Generate a GDPR Article 30 / HIPAA inventory |
| `orphaned_sensitive_assets` | Which sensitive assets have no owner or tests? |
| `data_access_chain` | Who has access to this table and all downstream assets? |

## Quick Start

### 1. Install

```bash
cd dataguardian
pip install -e .
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your OpenMetadata host, JWT token, and OpenAI key
```

### 3. Run the MCP server

```bash
fastmcp run dataguardian/server.py
```

### 4. Connect to Claude Desktop or Kiro

Copy `mcp.json` to your MCP config location and update the env values.

---

## Example Queries

Once connected to any MCP client (Claude Desktop, Kiro, Cursor):

```
"Which tables contain PII data?"

"If payments.transactions was breached, what's the blast radius?"

"Auto-classify the users table and tag any PII columns"

"Generate a GDPR compliance report for our analytics domain"

"Show me all sensitive assets with no owner — our highest risk data"

"Who do I need to notify if the customers table is compromised?"
```

---

## Architecture

```
MCP Client (Claude / Kiro / Cursor)
        │
        ▼
  DataGuardian MCP Server (FastMCP)
        │
        ├── search_sensitive      → OpenMetadata Search API
        ├── breach_impact         → OpenMetadata Lineage API
        ├── classify_table        → Tables API + LLM + Tags PATCH
        ├── compliance_report     → Search + Governance + LLM
        ├── orphaned_sensitive    → Search + Quality + Lineage APIs
        └── data_access_chain     → Lineage + Teams + Users APIs
        │
        ▼
  OpenMetadata REST API
```

## OpenMetadata APIs Used

- `/api/v1/search/query` — asset discovery by tag
- `/api/v1/lineage/{type}/{id}` — upstream/downstream traversal
- `/api/v1/tables/name/{fqn}` — schema and column metadata
- `/api/v1/tables/{id}` PATCH — write tags back (auto-classification)
- `/api/v1/dataQuality/testSuites` — quality test coverage
- `/api/v1/users` and `/api/v1/teams` — ownership and access
- `/api/v1/domains` — domain-scoped governance

## Requirements

- Python 3.11+
- OpenMetadata instance (local or cloud)
- OpenAI API key (for `classify_table` and `compliance_report`)
