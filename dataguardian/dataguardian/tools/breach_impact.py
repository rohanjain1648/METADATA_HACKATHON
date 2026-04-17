"""
Tool: get_breach_impact_graph
Given a table or column FQN, traverses the OpenMetadata lineage graph downstream
to build a full blast-radius report: every affected asset, its owner, and its type.
"""

import os
from collections import deque
from dataguardian import om_client


async def get_breach_impact_graph(
    fqn: str,
    direction: str = "downstream",
    depth: int | None = None,
) -> dict:
    """
    Traverse lineage from a given asset FQN and return the full impact graph.

    Args:
        fqn: Fully qualified name of the breached table/column (e.g. mysql.prod.payments.users).
        direction: 'downstream' (what's affected) or 'upstream' (data sources).
        depth: How many hops to traverse. Defaults to LINEAGE_MAX_DEPTH env var (5).

    Returns:
        Impact graph with all affected nodes, their owners, and edge relationships.
    """
    max_depth = depth or int(os.environ.get("LINEAGE_MAX_DEPTH", 5))

    # Resolve entity ID from FQN
    entity = await _resolve_entity(fqn)
    if not entity:
        return {"error": f"Could not resolve entity for FQN: {fqn}"}

    entity_id = entity["id"]
    entity_type = entity["entityType"]

    visited: set[str] = set()
    nodes: list[dict] = []
    edges: list[dict] = []

    queue: deque[tuple[str, str, int]] = deque([(entity_id, entity_type, 0)])

    while queue:
        current_id, current_type, current_depth = queue.popleft()
        if current_id in visited or current_depth > max_depth:
            continue
        visited.add(current_id)

        lineage = await om_client.get(
            f"/lineage/{current_type}/{current_id}",
            params={"upstreamDepth": 0 if direction == "downstream" else 1,
                    "downstreamDepth": 1 if direction == "downstream" else 0},
        )

        entity_node = lineage.get("entity", {})
        nodes.append(_format_node(entity_node))

        relations = lineage.get("nodes", [])
        downstream_edges = lineage.get("downstreamEdges" if direction == "downstream" else "upstreamEdges", [])

        for edge in downstream_edges:
            to_id = edge.get("toEntity") if direction == "downstream" else edge.get("fromEntity")
            from_id = edge.get("fromEntity") if direction == "downstream" else edge.get("toEntity")
            edges.append({"from": from_id, "to": to_id})

        for node in relations:
            node_id = node.get("id")
            node_type = node.get("type", "table")
            if node_id and node_id not in visited:
                queue.append((node_id, node_type, current_depth + 1))

    # Deduplicate nodes
    seen_ids: set[str] = set()
    unique_nodes = []
    for n in nodes:
        if n["id"] not in seen_ids:
            seen_ids.add(n["id"])
            unique_nodes.append(n)

    # Group by entity type for summary
    by_type: dict[str, list] = {}
    for n in unique_nodes:
        by_type.setdefault(n["type"], []).append(n["name"])

    owners_to_notify = list({
        n["owner"] for n in unique_nodes if n["owner"]
    })

    return {
        "breached_asset": fqn,
        "direction": direction,
        "total_affected": len(unique_nodes) - 1,  # exclude root
        "owners_to_notify": owners_to_notify,
        "affected_by_type": by_type,
        "nodes": unique_nodes,
        "edges": edges,
    }


async def _resolve_entity(fqn: str) -> dict | None:
    """Try to resolve FQN as a table first, then other types."""
    for entity_type in ["tables", "dashboards", "pipelines", "topics", "mlmodels"]:
        try:
            data = await om_client.get(
                f"/{entity_type}/name/{fqn}",
                params={"fields": "id,name,entityType,owner,fullyQualifiedName"},
            )
            return {
                "id": data["id"],
                "entityType": entity_type.rstrip("s"),  # tables -> table
                "name": data.get("name"),
                "fqn": data.get("fullyQualifiedName"),
            }
        except Exception:
            continue
    return None


def _format_node(node: dict) -> dict:
    owner = node.get("owner")
    return {
        "id": node.get("id", ""),
        "name": node.get("name", ""),
        "fqn": node.get("fullyQualifiedName", ""),
        "type": node.get("type", "unknown"),
        "owner": owner.get("name") if isinstance(owner, dict) else None,
        "description": node.get("description", ""),
    }
