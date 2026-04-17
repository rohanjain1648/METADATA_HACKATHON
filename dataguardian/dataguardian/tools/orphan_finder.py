"""
Tool: find_orphaned_sensitive_assets
Finds sensitive/PII assets that have NO owner, NO data quality tests,
and/or NO lineage — the highest-risk assets in any organization.
"""

from dataguardian import om_client
from dataguardian.tools.search_sensitive import search_sensitive_assets, DEFAULT_SENSITIVE_TAGS


async def find_orphaned_sensitive_assets(
    check_quality: bool = True,
    check_lineage: bool = True,
) -> dict:
    """
    Find sensitive assets that are ungoverned (no owner, no tests, no lineage).

    Args:
        check_quality: Also flag assets with no data quality tests.
        check_lineage: Also flag assets with no lineage connections.

    Returns:
        Categorized list of at-risk assets with risk scores.
    """
    # 1. Gather all sensitive assets across all default tags
    all_assets: list[dict] = []
    for tag in DEFAULT_SENSITIVE_TAGS:
        result = await search_sensitive_assets(tag=tag, entity_type="table", limit=100)
        for etype, assets in result.get("assets_by_type", {}).items():
            for asset in assets:
                asset["entity_type"] = etype
                all_assets.append(asset)

    # Deduplicate
    seen: set[str] = set()
    unique: list[dict] = []
    for a in all_assets:
        fqn = a.get("fqn", "")
        if fqn not in seen:
            seen.add(fqn)
            unique.append(a)

    # 2. Score each asset for risk
    risk_assets = []
    for asset in unique:
        risk_flags = []
        risk_score = 0

        if not asset.get("owner"):
            risk_flags.append("NO_OWNER")
            risk_score += 40

        if not asset.get("description"):
            risk_flags.append("NO_DESCRIPTION")
            risk_score += 10

        if not asset.get("tier"):
            risk_flags.append("NO_TIER")
            risk_score += 10

        fqn = asset.get("fqn", "")

        if check_quality and fqn:
            has_tests = await _has_quality_tests(fqn)
            if not has_tests:
                risk_flags.append("NO_QUALITY_TESTS")
                risk_score += 25

        if check_lineage and fqn:
            has_lineage = await _has_lineage(fqn)
            if not has_lineage:
                risk_flags.append("NO_LINEAGE")
                risk_score += 15

        risk_level = (
            "CRITICAL" if risk_score >= 65
            else "HIGH" if risk_score >= 40
            else "MEDIUM" if risk_score >= 20
            else "LOW"
        )

        risk_assets.append({
            **asset,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "risk_flags": risk_flags,
        })

    # Sort by risk score descending
    risk_assets.sort(key=lambda x: x["risk_score"], reverse=True)

    critical = [a for a in risk_assets if a["risk_level"] == "CRITICAL"]
    high = [a for a in risk_assets if a["risk_level"] == "HIGH"]

    return {
        "total_sensitive_assets_scanned": len(unique),
        "critical_risk_count": len(critical),
        "high_risk_count": len(high),
        "summary": f"{len(critical)} CRITICAL and {len(high)} HIGH risk ungoverned sensitive assets found.",
        "critical_assets": critical,
        "high_risk_assets": high,
        "all_assets_by_risk": risk_assets,
    }


async def _has_quality_tests(table_fqn: str) -> bool:
    """Check if a table has any data quality test suites."""
    try:
        data = await om_client.get(
            "/dataQuality/testSuites",
            params={"entityFQN": table_fqn, "limit": 1},
        )
        return len(data.get("data", [])) > 0
    except Exception:
        return False


async def _has_lineage(table_fqn: str) -> bool:
    """Check if a table has any lineage edges."""
    try:
        # Resolve table ID first
        table = await om_client.get(
            f"/tables/name/{table_fqn}",
            params={"fields": "id"},
        )
        table_id = table["id"]
        lineage = await om_client.get(
            f"/lineage/table/{table_id}",
            params={"upstreamDepth": 1, "downstreamDepth": 1},
        )
        edges = lineage.get("upstreamEdges", []) + lineage.get("downstreamEdges", [])
        return len(edges) > 0
    except Exception:
        return False
