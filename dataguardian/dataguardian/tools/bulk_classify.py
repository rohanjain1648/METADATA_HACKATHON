"""
Tool: bulk_classify_tables
Runs auto_classify_table across all sensitive tables that have no existing
PII or PHI column-level tags, bootstrapping governance in one shot.
"""

from dataguardian import om_client
from dataguardian.tools.search_sensitive import search_sensitive_assets, DEFAULT_SENSITIVE_TAGS
from dataguardian.tools.auto_classify import auto_classify_table


def _has_pii_or_phi_tags(columns: list[dict]) -> bool:
    """Return True if any column already carries a PII.* or PHI.* tag."""
    for col in columns:
        for tag in col.get("tags", []):
            fqn = tag.get("tagFQN", "")
            if fqn.startswith("PII.") or fqn.startswith("PHI."):
                return True
    return False


async def bulk_classify_tables(
    dry_run: bool = False,
    limit: int = 100,
) -> dict:
    """
    Auto-classify all sensitive tables that have no existing PII/PHI column tags.

    Searches for sensitive assets using the default tag set, filters to tables
    with no existing PII or PHI column-level tags, then runs classify_table on
    each one. Per-table errors are captured and do not abort the batch.

    Args:
        dry_run: If True, shows what would be tagged without writing to OpenMetadata.
        limit: Maximum number of unclassified tables to process (default 100).

    Returns:
        Summary dict with per-table results and aggregate counts.
    """
    # 1. Collect all sensitive tables across all default tags
    all_tables: list[dict] = []
    seen_fqns: set[str] = set()

    for tag in DEFAULT_SENSITIVE_TAGS:
        result = await search_sensitive_assets(tag=tag, entity_type="table", limit=200)
        for assets in result.get("assets_by_type", {}).values():
            for asset in assets:
                fqn = asset.get("fqn", "")
                if fqn and fqn not in seen_fqns:
                    seen_fqns.add(fqn)
                    all_tables.append(asset)

    total_scanned = len(all_tables)

    # 2. Filter to unclassified tables (no existing PII.* or PHI.* column tags)
    unclassified: list[str] = []
    for asset in all_tables:
        fqn = asset.get("fqn", "")
        if not fqn:
            continue
        try:
            table = await om_client.get(
                f"/tables/name/{fqn}",
                params={"fields": "columns"},
            )
            columns = table.get("columns", [])
            if not _has_pii_or_phi_tags(columns):
                unclassified.append(fqn)
        except Exception:
            # If we can't fetch the schema, skip conservatively
            continue

    # 3. Apply limit cap
    unclassified = unclassified[:limit]
    total_unclassified = len(unclassified)

    # 4. Classify each unclassified table
    per_table: list[dict] = []
    errors: list[dict] = []

    for fqn in unclassified:
        try:
            result = await auto_classify_table(table_fqn=fqn, dry_run=dry_run)
            per_table.append(result)
        except Exception as exc:
            errors.append({"table": fqn, "error": str(exc)})

    # 5. Build summary
    total_classified = sum(
        1 for r in per_table if r.get("sensitive_columns_found", 0) > 0
    )
    total_sensitive_columns = sum(
        r.get("sensitive_columns_found", 0) for r in per_table
    )

    return {
        "dry_run": dry_run,
        "total_tables_scanned": total_scanned,
        "total_unclassified": total_unclassified,
        "total_classified": total_classified,
        "total_sensitive_columns_found": total_sensitive_columns,
        "errors": errors,
        "per_table": per_table,
    }
