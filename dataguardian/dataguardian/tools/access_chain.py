"""
Tool: get_data_access_chain
For a given sensitive table, returns who has access to it and all downstream assets.
Combines OpenMetadata ownership, teams, and lineage to build a full access picture.
"""

from dataguardian import om_client
from dataguardian.tools.breach_impact import get_breach_impact_graph


async def get_data_access_chain(table_fqn: str) -> dict:
    """
    Build a complete access chain for a sensitive table:
    who owns it, which teams have access, and who owns downstream assets.

    Args:
        table_fqn: Fully qualified name of the table.

    Returns:
        Full access chain with owners, teams, and downstream stakeholders.
    """
    # 1. Fetch table details with policies and owner
    table = await om_client.get(
        f"/tables/name/{table_fqn}",
        params={"fields": "owner,followers,tags,domain,dataProducts,fullyQualifiedName"},
    )

    direct_owner = table.get("owner")
    followers = table.get("followers", [])
    domain = table.get("domain", {})
    data_products = table.get("dataProducts", [])

    # 2. Resolve owner's team membership
    owner_details = None
    if direct_owner:
        owner_details = await _get_user_or_team(direct_owner)

    # 3. Get downstream impact graph to find all downstream owners
    impact = await get_breach_impact_graph(fqn=table_fqn, direction="downstream", depth=3)
    downstream_nodes = impact.get("nodes", [])
    downstream_owners = list({n["owner"] for n in downstream_nodes if n.get("owner")})

    # 4. Resolve each downstream owner's details
    downstream_owner_details = []
    for owner_name in downstream_owners:
        details = await _get_user_or_team_by_name(owner_name)
        if details:
            downstream_owner_details.append(details)

    return {
        "table": table_fqn,
        "direct_owner": _format_principal(direct_owner),
        "owner_details": owner_details,
        "followers": [_format_principal(f) for f in followers],
        "domain": domain.get("name") if domain else None,
        "data_products": [dp.get("name") for dp in data_products],
        "downstream_asset_count": impact.get("total_affected", 0),
        "downstream_owners": downstream_owners,
        "downstream_owner_details": downstream_owner_details,
        "notification_list": list({
            *([direct_owner.get("name")] if direct_owner else []),
            *downstream_owners,
        }),
    }


async def _get_user_or_team(principal: dict) -> dict | None:
    """Fetch user or team details from OpenMetadata."""
    if not principal:
        return None
    ptype = principal.get("type", "user")
    name = principal.get("name")
    if not name:
        return None
    try:
        endpoint = "users" if ptype == "user" else "teams"
        data = await om_client.get(
            f"/{endpoint}/name/{name}",
            params={"fields": "email,teams,roles,profile"},
        )
        return {
            "name": data.get("name"),
            "display_name": data.get("displayName"),
            "email": data.get("email"),
            "type": ptype,
            "teams": [t.get("name") for t in data.get("teams", [])],
        }
    except Exception:
        return {"name": name, "type": ptype}


async def _get_user_or_team_by_name(name: str) -> dict | None:
    """Try to resolve a name as user first, then team."""
    for endpoint in ["users", "teams"]:
        try:
            data = await om_client.get(
                f"/{endpoint}/name/{name}",
                params={"fields": "email,teams"},
            )
            return {
                "name": data.get("name"),
                "email": data.get("email"),
                "type": "user" if endpoint == "users" else "team",
            }
        except Exception:
            continue
    return None


def _format_principal(p: dict | None) -> dict | None:
    if not p:
        return None
    return {"name": p.get("name"), "type": p.get("type", "user")}
