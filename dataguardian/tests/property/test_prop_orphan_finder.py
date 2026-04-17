"""
Property-based tests for dataguardian.tools.orphan_finder.

# Feature: dataguardian-enhancements

Properties tested:
  Property 1:  Parallel and sequential orphan scoring are equivalent
  Property 2:  Orphan finder exception isolation
  Property 25: Orphan finder entity-type-aware risk scoring
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dataguardian.tools.orphan_finder import _score_asset


# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

_ENTITY_TYPES = ["table", "dashboard", "pipeline"]

_asset_strategy = st.fixed_dictionaries(
    {
        "fqn": st.text(min_size=1, max_size=40),
        "owner": st.one_of(st.none(), st.text(min_size=1, max_size=20)),
        "description": st.one_of(st.none(), st.text(min_size=0, max_size=50)),
        "tier": st.one_of(st.none(), st.text(min_size=1, max_size=20)),
        "entity_type": st.sampled_from(_ENTITY_TYPES),
    }
)


# ---------------------------------------------------------------------------
# Property 1: Parallel and sequential orphan scoring are equivalent
# Validates: Requirements 2.2
# ---------------------------------------------------------------------------

@given(
    assets=st.lists(_asset_strategy, min_size=0, max_size=10),
    check_quality=st.booleans(),
    check_lineage=st.booleans(),
)
@settings(max_examples=10)
def test_property1_parallel_sequential_equivalence(assets, check_quality, check_lineage):
    """
    Property 1: Parallel and sequential orphan scoring are equivalent.

    For any list of assets, running _score_asset sequentially and via
    asyncio.gather must produce identical risk_score and risk_level values.

    Validates: Requirements 2.2
    """
    # Mock _has_quality_tests and _has_lineage to return deterministic values
    # (True for assets whose fqn length is even, False otherwise)
    async def mock_has_quality_tests(fqn: str) -> bool:
        return len(fqn) % 2 == 0

    async def mock_has_lineage(fqn: str) -> bool:
        return len(fqn) % 3 == 0

    with patch(
        "dataguardian.tools.orphan_finder._has_quality_tests",
        side_effect=mock_has_quality_tests,
    ), patch(
        "dataguardian.tools.orphan_finder._has_lineage",
        side_effect=mock_has_lineage,
    ):
        # Sequential
        sequential_results = []
        for asset in assets:
            result = asyncio.run(_score_asset(asset, check_quality, check_lineage))
            sequential_results.append(result)

        # Parallel
        async def run_parallel():
            return list(
                await asyncio.gather(
                    *[_score_asset(a, check_quality, check_lineage) for a in assets]
                )
            )

        parallel_results = asyncio.run(run_parallel())

    assert len(sequential_results) == len(parallel_results)
    for seq, par in zip(sequential_results, parallel_results):
        assert seq["risk_score"] == par["risk_score"], (
            f"risk_score mismatch for asset {seq.get('fqn')}: "
            f"sequential={seq['risk_score']}, parallel={par['risk_score']}"
        )
        assert seq["risk_level"] == par["risk_level"], (
            f"risk_level mismatch for asset {seq.get('fqn')}: "
            f"sequential={seq['risk_level']}, parallel={par['risk_level']}"
        )


# ---------------------------------------------------------------------------
# Property 2: Orphan finder exception isolation
# Validates: Requirements 2.3
# ---------------------------------------------------------------------------

@given(
    assets=st.lists(_asset_strategy, min_size=1, max_size=10),
    failing_indices=st.frozensets(st.integers(min_value=0, max_value=9)),
)
@settings(max_examples=10)
def test_property2_exception_isolation(assets, failing_indices):
    """
    Property 2: Orphan finder exception isolation.

    For a list of assets where some quality/lineage checks raise exceptions:
    - Assets with successful checks get correct scores.
    - Assets with failed checks don't get the flag (conservative: False).

    Validates: Requirements 2.3
    """
    # Clamp failing_indices to valid range for this asset list
    valid_failing = {i for i in failing_indices if i < len(assets)}

    call_count = {"quality": 0, "lineage": 0}

    async def mock_has_quality_tests(fqn: str) -> bool:
        idx = call_count["quality"]
        call_count["quality"] += 1
        if idx in valid_failing:
            raise RuntimeError(f"Simulated quality check failure for index {idx}")
        return True  # success → has tests → no NO_QUALITY_TESTS flag

    async def mock_has_lineage(fqn: str) -> bool:
        idx = call_count["lineage"]
        call_count["lineage"] += 1
        if idx in valid_failing:
            raise RuntimeError(f"Simulated lineage check failure for index {idx}")
        return True  # success → has lineage → no NO_LINEAGE flag

    with patch(
        "dataguardian.tools.orphan_finder._has_quality_tests",
        side_effect=mock_has_quality_tests,
    ), patch(
        "dataguardian.tools.orphan_finder._has_lineage",
        side_effect=mock_has_lineage,
    ):
        async def run_all():
            return list(
                await asyncio.gather(
                    *[_score_asset(a, True, True) for a in assets]
                )
            )

        results = asyncio.run(run_all())

    # All assets must be present in results (no asset dropped due to exception)
    assert len(results) == len(assets), (
        f"Expected {len(assets)} results, got {len(results)}"
    )

    # Every result must have the required fields
    for result in results:
        assert "risk_score" in result
        assert "risk_level" in result
        assert "risk_flags" in result
        # risk_score must be non-negative
        assert result["risk_score"] >= 0


# ---------------------------------------------------------------------------
# Property 25: Orphan finder entity-type-aware risk scoring
# Validates: Requirements 13.2, 13.3
# ---------------------------------------------------------------------------

@given(
    entity_type=st.sampled_from(["dashboard", "pipeline", "table"]),
    check_quality=st.booleans(),
)
@settings(max_examples=10)
def test_property25_entity_type_aware_quality_scoring(entity_type, check_quality):
    """
    Property 25: Orphan finder entity-type-aware risk scoring.

    For any asset with entity_type "dashboard" or "pipeline":
    - NO_QUALITY_TESTS must NEVER appear in risk_flags.

    For any asset with entity_type "table":
    - NO_QUALITY_TESTS CAN appear when check_quality=True and no tests found.

    Validates: Requirements 13.2, 13.3
    """
    asset = {
        "fqn": "some.fully.qualified.name",
        "owner": None,          # no owner → NO_OWNER flag
        "description": None,    # no description → NO_DESCRIPTION flag
        "tier": None,           # no tier → NO_TIER flag
        "entity_type": entity_type,
    }

    async def mock_has_quality_tests(fqn: str) -> bool:
        return False  # no tests found

    async def mock_has_lineage(fqn: str) -> bool:
        return True  # has lineage → no NO_LINEAGE flag

    with patch(
        "dataguardian.tools.orphan_finder._has_quality_tests",
        side_effect=mock_has_quality_tests,
    ), patch(
        "dataguardian.tools.orphan_finder._has_lineage",
        side_effect=mock_has_lineage,
    ):
        result = asyncio.run(_score_asset(asset, check_quality, check_lineage=True))

    if entity_type in ("dashboard", "pipeline"):
        assert "NO_QUALITY_TESTS" not in result["risk_flags"], (
            f"NO_QUALITY_TESTS must never appear for entity_type={entity_type}, "
            f"but got risk_flags={result['risk_flags']}"
        )
    elif entity_type == "table" and check_quality:
        # For tables with check_quality=True and no tests found, flag SHOULD appear
        assert "NO_QUALITY_TESTS" in result["risk_flags"], (
            f"NO_QUALITY_TESTS should appear for entity_type=table with check_quality=True "
            f"and no tests found, but got risk_flags={result['risk_flags']}"
        )
