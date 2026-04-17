"""
Tool: detect_pii_linkage
Identifies pairs of tables that share PII column name patterns and could
re-identify individuals when joined — a re-identification risk assessment.
"""

from itertools import combinations

from dataguardian import om_client
from dataguardian.tools.search_sensitive import search_sensitive_assets, DEFAULT_SENSITIVE_TAGS

# Canonical PII column name patterns (case-insensitive substring matching)
PII_COLUMN_PATTERNS = {
    "user_id",
    "email",
    "ssn",
    "phone",
    "name",
    "first_name",
    "last_name",
    "date_of_birth",
    "dob",
    "address",
    "ip_address",
    "credit_card",
    "passport",
    "national_id",
    "tax_id",
}


def _matches_pii_pattern(col_name: str) -> bool:
    """Return True if the column name matches any PII pattern (case-insensitive substring)."""
    lower = col_name.lower()
    return any(pattern in lower for pattern in PII_COLUMN_PATTERNS)


async def detect_pii_linkage(
    domain: str | None = None,
    min_shared_columns: int = 2,
) -> dict:
    """
    Detect pairs of tables that could re-identify individuals when joined.

    Retrieves all sensitive tables, extracts their PII-matching column names,
    then flags pairs sharing at least min_shared_columns PII column patterns.

    Args:
        domain: Optional OpenMetadata domain name to scope the analysis.
        min_shared_columns: Minimum shared PII columns to flag a pair (default 2).

    Returns:
        Summary with flagged pairs sorted by risk level (HIGH before MEDIUM).
    """
    # 1. Collect all sensitive tables
    all_tables: list[dict] = []
    seen_fqns: set[str] = set()

    for tag in DEFAULT_SENSITIVE_TAGS:
        result = await search_sensitive_assets(tag=tag, entity_type="table", limit=200)
        for assets in result.get("assets_by_type", {}).values():
            for asset in assets:
                fqn = asset.get("fqn", "")
                if fqn and fqn not in seen_fqns:
                    if domain is None or domain.lower() in fqn.lower():
                        seen_fqns.add(fqn)
                        all_tables.append(asset)

    if len(all_tables) < 2:
        return {
            "total_tables_analyzed": len(all_tables),
            "total_flagged_pairs": 0,
            "min_shared_columns": min_shared_columns,
            "flagged_pairs": [],
            "skipped_tables": [],
            "message": "Fewer than 2 sensitive tables found — no pairs to analyze.",
        }

    # 2. Fetch PII column names for each table
    table_pii_columns: dict[str, set[str]] = {}  # fqn -> set of matching col names
    table_owners: dict[str, str | None] = {}
    skipped: list[str] = []

    for asset in all_tables:
        fqn = asset.get("fqn", "")
        table_owners[fqn] = asset.get("owner")
        try:
            table = await om_client.get(
                f"/tables/name/{fqn}",
                params={"fields": "columns"},
            )
            columns = table.get("columns", [])
            pii_cols = {
                c["name"].lower()
                for c in columns
                if _matches_pii_pattern(c.get("name", ""))
            }
            table_pii_columns[fqn] = pii_cols
        except Exception:
            skipped.append(fqn)

    # Only consider tables we successfully fetched
    analyzable = [fqn for fqn in seen_fqns if fqn in table_pii_columns]

    # 3. Find flagged pairs
    flagged_pairs: list[dict] = []

    for fqn_a, fqn_b in combinations(analyzable, 2):
        shared = table_pii_columns[fqn_a] & table_pii_columns[fqn_b]
        if len(shared) >= min_shared_columns:
            risk_level = "HIGH" if len(shared) >= 3 else "MEDIUM"
            flagged_pairs.append({
                "table_a": fqn_a,
                "table_b": fqn_b,
                "owner_a": table_owners.get(fqn_a),
                "owner_b": table_owners.get(fqn_b),
                "shared_pii_columns": sorted(shared),
                "shared_count": len(shared),
                "risk_level": risk_level,
            })

    # 4. Sort HIGH before MEDIUM
    flagged_pairs.sort(key=lambda p: (0 if p["risk_level"] == "HIGH" else 1))

    return {
        "total_tables_analyzed": len(analyzable),
        "total_flagged_pairs": len(flagged_pairs),
        "min_shared_columns": min_shared_columns,
        "flagged_pairs": flagged_pairs,
        "skipped_tables": skipped,
        "message": None,
    }
