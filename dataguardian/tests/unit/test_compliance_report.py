"""
Unit tests for dataguardian.tools.compliance_report — truncation transparency.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from dataguardian.tools.compliance_report import generate_compliance_report, LLM_ASSET_CAP


def _make_asset(i: int) -> dict:
    """Create a minimal asset dict with a unique FQN."""
    return {"fqn": f"db.schema.table_{i}", "owner": "owner", "entity_type": "table", "matched_tag": "PII"}


def _build_search_result(n: int) -> dict:
    """Return a search_sensitive_assets-style result with n unique assets."""
    assets = [_make_asset(i) for i in range(n)]
    return {"assets_by_type": {"table": assets}}


def _mock_llm_client(report_text: str = "Mock report."):
    """Build a mock LLM client that returns a fixed report string."""
    mock_message = MagicMock()
    mock_message.content = report_text
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    mock_client = AsyncMock()
    mock_client.chat = MagicMock()
    mock_client.chat.completions = MagicMock()
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    return mock_client


async def _run_report(n_assets: int, output_format: str = "markdown") -> dict:
    """Helper: run generate_compliance_report with mocked dependencies."""
    search_result = _build_search_result(n_assets)
    mock_client = _mock_llm_client()

    with patch(
        "dataguardian.tools.compliance_report.search_sensitive_assets",
        new=AsyncMock(return_value=search_result),
    ), patch(
        "dataguardian.tools.compliance_report.get_client",
        return_value=mock_client,
    ), patch(
        "dataguardian.tools.compliance_report.get_model",
        return_value="mock-model",
    ):
        return await generate_compliance_report(
            regulation="GDPR",
            domain=None,
            output_format=output_format,
        )


# ---------------------------------------------------------------------------
# Truncation fields — value correctness
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_truncated_false_when_assets_at_cap():
    """truncated=False and truncated_at=None when assets == LLM_ASSET_CAP (exactly at cap)."""
    result = await _run_report(n_assets=LLM_ASSET_CAP)
    assert result["truncated"] is False
    assert result["truncated_at"] is None


@pytest.mark.asyncio
async def test_truncated_false_when_assets_below_cap():
    """truncated=False and truncated_at=None when assets < LLM_ASSET_CAP."""
    result = await _run_report(n_assets=10)
    assert result["truncated"] is False
    assert result["truncated_at"] is None


@pytest.mark.asyncio
async def test_truncated_false_when_zero_assets():
    """truncated=False and truncated_at=None when there are no assets."""
    result = await _run_report(n_assets=0)
    assert result["truncated"] is False
    assert result["truncated_at"] is None


@pytest.mark.asyncio
async def test_truncated_true_when_assets_exceed_cap():
    """truncated=True and truncated_at=LLM_ASSET_CAP when assets > LLM_ASSET_CAP."""
    result = await _run_report(n_assets=LLM_ASSET_CAP + 1)
    assert result["truncated"] is True
    assert result["truncated_at"] == LLM_ASSET_CAP


@pytest.mark.asyncio
async def test_truncated_true_when_assets_far_exceed_cap():
    """truncated=True and truncated_at=LLM_ASSET_CAP when assets >> LLM_ASSET_CAP."""
    result = await _run_report(n_assets=100)
    assert result["truncated"] is True
    assert result["truncated_at"] == LLM_ASSET_CAP


# ---------------------------------------------------------------------------
# Truncation fields — present in both output formats
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_truncation_fields_present_in_markdown_format():
    """Both 'truncated' and 'truncated_at' are present in markdown output format."""
    result = await _run_report(n_assets=10, output_format="markdown")
    assert "truncated" in result
    assert "truncated_at" in result


@pytest.mark.asyncio
async def test_truncation_fields_present_in_json_format():
    """Both 'truncated' and 'truncated_at' are present in json output format."""
    result = await _run_report(n_assets=10, output_format="json")
    assert "truncated" in result
    assert "truncated_at" in result


@pytest.mark.asyncio
async def test_truncation_fields_consistent_across_formats_below_cap():
    """truncated/truncated_at values are identical for markdown and json when below cap."""
    result_md = await _run_report(n_assets=10, output_format="markdown")
    result_json = await _run_report(n_assets=10, output_format="json")
    assert result_md["truncated"] == result_json["truncated"]
    assert result_md["truncated_at"] == result_json["truncated_at"]


@pytest.mark.asyncio
async def test_truncation_fields_consistent_across_formats_above_cap():
    """truncated/truncated_at values are identical for markdown and json when above cap."""
    result_md = await _run_report(n_assets=75, output_format="markdown")
    result_json = await _run_report(n_assets=75, output_format="json")
    assert result_md["truncated"] == result_json["truncated"]
    assert result_md["truncated_at"] == result_json["truncated_at"]
