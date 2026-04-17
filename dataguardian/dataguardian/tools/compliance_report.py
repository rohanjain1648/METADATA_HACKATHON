"""
Tool: generate_compliance_report
Aggregates data from Tags, Lineage, Governance, and Teams APIs to produce
a structured compliance inventory (GDPR Article 30, HIPAA, CCPA).
"""

import json
from dataguardian import om_client
from dataguardian.llm_client import get_client, get_model
from dataguardian.tools.search_sensitive import search_sensitive_assets

REGULATION_TAGS = {
    "GDPR": ["PII", "GDPR", "Sensitive"],
    "HIPAA": ["PHI", "HIPAA", "HealthData"],
    "CCPA": ["PII", "CCPA", "Sensitive"],
    "SOC2": ["Sensitive", "Confidential"],
}

REPORT_PROMPT = """You are a compliance officer. Based on the following data asset inventory, 
generate a formal {regulation} compliance report.

Data Assets:
{assets_json}

Generate a structured report with:
1. Executive Summary
2. Data Processing Activities (Article 30 style for GDPR)
3. Data Categories Found
4. Risk Assessment (High/Medium/Low for each asset)
5. Recommended Actions
6. Assets with No Owner (highest risk)

Format as clean markdown. Be specific and actionable.
"""


async def generate_compliance_report(
    regulation: str = "GDPR",
    domain: str | None = None,
    output_format: str = "markdown",
) -> dict:
    """
    Generate a compliance report for a given regulation by querying OpenMetadata.

    Args:
        regulation: GDPR | HIPAA | CCPA | SOC2
        domain: Optional OpenMetadata domain to scope the report.
        output_format: 'markdown' or 'json'

    Returns:
        Full compliance report with asset inventory and risk assessment.
    """
    regulation = regulation.upper()
    tags = REGULATION_TAGS.get(regulation, ["PII", "Sensitive"])

    # 1. Collect all sensitive assets for this regulation
    all_assets = []
    for tag in tags:
        result = await search_sensitive_assets(tag=tag, limit=100)
        for etype, assets in result.get("assets_by_type", {}).items():
            for asset in assets:
                asset["entity_type"] = etype
                asset["matched_tag"] = tag
                all_assets.append(asset)

    # Deduplicate by FQN
    seen: set[str] = set()
    unique_assets = []
    for a in all_assets:
        fqn = a.get("fqn", "")
        if fqn not in seen:
            seen.add(fqn)
            unique_assets.append(a)

    # 2. Filter by domain if specified
    if domain:
        domain_assets = await _get_domain_assets(domain)
        domain_fqns = {a.get("fullyQualifiedName") for a in domain_assets}
        unique_assets = [a for a in unique_assets if a.get("fqn") in domain_fqns]

    # 3. Identify orphaned assets (no owner)
    orphaned = [a for a in unique_assets if not a.get("owner")]

    # 4. Generate narrative report via LLM
    client = get_client()
    response = await client.chat.completions.create(
        model=get_model(),
        messages=[{
            "role": "user",
            "content": REPORT_PROMPT.format(
                regulation=regulation,
                assets_json=json.dumps(unique_assets[:50], indent=2),  # cap for token limit
            ),
        }],
        temperature=0.2,
    )

    report_text = response.choices[0].message.content.strip()

    result = {
        "regulation": regulation,
        "domain_filter": domain,
        "total_sensitive_assets": len(unique_assets),
        "orphaned_assets_count": len(orphaned),
        "orphaned_assets": [a["fqn"] for a in orphaned],
        "asset_inventory": unique_assets,
        "report": report_text,
    }

    if output_format == "json":
        return result

    # Return markdown-friendly structure
    return result


async def _get_domain_assets(domain: str) -> list[dict]:
    """Fetch assets belonging to a specific OpenMetadata domain."""
    try:
        data = await om_client.get(
            "/search/query",
            params={"q": f"domain.name:{domain}", "index": "all", "size": 200},
        )
        hits = data.get("hits", {}).get("hits", [])
        return [h.get("_source", {}) for h in hits]
    except Exception:
        return []
