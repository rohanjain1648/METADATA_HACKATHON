"""
Property-based tests for dataguardian.om_client.

# Feature: dataguardian-enhancements

Properties tested:
  Property 3: Cacheable endpoints are served from cache within TTL
  Property 4: Cache expiry triggers a fresh fetch
  Property 5: PUT and PATCH responses are never cached
  Property 6: Retryable status codes trigger the correct number of retries
  Property 7: Exponential backoff delay formula
  Property 8: Non-retryable status codes raise immediately
"""

import asyncio
import json
import time
import httpx
from unittest.mock import AsyncMock, patch

from hypothesis import given, settings
from hypothesis import strategies as st

import dataguardian.om_client as om_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(status_code: int, body: dict | None = None) -> httpx.Response:
    content = json.dumps(body or {}).encode()
    request = httpx.Request("GET", "http://test.com")
    return httpx.Response(status_code, content=content, request=request)


def _setup_client():
    """Reset module state and set up a fake initialized client."""
    om_client._client = None
    om_client._cache = {}
    om_client._cache_ttl = 300
    om_client._max_retries = 3
    om_client._retry_base_delay = 0.0  # no real sleep in tests
    om_client._BASE = "http://om-host/api/v1"
    om_client._HEADERS = {"Authorization": "Bearer fake-token", "Content-Type": "application/json"}
    om_client._client = httpx.AsyncClient(timeout=30)


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

CACHEABLE_PATHS = st.one_of(
    st.builds(
        lambda s: f"/lineage/{s}",
        st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_"),
    ),
    st.builds(
        lambda s: f"/teams/name/{s}",
        st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789-_"),
    ),
)

RESPONSE_BODIES = st.dictionaries(
    st.text(min_size=1, max_size=8, alphabet="abcdefghijklmnopqrstuvwxyz"),
    st.integers(min_value=0, max_value=999),
    max_size=3,
)

NON_LINEAGE_PATHS = st.builds(
    lambda s: f"/tables/{s}",
    st.text(min_size=1, max_size=20, alphabet="abcdefghijklmnopqrstuvwxyz0123456789"),
)

PUT_BODIES = st.dictionaries(
    st.text(min_size=1, max_size=8, alphabet="abcdefghijklmnopqrstuvwxyz"),
    st.integers(),
    max_size=3,
)

PATCH_BODIES = st.lists(
    st.fixed_dictionaries({
        "op": st.sampled_from(["add", "replace"]),
        "path": st.builds(lambda s: f"/{s}", st.text(min_size=1, max_size=8, alphabet="abcdefghijklmnopqrstuvwxyz")),
        "value": st.integers(),
    }),
    min_size=1,
    max_size=2,
)

RETRYABLE_STATUSES = st.sampled_from([429, 502, 503, 504])
NON_RETRYABLE_STATUSES = st.sampled_from([400, 401, 403, 404])


# ---------------------------------------------------------------------------
# Property 3: Cacheable endpoints are served from cache within TTL
# Validates: Requirements 3.1, 3.2
# ---------------------------------------------------------------------------

@given(path=CACHEABLE_PATHS, body=RESPONSE_BODIES)
@settings(max_examples=10, deadline=5000)
def test_property3_cacheable_endpoints_served_from_cache_within_ttl(path, body):
    """
    Property 3: Cacheable endpoints are served from cache within TTL.
    Validates: Requirements 3.1, 3.2
    """
    _setup_client()
    call_count = 0

    async def run():
        nonlocal call_count

        async def mock_request(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            return _make_response(200, body)

        with patch.object(om_client._client, "request", side_effect=mock_request):
            result1 = await om_client.get(path)
            result2 = await om_client.get(path)

        return result1, result2

    result1, result2 = asyncio.run(run())

    assert call_count == 1, f"Expected 1 HTTP call, got {call_count} for path {path}"
    assert result1 == body
    assert result2 == body


# ---------------------------------------------------------------------------
# Property 4: Cache expiry triggers a fresh fetch
# Validates: Requirements 3.3
# ---------------------------------------------------------------------------

@given(path=CACHEABLE_PATHS, body=RESPONSE_BODIES)
@settings(max_examples=10, deadline=5000)
def test_property4_cache_expiry_triggers_fresh_fetch(path, body):
    """
    Property 4: Cache expiry triggers a fresh fetch.
    Validates: Requirements 3.3
    """
    _setup_client()
    call_count = 0

    async def run():
        nonlocal call_count

        async def mock_request(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            return _make_response(200, body)

        with patch.object(om_client._client, "request", side_effect=mock_request):
            await om_client.get(path)
            # Manually expire the cache entry
            key = om_client._cache_key(path, None)
            om_client._cache[key] = (body, time.time() - 1)
            await om_client.get(path)

    asyncio.run(run())
    assert call_count == 2, f"Expected 2 HTTP calls after expiry, got {call_count}"


# ---------------------------------------------------------------------------
# Property 5: PUT and PATCH responses are never cached
# Validates: Requirements 3.5
# ---------------------------------------------------------------------------

@given(path=NON_LINEAGE_PATHS, body=PUT_BODIES)
@settings(max_examples=10, deadline=5000)
def test_property5_put_never_cached(path, body):
    """Property 5: PUT responses are never cached. Validates: Requirements 3.5"""
    _setup_client()
    call_count = 0

    async def run():
        nonlocal call_count

        async def mock_request(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            return _make_response(200, {"ok": True})

        with patch.object(om_client._client, "request", side_effect=mock_request):
            await om_client.put(path, body)
            await om_client.put(path, body)

    asyncio.run(run())
    assert call_count == 2
    assert om_client._cache == {}


@given(path=NON_LINEAGE_PATHS, body=PATCH_BODIES)
@settings(max_examples=10, deadline=5000)
def test_property5_patch_never_cached(path, body):
    """Property 5: PATCH responses are never cached. Validates: Requirements 3.5"""
    _setup_client()
    call_count = 0

    async def run():
        nonlocal call_count

        async def mock_request(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            return _make_response(200, {"ok": True})

        with patch.object(om_client._client, "request", side_effect=mock_request):
            await om_client.patch(path, body)
            await om_client.patch(path, body)

    asyncio.run(run())
    assert call_count == 2
    assert om_client._cache == {}


# ---------------------------------------------------------------------------
# Property 6: Retryable status codes trigger the correct number of retries
# Validates: Requirements 4.1
# ---------------------------------------------------------------------------

@given(
    status_code=RETRYABLE_STATUSES,
    max_retries=st.integers(min_value=0, max_value=3),
    failures=st.integers(min_value=1, max_value=4),
)
@settings(max_examples=10, deadline=5000)
def test_property6_retryable_status_triggers_correct_retry_count(status_code, max_retries, failures):
    """
    Property 6: Retryable status codes trigger the correct number of retries.
    Validates: Requirements 4.1
    """
    _setup_client()
    om_client._max_retries = max_retries
    om_client._retry_base_delay = 0.0

    call_count = 0

    async def run():
        nonlocal call_count

        async def mock_request(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= failures:
                return _make_response(status_code)
            return _make_response(200, {"ok": True})

        with patch.object(om_client._client, "request", side_effect=mock_request):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                try:
                    await om_client.get("/tables")
                except httpx.HTTPStatusError:
                    pass

    asyncio.run(run())

    if failures <= max_retries:
        expected_calls = failures + 1  # failures + 1 success
    else:
        expected_calls = max_retries + 1  # exhausted retries

    assert call_count == expected_calls, (
        f"status={status_code}, max_retries={max_retries}, failures={failures}: "
        f"expected {expected_calls} calls, got {call_count}"
    )


# ---------------------------------------------------------------------------
# Property 7: Exponential backoff delay formula
# Validates: Requirements 4.2
# ---------------------------------------------------------------------------

@given(
    max_retries=st.integers(min_value=1, max_value=4),
    base_delay=st.floats(min_value=0.1, max_value=1.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=10, deadline=5000)
def test_property7_exponential_backoff_delay_formula(max_retries, base_delay):
    """
    Property 7: Exponential backoff delay formula.
    Validates: Requirements 4.2
    """
    _setup_client()
    om_client._max_retries = max_retries
    om_client._retry_base_delay = base_delay

    recorded_delays = []

    async def run():
        async def mock_request(method, url, **kwargs):
            return _make_response(503)

        async def mock_sleep(delay):
            recorded_delays.append(delay)

        with patch.object(om_client._client, "request", side_effect=mock_request):
            with patch("asyncio.sleep", side_effect=mock_sleep):
                try:
                    await om_client.get("/tables")
                except httpx.HTTPStatusError:
                    pass

    asyncio.run(run())

    assert len(recorded_delays) == max_retries, (
        f"Expected {max_retries} sleep calls, got {len(recorded_delays)}"
    )
    for attempt, actual_delay in enumerate(recorded_delays):
        expected_delay = base_delay * (2 ** attempt)
        assert abs(actual_delay - expected_delay) < 1e-9, (
            f"Attempt {attempt}: expected {expected_delay}, got {actual_delay}"
        )


# ---------------------------------------------------------------------------
# Property 8: Non-retryable status codes raise immediately
# Validates: Requirements 4.4
# ---------------------------------------------------------------------------

@given(status_code=NON_RETRYABLE_STATUSES, max_retries=st.integers(min_value=1, max_value=4))
@settings(max_examples=10, deadline=5000)
def test_property8_non_retryable_status_raises_immediately(status_code, max_retries):
    """
    Property 8: Non-retryable status codes raise immediately.
    Validates: Requirements 4.4
    """
    _setup_client()
    om_client._max_retries = max_retries
    call_count = 0

    async def run():
        nonlocal call_count

        async def mock_request(method, url, **kwargs):
            nonlocal call_count
            call_count += 1
            return _make_response(status_code)

        with patch.object(om_client._client, "request", side_effect=mock_request):
            try:
                await om_client.get("/some/path")
            except httpx.HTTPStatusError:
                pass

    asyncio.run(run())
    assert call_count == 1, (
        f"Non-retryable status {status_code} should cause exactly 1 HTTP call, got {call_count}"
    )
