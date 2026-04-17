"""
Property-based tests for dataguardian.tools.compliance_report.

# Feature: dataguardian-enhancements

Properties tested:
  Property 24: Compliance report truncation transparency is format-invariant
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from hypothesis import given, settings
from hypothesis import strategies as st

from dataguardian.tools.compliance_report import generate_compliance_report, LLM_ASSET_CAP


def _make_asset(i: int) -> dict:
    """Create a minimal asset dict with a unique FQN."""
    return {"fqn": f"db.schema.table_{i}", "owner": "owner", "entity_type": "table", "matched_tag": "PII"}


def _build_search_result(n: int) -> dict:
    """Return a search_sensitive_assets-style result with n unique assets."""
    assets = [_make_asset(i) for i in range(n)]
    return {"assets_by_type": {"table": assets}}


# ---------------------------------------------------------------------------
# Property 24: Compliance report truncation transparency is format-invariant
# Validates: Requirements 12.1, 12.2, 12.3, 12.4
# ---------------------------------------------------------------------------

@given(
    n_assets=st.integers(min_value=0, max_value=100),
    output_format=st.sampled_from(["markdown", "json"]),
)
@settings(max_examples=10)
def test_property24_truncation_transparency_format_invariant(n_assets, output_format):
    """
    Property 24: Compliance report truncation transparency is format-invariant.

    For any output_format in ["markdown", "json"] and any number of unique assets:
    - When total_unique > LLM_ASSET_CAP: truncated=True and truncated_at=LLM_ASSET_CAP
    - When total_unique <= LLM_ASSET_CAP: truncated=False and truncated_at=None

    Validates: Requirements 12.1, 12.2, 12.3, 12.4
    """
    import asyncio

    search_result = _build_search_result(n_assets)

    # Mock LLM response
    mock_message = MagicMock()
    mock_message.content = "Mock compliance report text."
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_llm_response = MagicMock()
    mock_llm_response.choices = [mock_choice]

    mock_llm_client = AsyncMock()
    mock_llm_client.chat = MagicMock()
    mock_llm_client.chat.completions = MagicMock()
    mock_llm_client.chat.completions.create = AsyncMock(return_value=mock_llm_response)

    with patch(
        "dataguardian.tools.compliance_report.search_sensitive_assets",
        new=AsyncMock(return_value=search_result),
    ), patch(
        "dataguardian.tools.compliance_report.get_client",
        return_value=mock_llm_client,
    ), patch(
        "dataguardian.tools.compliance_report.get_model",
        return_value="mock-model",
    ):
        result = asyncio.run(
            generate_compliance_report(
                regulation="GDPR",
                domain=None,
                output_format=output_format,
            )
        )

    # Both fields must always be present
    assert "truncated" in result, "Field 'truncated' must be present in result"
    assert "truncated_at" in result, "Field 'truncated_at' must be present in result"

    if n_assets > LLM_ASSET_CAP:
        assert result["truncated"] is True, (
            f"Expected truncated=True when n_assets={n_assets} > LLM_ASSET_CAP={LLM_ASSET_CAP}"
        )
        assert result["truncated_at"] == LLM_ASSET_CAP, (
            f"Expected truncated_at={LLM_ASSET_CAP}, got {result['truncated_at']}"
        )
    else:
        assert result["truncated"] is False, (
            f"Expected truncated=False when n_assets={n_assets} <= LLM_ASSET_CAP={LLM_ASSET_CAP}"
        )
        assert result["truncated_at"] is None, (
            f"Expected truncated_at=None, got {result['truncated_at']}"
        )
