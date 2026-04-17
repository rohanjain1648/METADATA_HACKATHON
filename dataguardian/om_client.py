"""
OpenMetadata REST API client — thin async wrapper over httpx.
All tools in server.py use this instead of the heavy ingestion SDK
so there are zero dependency conflicts with FastMCP.
"""

import os
import httpx
from typing import Any

_HOST = os.getenv("OPENMETADATA_HOST", "http://localhost:8585")
_TOKEN = os.getenv("OPENMETADATA_JWT_TOKEN", "")

HEADERS = {
    "Authorization": f"Bearer {_TOKEN}",
    "Content-Type": "application/json",
}


def _url(path: str) -> str:
    return f"{_HOST}/api/v1{path}"


async def get(path: str, params: dict | None = None) -> Any:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(_url(path), headers=HEADERS, params=params or {})
        r.raise_for_status()
        return r.json()


async def patch(path: str, payload: list[dict]) -> Any:
    """OpenMetadata uses JSON Patch (RFC 6902) for updates."""
    headers = {**HEADERS, "Content-Type": "application/json-patch+json"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.patch(_url(path), headers=headers, json=payload)
        r.raise_for_status()
        return r.json()


async def search_entities(query: str, entity_type: str = "", size: int = 50) -> dict:
    """
    Call OpenMetadata's Elasticsearch-backed search API.
    entity_type maps to the index name, e.g. 'table', 'dashboard', 'pipeline'.
    """
    index_map = {
        "table": "table_search_index",
        "dashboard": "dashboard_search_index",
        "pipeline": "pipeline_search_index",
        "topic": "topic_search_index",
        "mlmodel": "mlmodel_search_index",
        "": "all",  # search across everything
    }
    index = index_map.get(entity_type.lower(), "all")
    params = {"q": query, "index": index, "from": 0, "size": size}
    return await get("/search/query", params)


async def get_lineage_by_fqn(entity_type: str, fqn: str, upstream: int = 3, downstream: int = 3) -> dict:
    return await get(
        f"/lineage/{entity_type}/name/{fqn}",
        {"upstreamDepth": upstream, "downstreamDepth": downstream},
    )


async def get_table_by_fqn(fqn: str) -> dict:
    return await get(f"/tables/name/{fqn}", {"fields": "columns,owners,tags,domain"})


async def get_entity_by_id(entity_type: str, entity_id: str) -> dict:
    return await get(f"/{entity_type}s/{entity_id}", {"fields": "owners,tags,domain"})


async def patch_table_tags(table_id: str, tag_fqns: list[str]) -> dict:
    """Add tags to a table via JSON Patch."""
    ops = [
        {
            "op": "add",
            "path": "/tags/-",
            "value": {
                "tagFQN": fqn,
                "source": "Classification",
                "labelType": "Automated",
                "state": "Suggested",
            },
        }
        for fqn in tag_fqns
    ]
    return await patch(f"/tables/{table_id}", ops)


async def list_tables_with_tag(tag_fqn: str, limit: int = 100) -> dict:
    return await get("/tables", {"tags": tag_fqn, "limit": limit, "fields": "owners,tags,domain"})


async def get_test_suites_for_table(table_fqn: str) -> dict:
    return await get("/dataQuality/testSuites", {"entityLink": f"<#E::table::{table_fqn}>"})
