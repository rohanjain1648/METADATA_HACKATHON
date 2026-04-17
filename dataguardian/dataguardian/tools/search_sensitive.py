"""
Tool: search_sensitive_assets
Finds all data assets tagged with a given sensitivity label (PII, GDPR, HIPAA, etc.)
across tables, dashboards, topics, pipelines, and ML models.
"""

from dataguardian import om_client

# Sensitivity tags that DataGuardian recognizes by default
DEFAULT_SENSITIVE_TAGS = ["PII", "Sensitive", "GDPR", "HIPAA", "Confidential", "PHI"]

# OpenMetadata entity index names
ENTITY_TYPES = [
    "table",
    "dashboard",
    "topic",
    "pipeline",
    "mlmodel",
    "storedProcedure",
]


async def search_sensitive_assets(
    tag: str = "PII",
    entity_type: str = "all",
    limit: int = 50,
) -> dict:
    """
    Search OpenMetadata for assets tagged with a sensitivity label.

    Args:
        tag: The tag/classification to search for (e.g. PII, GDPR, HIPAA).
        entity_type: Filter by entity type or 'all'.
        limit: Max results to return.

    Returns:
        Dict with matched assets grouped by entity type, including owner and FQN.
    """
    index = "all" if entity_type == "all" else f"{entity_type}_search_index"

    params = {
        "q": f"tags.tagFQN:{tag}",
        "index": index,
        "from": 0,
        "size": limit,
        "include_source_fields": "name,fullyQualifiedName,entityType,owner,tags,description,tier",
    }

    data = await om_client.get("/search/query", params=params)
    hits = data.get("hits", {}).get("hits", [])

    results: dict[str, list] = {}
    for hit in hits:
        src = hit.get("_source", {})
        etype = src.get("entityType", "unknown")
        results.setdefault(etype, []).append({
            "name": src.get("name"),
            "fqn": src.get("fullyQualifiedName"),
            "description": src.get("description", ""),
            "owner": _extract_owner(src.get("owner")),
            "tags": [t.get("tagFQN") for t in src.get("tags", [])],
            "tier": src.get("tier", {}).get("tagFQN") if src.get("tier") else None,
        })

    return {
        "tag_searched": tag,
        "total_found": len(hits),
        "assets_by_type": results,
    }


def _extract_owner(owner: dict | None) -> str | None:
    if not owner:
        return None
    return owner.get("name") or owner.get("displayName")
