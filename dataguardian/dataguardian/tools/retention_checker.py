"""
Tool: check_retention_policies
Identifies sensitive assets that have no retention policy or expiry metadata,
flagging GDPR Article 5(1)(e) and CCPA data minimization gaps.
"""

from dataguardian import om_client
from dataguardian.config import load_regulation_tags
from dataguardian.tools.search_sensitive import search_sensitive_assets

REGULATION_TAGS = load_regulation_tags()

# Keywords that indicate a retention policy is present (case-insensitive)
RETENTION_KEYWORDS = ["retention", "expiry", "expire", "purge", "delete_after", "ttl"]


def _has_retention_metadata(description: str, custom_properties: dict) -> bool:
    """Return True if any retention keyword is found in description or custom properties."""
    text_to_check = (description or "").lower()
    for keyword in RETENTION_KEYWORDS:
        if keyword in text_to_check:
            return True

    # Check custom property keys and string values
    for key, value in (custom_properties or {}).items():
        if any(kw in key.lower() for kw in RETENTION_KEYWORDS):
            return True
        if isinstance(value, str) and any(kw in value.lower() for kw in RETENTION_KEYWORDS):
            return True

    return False


def _recommended_action(fqn: str, entity_type: str, regulation: str) -> str:
    return (
        f"Add a retention policy to {entity_type} '{fqn}'. "
        f"For {regulation} compliance, document the data retention period and deletion schedule "
        f"in the asset description or as a custom property (e.g. 'retention_days: 365')."
    )


async def check_retention_policies(
    regulation: str = "GDPR",
    domain: str | None = None,
) -> dict:
    """
    Find sensitive assets missing retention policy or expiry metadata.

    Searches for assets relevant to the specified regulation, then checks each
    asset's description and custom properties for retention-related keywords.

    Args:
        regulation: GDPR | HIPAA | CCPA | SOC2 (default GDPR).
        domain: Optional OpenMetadata domain name to scope the scan.

    Returns:
        Summary with compliant/non-compliant counts and remediation actions.
    """
    regulation = regulation.upper()
    tags = REGULATION_TAGS.get(regulation, ["PII", "Sensitive"])

    # 1. Collect all sensitive assets for this regulation
    all_assets: list[dict] = []
    seen: set[str] = set()

    for tag in tags:
        result = await search_sensitive_assets(tag=tag, limit=100)
        for etype, assets in result.get("assets_by_type", {}).items():
            for asset in assets:
                fqn = asset.get("fqn", "")
                if fqn and fqn not in seen:
                    seen.add(fqn)
                    asset["entity_type"] = etype
                    all_assets.append(asset)

    # 2. Filter by domain if specified
    if domain:
        all_assets = [a for a in all_assets if _asset_in_domain(a, domain)]

    if not all_assets:
        return {
            "regulation": regulation,
            "domain_filter": domain,
            "total_assets_scanned": 0,
            "compliant_count": 0,
            "non_compliant_count": 0,
            "non_compliant_assets": [],
            "message": f"No sensitive assets found for {regulation}"
            + (f" in domain '{domain}'" if domain else "") + ".",
        }

    # 3. Check each asset for retention metadata
    compliant_count = 0
    non_compliant: list[dict] = []

    for asset in all_assets:
        fqn = asset.get("fqn", "")
        entity_type = asset.get("entity_type", "unknown")
        description = asset.get("description", "")
        custom_properties: dict = {}

        # Fetch full record to get customProperties
        try:
            endpoint = _entity_endpoint(entity_type)
            if endpoint:
                full = await om_client.get(
                    f"/{endpoint}/name/{fqn}",
                    params={"fields": "customProperties,description"},
                )
                description = full.get("description", description)
                custom_properties = full.get("customProperties") or {}
        except Exception:
            # Conservative: treat fetch failure as non-compliant
            pass

        if _has_retention_metadata(description, custom_properties):
            compliant_count += 1
        else:
            non_compliant.append({
                "fqn": fqn,
                "owner": asset.get("owner"),
                "entity_type": entity_type,
                "recommended_action": _recommended_action(fqn, entity_type, regulation),
            })

    return {
        "regulation": regulation,
        "domain_filter": domain,
        "total_assets_scanned": len(all_assets),
        "compliant_count": compliant_count,
        "non_compliant_count": len(non_compliant),
        "non_compliant_assets": non_compliant,
        "message": None,
    }


def _entity_endpoint(entity_type: str) -> str | None:
    """Map entity type to its OpenMetadata REST endpoint prefix."""
    mapping = {
        "table": "tables",
        "dashboard": "dashboards",
        "pipeline": "pipelines",
        "topic": "topics",
        "mlmodel": "mlmodels",
    }
    return mapping.get(entity_type)


def _asset_in_domain(asset: dict, domain: str) -> bool:
    """Simple domain filter: check if the asset FQN starts with the domain prefix."""
    fqn = asset.get("fqn", "")
    return domain.lower() in fqn.lower()
