"""
Unit tests for dataguardian.tools.orphan_finder.

Tests:
  - entity_types_scanned field present in response with value ["table", "dashboard", "pipeline"]
  - NO_QUALITY_TESTS never added for dashboard assets
  - NO_QUALITY_TESTS never added for pipeline assets
  - NO_QUALITY_TESTS CAN be added for table assets when no tests found
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from dataguardian.tools.orphan_finder import (
    find_orphaned_sensitive_assets,
    _score_asset,
    ENTITY_TYPES_SCANNED,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_asset(fqn: str, entity_type: str, owner=None, description=None, tier=None) -> dict:
    return {
        "fqn": fqn,
        "entity_type": entity_type,
        "owner": owner,
        "description": description,
        "tier": tier,
        "tags": [],
        "name": fqn.split(".")[-1],
    }


def _search_result_for(assets: list[dict]) -> dict:
    """Build a search_sensitive_assets-style result grouped by entity_type."""
    by_type: dict[str, list] = {}
    for asset in assets:
        etype = asset.get("entity_type", "table")
        by_type.setdefault(etype, []).append(asset)
    return {"assets_by_type": by_type}


# ---------------------------------------------------------------------------
# Test: entity_types_scanned field
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_entity_types_scanned_field_present():
    """entity_types_scanned must be present in the response."""
    with patch(
        "dataguardian.tools.orphan_finder.search_sensitive_assets",
        new=AsyncMock(return_value={"assets_by_type": {}}),
    ):
        result = await find_orphaned_sensitive_assets(check_quality=False, check_lineage=False)

    assert "entity_types_scanned" in result, (
        "Response must contain 'entity_types_scanned' field"
    )


@pytest.mark.asyncio
async def test_entity_types_scanned_value():
    """entity_types_scanned must equal ['table', 'dashboard', 'pipeline']."""
    with patch(
        "dataguardian.tools.orphan_finder.search_sensitive_assets",
        new=AsyncMock(return_value={"assets_by_type": {}}),
    ):
        result = await find_orphaned_sensitive_assets(check_quality=False, check_lineage=False)

    assert result["entity_types_scanned"] == ["table", "dashboard", "pipeline"], (
        f"Expected ['table', 'dashboard', 'pipeline'], got {result['entity_types_scanned']}"
    )


# ---------------------------------------------------------------------------
# Test: NO_QUALITY_TESTS never added for dashboard assets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_quality_tests_not_added_for_dashboard():
    """NO_QUALITY_TESTS must never appear in risk_flags for dashboard assets."""
    asset = _make_asset("db.dash1", "dashboard")

    with patch(
        "dataguardian.tools.orphan_finder._has_quality_tests",
        new=AsyncMock(return_value=False),
    ), patch(
        "dataguardian.tools.orphan_finder._has_lineage",
        new=AsyncMock(return_value=True),
    ):
        result = await _score_asset(asset, check_quality=True, check_lineage=True)

    assert "NO_QUALITY_TESTS" not in result["risk_flags"], (
        f"NO_QUALITY_TESTS must not appear for dashboard, got {result['risk_flags']}"
    )


@pytest.mark.asyncio
async def test_no_quality_tests_not_added_for_dashboard_via_full_scan():
    """NO_QUALITY_TESTS must not appear for dashboard assets in a full scan."""
    dashboard_asset = _make_asset("db.dash1", "dashboard")
    search_result = _search_result_for([dashboard_asset])

    with patch(
        "dataguardian.tools.orphan_finder.search_sensitive_assets",
        new=AsyncMock(return_value=search_result),
    ), patch(
        "dataguardian.tools.orphan_finder._has_quality_tests",
        new=AsyncMock(return_value=False),
    ), patch(
        "dataguardian.tools.orphan_finder._has_lineage",
        new=AsyncMock(return_value=True),
    ):
        result = await find_orphaned_sensitive_assets(check_quality=True, check_lineage=True)

    all_assets = result["all_assets_by_risk"]
    dashboard_assets = [a for a in all_assets if a.get("entity_type") == "dashboard"]
    for a in dashboard_assets:
        assert "NO_QUALITY_TESTS" not in a["risk_flags"], (
            f"NO_QUALITY_TESTS must not appear for dashboard, got {a['risk_flags']}"
        )


# ---------------------------------------------------------------------------
# Test: NO_QUALITY_TESTS never added for pipeline assets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_quality_tests_not_added_for_pipeline():
    """NO_QUALITY_TESTS must never appear in risk_flags for pipeline assets."""
    asset = _make_asset("db.pipe1", "pipeline")

    with patch(
        "dataguardian.tools.orphan_finder._has_quality_tests",
        new=AsyncMock(return_value=False),
    ), patch(
        "dataguardian.tools.orphan_finder._has_lineage",
        new=AsyncMock(return_value=True),
    ):
        result = await _score_asset(asset, check_quality=True, check_lineage=True)

    assert "NO_QUALITY_TESTS" not in result["risk_flags"], (
        f"NO_QUALITY_TESTS must not appear for pipeline, got {result['risk_flags']}"
    )


@pytest.mark.asyncio
async def test_no_quality_tests_not_added_for_pipeline_via_full_scan():
    """NO_QUALITY_TESTS must not appear for pipeline assets in a full scan."""
    pipeline_asset = _make_asset("db.pipe1", "pipeline")
    search_result = _search_result_for([pipeline_asset])

    with patch(
        "dataguardian.tools.orphan_finder.search_sensitive_assets",
        new=AsyncMock(return_value=search_result),
    ), patch(
        "dataguardian.tools.orphan_finder._has_quality_tests",
        new=AsyncMock(return_value=False),
    ), patch(
        "dataguardian.tools.orphan_finder._has_lineage",
        new=AsyncMock(return_value=True),
    ):
        result = await find_orphaned_sensitive_assets(check_quality=True, check_lineage=True)

    all_assets = result["all_assets_by_risk"]
    pipeline_assets = [a for a in all_assets if a.get("entity_type") == "pipeline"]
    for a in pipeline_assets:
        assert "NO_QUALITY_TESTS" not in a["risk_flags"], (
            f"NO_QUALITY_TESTS must not appear for pipeline, got {a['risk_flags']}"
        )


# ---------------------------------------------------------------------------
# Test: NO_QUALITY_TESTS CAN be added for table assets
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_quality_tests_added_for_table_when_no_tests_found():
    """NO_QUALITY_TESTS must appear for table assets when check_quality=True and no tests found."""
    asset = _make_asset("db.schema.table1", "table")

    with patch(
        "dataguardian.tools.orphan_finder._has_quality_tests",
        new=AsyncMock(return_value=False),
    ), patch(
        "dataguardian.tools.orphan_finder._has_lineage",
        new=AsyncMock(return_value=True),
    ):
        result = await _score_asset(asset, check_quality=True, check_lineage=True)

    assert "NO_QUALITY_TESTS" in result["risk_flags"], (
        f"NO_QUALITY_TESTS must appear for table with no tests, got {result['risk_flags']}"
    )


@pytest.mark.asyncio
async def test_no_quality_tests_not_added_for_table_when_tests_exist():
    """NO_QUALITY_TESTS must NOT appear for table assets when tests exist."""
    asset = _make_asset("db.schema.table1", "table")

    with patch(
        "dataguardian.tools.orphan_finder._has_quality_tests",
        new=AsyncMock(return_value=True),
    ), patch(
        "dataguardian.tools.orphan_finder._has_lineage",
        new=AsyncMock(return_value=True),
    ):
        result = await _score_asset(asset, check_quality=True, check_lineage=True)

    assert "NO_QUALITY_TESTS" not in result["risk_flags"], (
        f"NO_QUALITY_TESTS must not appear when tests exist, got {result['risk_flags']}"
    )


@pytest.mark.asyncio
async def test_no_quality_tests_not_added_for_table_when_check_quality_false():
    """NO_QUALITY_TESTS must NOT appear for table assets when check_quality=False."""
    asset = _make_asset("db.schema.table1", "table")

    with patch(
        "dataguardian.tools.orphan_finder._has_quality_tests",
        new=AsyncMock(return_value=False),
    ), patch(
        "dataguardian.tools.orphan_finder._has_lineage",
        new=AsyncMock(return_value=True),
    ):
        result = await _score_asset(asset, check_quality=False, check_lineage=True)

    assert "NO_QUALITY_TESTS" not in result["risk_flags"], (
        f"NO_QUALITY_TESTS must not appear when check_quality=False, got {result['risk_flags']}"
    )


# ---------------------------------------------------------------------------
# Test: ENTITY_TYPES_SCANNED constant
# ---------------------------------------------------------------------------

def test_entity_types_scanned_constant():
    """ENTITY_TYPES_SCANNED constant must equal ['table', 'dashboard', 'pipeline']."""
    assert ENTITY_TYPES_SCANNED == ["table", "dashboard", "pipeline"]
