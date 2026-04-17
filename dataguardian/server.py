"""
DataGuardian MCP Server
AI-Powered Compliance & Breach Impact Agent for OpenMetadata

Run: python server.py
"""

import os
import json
from dotenv import load_dotenv

load_dotenv()

from fastmcp import FastMCP
import om_client as om
from classifier import classify_columns, generate_compliance_summary

mcp = FastMCP(
    name="DataGuardian",
    instructions=(
        "DataGuardian is a compliance and data governance agent for OpenMetadata. "
        "Use it to find sensitive/PII data, analyze breach blast radius via lineage, "
        "auto-classify tables, generate GDPR/HIPAA reports, and find orphaned sensitive assets."
    ),
)


# ---------------------------------------------------------------------------
# Tool 1: Search Sensitive Assets
# ---------------------------------------------------------------------------
@mcp.tool
async def search_sensitive_assets(
    tag: str = "PII",
    entity_type: str = "",
    limit: int = 20,
) -> str:
    