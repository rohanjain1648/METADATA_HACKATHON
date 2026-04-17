"""
DataGuardian MCP Server
AI-powered Compliance & Breach Impact Agent for OpenMetadata

Run with:
    fastmcp run dataguardian/server.py
Or install and run:
    dataguardian
"""

import atexit
import asyncio
import os
from dotenv import load_dotenv
from fastmcp import FastMCP

load_dotenv()

# Initialize OpenMetadata client before importing tools
from dataguardian import om_client
om_client.init()

from dataguardian.tools.search_sensitive import search_sensitive_assets
from dataguardian.tools.breach_impact import get_breach_impact_graph
from dataguardian.tools.auto_classify import auto_classify_table
from dataguardian.tools.compliance_report import generate_compliance_report
from dataguardian.tools.orphan_finder import find_orphaned_sensitive_assets
from dataguardian.tools.access_chain import get_data_access_chain
from dataguardian.tools.bulk_classify import bulk_classify_tables
from dataguardian.tools.retention_checker import check_retention_policies
from dataguardian.tools.linkage_detector import detect_pii_linkage
from dataguardian.tools.drift_monitor import monitor_tag_drift
from dataguardian.tools.playbook_generator import generate_incident_playbook


def _shutdown():
    """Drain the shared HTTP connection pool on process exit."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(om_client.close())
        else:
            loop.run_until_complete(om_client.close())
    except Exception:
        pass


atexit.register(_shutdown)

mcp = FastMCP(
    name="DataGuardian",
    instructions="""
You are DataGuardian, an AI compliance and data governance agent powered by OpenMetadata.

You help data teams answer critical questions about sensitive data:
- Which assets contain PII, PHI, or other sensitive data?
- If a table is breached, what is the downstream blast radius?
- Who owns sensitive assets and who needs to be notified?
- Which sensitive assets have no owner, no tests, no lineage (highest risk)?
- Generate compliance reports for GDPR, HIPAA, CCPA, SOC2.
- Auto-classify tables for PII and write tags back to OpenMetadata.
- Bulk-classify all unclassified sensitive tables in one shot.
- Check which sensitive assets are missing retention/expiry policies.
- Detect pairs of tables that could re-identify individuals when joined.
- Monitor tag drift — detect when sensitive column tags have been removed.
- Generate a full incident response playbook for a breached asset.

Always be specific, cite asset FQNs, and prioritize actionable recommendations.
""",
)


@mcp.tool()
async def search_sensitive(
    tag: str = "PII",
    entity_type: str = "all",
    limit: int = 50,
) -> dict:
    """
    Search OpenMetadata for data assets tagged with a sensitivity label.

    Use this to find all tables, dashboards, pipelines, or topics that contain
    PII, GDPR, HIPAA, PHI, Confidential, or other sensitive data.

    Args:
        tag: Sensitivity tag to search for. Common values: PII, GDPR, HIPAA, PHI, Sensitive, Confidential.
        entity_type: Filter by type: table, dashboard, pipeline, topic, mlmodel, or 'all'.
        limit: Maximum number of results (default 50).
    """
    return await search_sensitive_assets(tag=tag, entity_type=entity_type, limit=limit)


@mcp.tool()
async def breach_impact(
    fqn: str,
    direction: str = "downstream",
    depth: int = 5,
) -> dict:
    """
    Given a table or asset FQN, traverse the lineage graph to find everything affected.

    Use this when a data asset may be compromised — it returns the full blast radius:
    every downstream table, dashboard, pipeline, ML model, and their owners.

    Args:
        fqn: Fully qualified name of the asset (e.g. mysql_prod.analytics.public.users).
        direction: 'downstream' to see what's affected, 'upstream' to see data sources.
        depth: How many lineage hops to traverse (default 5).
    """
    return await get_breach_impact_graph(fqn=fqn, direction=direction, depth=depth)


@mcp.tool()
async def classify_table(
    table_fqn: str,
    dry_run: bool = False,
) -> dict:
    """
    Auto-classify a table's columns for PII and sensitive data using AI, then tag in OpenMetadata.

    This is the closed-loop governance tool: it reads the schema, uses an LLM to detect
    sensitive columns (email, SSN, phone, DOB, etc.), and writes tags back to OpenMetadata.

    Args:
        table_fqn: Fully qualified name of the table to classify.
        dry_run: If True, shows what would be tagged without writing to OpenMetadata.
    """
    return await auto_classify_table(table_fqn=table_fqn, dry_run=dry_run)


@mcp.tool()
async def compliance_report(
    regulation: str = "GDPR",
    domain: str | None = None,
    output_format: str = "markdown",
) -> dict:
    """
    Generate a compliance inventory report for GDPR, HIPAA, CCPA, or SOC2.

    Aggregates all sensitive assets from OpenMetadata, identifies owners,
    flags ungoverned assets, and produces a structured compliance document.

    Args:
        regulation: GDPR | HIPAA | CCPA | SOC2
        domain: Optional OpenMetadata domain name to scope the report.
        output_format: 'markdown' for human-readable, 'json' for structured data.
    """
    return await generate_compliance_report(
        regulation=regulation,
        domain=domain,
        output_format=output_format,
    )


@mcp.tool()
async def orphaned_sensitive_assets(
    check_quality: bool = True,
    check_lineage: bool = True,
) -> dict:
    """
    Find sensitive/PII assets with no owner, no data quality tests, or no lineage.

    These are the highest-risk assets in your organization — sensitive data that
    nobody is responsible for and nobody is monitoring.

    Args:
        check_quality: Also flag assets with no data quality test suites.
        check_lineage: Also flag assets with no lineage connections.
    """
    return await find_orphaned_sensitive_assets(
        check_quality=check_quality,
        check_lineage=check_lineage,
    )


@mcp.tool()
async def data_access_chain(table_fqn: str) -> dict:
    """
    Get the complete access chain for a sensitive table.

    Returns direct owners, team memberships, followers, downstream asset owners,
    and a ready-to-use notification list for incident response.

    Args:
        table_fqn: Fully qualified name of the table.
    """
    return await get_data_access_chain(table_fqn=table_fqn)


@mcp.tool()
async def bulk_classify(
    dry_run: bool = False,
    limit: int = 100,
) -> dict:
    """
    Auto-classify all sensitive tables that have no existing PII/PHI column tags.

    Searches for sensitive assets, filters to unclassified tables, then runs
    classify_table on each one. Use this to bootstrap PII tagging for a new
    OpenMetadata instance without invoking classify_table individually.

    Args:
        dry_run: If True, shows what would be tagged without writing to OpenMetadata.
        limit: Maximum number of unclassified tables to process (default 100).
    """
    return await bulk_classify_tables(dry_run=dry_run, limit=limit)


@mcp.tool()
async def retention_checker(
    regulation: str = "GDPR",
    domain: str | None = None,
) -> dict:
    """
    Find sensitive assets that have no retention policy or expiry metadata.

    Checks each asset's description and custom properties for retention-related
    keywords. Non-compliant assets are flagged with a recommended remediation action.

    Args:
        regulation: GDPR | HIPAA | CCPA | SOC2 (default GDPR).
        domain: Optional OpenMetadata domain name to scope the scan.
    """
    return await check_retention_policies(regulation=regulation, domain=domain)


@mcp.tool()
async def linkage_detector(
    domain: str | None = None,
    min_shared_columns: int = 2,
) -> dict:
    """
    Detect pairs of tables that could re-identify individuals when joined.

    Identifies tables sharing two or more PII column name patterns (email, ssn,
    user_id, etc.). HIGH risk = 3+ shared columns, MEDIUM = 2 shared columns.

    Args:
        domain: Optional OpenMetadata domain name to scope the analysis.
        min_shared_columns: Minimum shared PII columns to flag a pair (default 2).
    """
    return await detect_pii_linkage(domain=domain, min_shared_columns=min_shared_columns)


@mcp.tool()
async def drift_monitor(
    table_fqn: str,
    snapshot_path: str,
) -> dict:
    """
    Monitor a table for sensitive tag drift — detect removed or added column tags.

    On first run, creates a baseline snapshot. On subsequent runs, compares current
    tags against the snapshot and reports any columns that lost sensitive tags.

    Args:
        table_fqn: Fully qualified name of the table to monitor.
        snapshot_path: File path to save/load the tag snapshot (JSON).
    """
    return await monitor_tag_drift(table_fqn=table_fqn, snapshot_path=snapshot_path)


@mcp.tool()
async def incident_playbook(
    table_fqn: str,
    regulation: str = "GDPR",
    incident_description: str | None = None,
) -> dict:
    """
    Generate a complete incident response playbook for a breached data asset.

    Combines breach impact analysis, access chain resolution, and regulation-specific
    obligations to produce a ready-to-send notification draft.

    Args:
        table_fqn: Fully qualified name of the breached asset.
        regulation: GDPR | HIPAA | CCPA | SOC2 (default GDPR).
        incident_description: Optional context about the incident for the LLM.
    """
    return await generate_incident_playbook(
        table_fqn=table_fqn,
        regulation=regulation,
        incident_description=incident_description,
    )


def main():
    mcp.run()


if __name__ == "__main__":
    main()
