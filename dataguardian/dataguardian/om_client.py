"""
OpenMetadata API client — thin async wrapper around the REST API.
All tools in the MCP server use this module exclusively.
"""

import os
import httpx
from typing import Any

_BASE: str = ""
_HEADERS: dict = {}


def init():
    """Initialize from environment variables."""
    global _BASE, _HEADERS
    host = os.environ["OPENMETADATA_HOST"].rstrip("/")
    token = os.environ["OPENMETADATA_JWT_TOKEN"]
    _BASE = f"{host}/api/v1"
    _HEADERS = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def get(path: str, params: dict | None = None) -> Any:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{_BASE}{path}", headers=_HEADERS, params=params)
        r.raise_for_status()
        return r.json()


async def put(path: str, body: dict) -> Any:
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.put(f"{_BASE}{path}", headers=_HEADERS, json=body)
        r.raise_for_status()
        return r.json()


async def patch(path: str, body: list) -> Any:
    """JSON Patch (RFC 6902)."""
    headers = {**_HEADERS, "Content-Type": "application/json-patch+json"}
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.patch(f"{_BASE}{path}", headers=headers, json=body)
        r.raise_for_status()
        return r.json()
