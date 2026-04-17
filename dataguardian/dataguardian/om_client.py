"""
OpenMetadata API client — thin async wrapper around the REST API.
All tools in the MCP server use this module exclusively.
"""

import asyncio
import logging
import os
import time
import httpx
from typing import Any

logger = logging.getLogger(__name__)

_BASE: str = ""
_HEADERS: dict = {}

# Shared HTTP connection pool
_client: httpx.AsyncClient | None = None

# TTL cache: maps cache_key -> (response_data, expiry_unix_timestamp)
_cache: dict[str, tuple[Any, float]] = {}
_cache_ttl: int = 300
_max_retries: int = 3
_retry_base_delay: float = 0.5
_retryable_statuses: frozenset = frozenset({429, 502, 503, 504})
_non_retryable_statuses: frozenset = frozenset({400, 401, 403, 404})


def _cache_key(path: str, params: dict | None) -> str:
    return f"GET:{path}:{sorted((params or {}).items())}"


def _is_cacheable(path: str) -> bool:
    return path.startswith("/lineage/") or path.startswith("/teams/name/")


def init():
    """Initialize from environment variables."""
    global _BASE, _HEADERS, _client, _cache, _cache_ttl, _max_retries, _retry_base_delay
    host = os.environ["OPENMETADATA_HOST"].rstrip("/")
    token = os.environ["OPENMETADATA_JWT_TOKEN"]
    _BASE = f"{host}/api/v1"
    _HEADERS = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    _cache_ttl = int(os.environ.get("CACHE_TTL_SECONDS", 300))
    _max_retries = int(os.environ.get("OM_MAX_RETRIES", 3))
    _retry_base_delay = float(os.environ.get("OM_RETRY_BASE_DELAY_SECONDS", 0.5))

    _cache = {}
    _client = httpx.AsyncClient(
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        timeout=30,
    )


async def _request_with_retry(method: str, url: str, **kwargs) -> httpx.Response:
    """Issue an HTTP request with exponential backoff retry for transient errors."""
    for attempt in range(_max_retries + 1):
        r = await _client.request(method, url, **kwargs)
        status = r.status_code

        if status in _non_retryable_statuses:
            # Raise immediately — no retry for 400, 401, 403, 404
            r.raise_for_status()

        if status in _retryable_statuses:
            if attempt < _max_retries:
                delay = _retry_base_delay * (2 ** attempt)
                logger.warning(
                    "Retryable error on attempt %d/%d: HTTP %d for %s — retrying in %.2fs",
                    attempt + 1,
                    _max_retries + 1,
                    status,
                    url,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            else:
                # Exhausted all retries — raise the final error
                r.raise_for_status()

        # For any other non-2xx status, raise immediately
        r.raise_for_status()
        return r

    # Should not be reached, but satisfies type checker
    r.raise_for_status()  # type: ignore[return]
    return r  # type: ignore[return]


async def get(path: str, params: dict | None = None) -> Any:
    if _client is None:
        raise RuntimeError("OM_Client not initialized. Call om_client.init() first.")

    url = f"{_BASE}{path}"

    # Check cache for cacheable paths
    if _is_cacheable(path):
        key = _cache_key(path, params)
        if key in _cache:
            value, expiry = _cache[key]
            if time.time() < expiry:
                return value

    r = await _request_with_retry("GET", url, headers=_HEADERS, params=params)
    data = r.json()

    if _is_cacheable(path):
        _cache[_cache_key(path, params)] = (data, time.time() + _cache_ttl)

    return data


async def put(path: str, body: dict) -> Any:
    if _client is None:
        raise RuntimeError("OM_Client not initialized. Call om_client.init() first.")
    r = await _request_with_retry("PUT", f"{_BASE}{path}", headers=_HEADERS, json=body)
    return r.json()


async def patch(path: str, body: list) -> Any:
    """JSON Patch (RFC 6902)."""
    if _client is None:
        raise RuntimeError("OM_Client not initialized. Call om_client.init() first.")
    patch_headers = {**_HEADERS, "Content-Type": "application/json-patch+json"}
    r = await _request_with_retry("PATCH", f"{_BASE}{path}", headers=patch_headers, json=body)
    return r.json()


async def close() -> None:
    """Close the shared HTTP client and release all connections."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
