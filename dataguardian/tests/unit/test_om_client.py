"""
Unit tests for dataguardian.om_client — shared pool, TTL cache, retry/backoff, close().
"""

import time
import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock, patch

import dataguardian.om_client as om_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status_code: int, json_body: dict | None = None) -> httpx.Response:
    """Build a minimal httpx.Response for mocking."""
    content = b"{}" if json_body is None else __import__("json").dumps(json_body).encode()
    request = httpx.Request("GET", "http://test.com")
    response = httpx.Response(status_code, content=content, request=request)
    return response


def _reset_module():
    """Reset all module-level state between tests."""
    om_client._client = None
    om_client._cache = {}
    om_client._cache_ttl = 300
    om_client._max_retries = 3
    om_client._retry_base_delay = 0.5
    om_client._BASE = ""
    om_client._HEADERS = {}


# ---------------------------------------------------------------------------
# Uninitialized pool raises RuntimeError
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_raises_when_not_initialized():
    _reset_module()
    with pytest.raises(RuntimeError, match="OM_Client not initialized"):
        await om_client.get("/some/path")


@pytest.mark.asyncio
async def test_put_raises_when_not_initialized():
    _reset_module()
    with pytest.raises(RuntimeError, match="OM_Client not initialized"):
        await om_client.put("/some/path", {"key": "value"})


@pytest.mark.asyncio
async def test_patch_raises_when_not_initialized():
    _reset_module()
    with pytest.raises(RuntimeError, match="OM_Client not initialized"):
        await om_client.patch("/some/path", [{"op": "add", "path": "/x", "value": 1}])


# ---------------------------------------------------------------------------
# init() reads env vars and resets cache
# ---------------------------------------------------------------------------

def test_init_reads_env_vars(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")
    monkeypatch.setenv("CACHE_TTL_SECONDS", "120")
    monkeypatch.setenv("OM_MAX_RETRIES", "5")
    monkeypatch.setenv("OM_RETRY_BASE_DELAY_SECONDS", "1.0")

    om_client.init()

    assert om_client._BASE == "http://localhost:8585/api/v1"
    assert om_client._HEADERS["Authorization"] == "Bearer test-token"
    assert om_client._cache_ttl == 120
    assert om_client._max_retries == 5
    assert om_client._retry_base_delay == 1.0
    assert om_client._cache == {}
    assert om_client._client is not None


def test_init_uses_defaults_when_env_vars_absent(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")
    monkeypatch.delenv("CACHE_TTL_SECONDS", raising=False)
    monkeypatch.delenv("OM_MAX_RETRIES", raising=False)
    monkeypatch.delenv("OM_RETRY_BASE_DELAY_SECONDS", raising=False)

    om_client.init()

    assert om_client._cache_ttl == 300
    assert om_client._max_retries == 3
    assert om_client._retry_base_delay == 0.5


def test_init_clears_existing_cache(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")

    # Pre-populate cache
    om_client._cache["some-key"] = ({"data": 1}, time.time() + 999)

    om_client.init()

    assert om_client._cache == {}


# ---------------------------------------------------------------------------
# close() sets client to None
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_close_sets_client_to_none(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")

    om_client.init()
    assert om_client._client is not None

    await om_client.close()
    assert om_client._client is None


@pytest.mark.asyncio
async def test_close_is_idempotent():
    """Calling close() when already None should not raise."""
    _reset_module()
    assert om_client._client is None
    await om_client.close()  # should not raise
    assert om_client._client is None


# ---------------------------------------------------------------------------
# Cache behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_caches_lineage_response(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")
    om_client.init()
    om_client._cache_ttl = 300

    response_data = {"entity": "lineage-data"}
    mock_response = _make_response(200, response_data)

    with patch.object(om_client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response

        result1 = await om_client.get("/lineage/table/abc123")
        result2 = await om_client.get("/lineage/table/abc123")

    # HTTP should only be called once; second call served from cache
    assert mock_req.call_count == 1
    assert result1 == response_data
    assert result2 == response_data


@pytest.mark.asyncio
async def test_get_caches_teams_response(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")
    om_client.init()

    response_data = {"team": "data-engineers"}
    mock_response = _make_response(200, response_data)

    with patch.object(om_client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response

        result1 = await om_client.get("/teams/name/data-engineers")
        result2 = await om_client.get("/teams/name/data-engineers")

    assert mock_req.call_count == 1
    assert result1 == result2 == response_data


@pytest.mark.asyncio
async def test_get_does_not_cache_other_paths(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")
    om_client.init()

    response_data = {"tables": []}
    mock_response = _make_response(200, response_data)

    with patch.object(om_client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response

        await om_client.get("/tables")
        await om_client.get("/tables")

    # Non-cacheable path: two HTTP calls expected
    assert mock_req.call_count == 2


@pytest.mark.asyncio
async def test_get_refetches_after_ttl_expiry(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")
    om_client.init()
    om_client._cache_ttl = 1  # 1 second TTL

    response_data = {"entity": "lineage-data"}
    mock_response = _make_response(200, response_data)

    with patch.object(om_client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_response

        await om_client.get("/lineage/table/abc123")

        # Manually expire the cache entry
        key = om_client._cache_key("/lineage/table/abc123", None)
        om_client._cache[key] = (response_data, time.time() - 1)  # already expired

        await om_client.get("/lineage/table/abc123")

    # Should have made 2 HTTP calls (first + after expiry)
    assert mock_req.call_count == 2


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_retries_on_retryable_status(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")
    om_client.init()
    om_client._max_retries = 2
    om_client._retry_base_delay = 0.0  # no actual sleep in tests

    retryable_response = _make_response(503)
    success_response = _make_response(200, {"ok": True})

    call_count = 0

    async def mock_request(method, url, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return retryable_response
        return success_response

    with patch.object(om_client._client, "request", side_effect=mock_request):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await om_client.get("/tables")

    assert result == {"ok": True}
    assert call_count == 3


@pytest.mark.asyncio
async def test_get_raises_after_exhausting_retries(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")
    om_client.init()
    om_client._max_retries = 2
    om_client._retry_base_delay = 0.0

    retryable_response = _make_response(429)

    with patch.object(om_client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = retryable_response
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await om_client.get("/tables")

    # 1 initial + 2 retries = 3 total attempts
    assert mock_req.call_count == 3


@pytest.mark.asyncio
async def test_get_does_not_retry_non_retryable_status(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")
    om_client.init()
    om_client._max_retries = 3

    not_found_response = _make_response(404)

    with patch.object(om_client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = not_found_response
        with pytest.raises(httpx.HTTPStatusError):
            await om_client.get("/tables/nonexistent")

    # Only 1 attempt — no retries for 404
    assert mock_req.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
async def test_non_retryable_statuses_raise_immediately(status_code, monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")
    om_client.init()
    om_client._max_retries = 3

    error_response = _make_response(status_code)

    with patch.object(om_client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = error_response
        with pytest.raises(httpx.HTTPStatusError):
            await om_client.get("/some/path")

    assert mock_req.call_count == 1


# ---------------------------------------------------------------------------
# PUT and PATCH are never cached
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_put_is_not_cached(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")
    om_client.init()

    success_response = _make_response(200, {"updated": True})

    with patch.object(om_client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = success_response

        await om_client.put("/lineage/table/abc", {"data": 1})
        await om_client.put("/lineage/table/abc", {"data": 1})

    assert mock_req.call_count == 2
    assert om_client._cache == {}


@pytest.mark.asyncio
async def test_patch_is_not_cached(monkeypatch):
    _reset_module()
    monkeypatch.setenv("OPENMETADATA_HOST", "http://localhost:8585")
    monkeypatch.setenv("OPENMETADATA_JWT_TOKEN", "test-token")
    om_client.init()

    success_response = _make_response(200, {"patched": True})

    with patch.object(om_client._client, "request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = success_response

        await om_client.patch("/lineage/table/abc", [{"op": "add", "path": "/x", "value": 1}])
        await om_client.patch("/lineage/table/abc", [{"op": "add", "path": "/x", "value": 1}])

    assert mock_req.call_count == 2
    assert om_client._cache == {}
