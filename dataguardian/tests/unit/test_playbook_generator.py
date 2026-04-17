"""
Unit tests for dataguardian.tools.playbook_generator.

Tests:
  - Early return without LLM call when breach_impact returns error
  - Early return without LLM call when data_access_chain returns error
  - Successful playbook generation returns all required fields
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from dataguardian.tools.playbook_generator import generate_incident_playbook, REGULATION_OBLIGATIONS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_breach_impact_success(total_affected: int = 3) -> dict:
    """Build a minimal successful breach_impact response."""
    return {
        "breached_asset": "db.schema.users",
        "direction": "downstream",
        "total_affected": total_affected,
        "owners_to_notify": ["alice", "bob"],
        "affected_by_type": {
            "table": ["db.schema.orders", "db.schema.payments"],
            "dashboard": ["analytics.revenue_dash"],
        },
        "nodes": [
            {"id": "1", "name": "users", "fqn": "db.schema.users", "type": "table", "owner": "alice", "description": ""},
            {"id": "2", "name": "orders", "fqn": "db.schema.orders", "type": "table", "owner": "bob", "description": ""},
        ],
        "edges": [],
    }


def _make_access_chain_success() -> dict:
    """Build a minimal successful access_chain response."""
    return {
        "table": "db.schema.users",
        "direct_owner": {"name": "alice", "type": "user"},
        "owner_details": {"name": "alice", "email": "alice@example.com", "type": "user", "teams": []},
        "followers": [],
        "domain": "analytics",
        "data_products": [],
        "downstream_asset_count": 2,
        "downstream_owners": ["bob"],
        "downstream_owner_details": [{"name": "bob", "email": "bob@example.com", "type": "user"}],
        "notification_list": ["alice", "bob"],
    }


def _make_llm_response(text: str = "# Incident Playbook\n\nStep 1: Contain the breach.") -> MagicMock:
    """Build a mock LLM response."""
    mock_message = MagicMock()
    mock_message.content = text
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


# ---------------------------------------------------------------------------
# Test: Early return without LLM call when breach_impact returns error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_early_return_when_breach_impact_returns_error():
    """When breach_impact returns an error, the function must return early without calling the LLM."""
    breach_error = {"error": "Could not resolve entity for FQN: db.schema.unknown"}

    mock_llm_client = MagicMock()
    mock_llm_client.chat.completions.create = AsyncMock()

    with (
        patch(
            "dataguardian.tools.playbook_generator.get_breach_impact_graph",
            new=AsyncMock(return_value=breach_error),
        ),
        patch(
            "dataguardian.tools.playbook_generator.get_data_access_chain",
            new=AsyncMock(),
        ) as mock_access_chain,
        patch(
            "dataguardian.tools.playbook_generator.llm_client.get_client",
            return_value=mock_llm_client,
        ),
    ):
        result = await generate_incident_playbook(
            table_fqn="db.schema.unknown",
            regulation="GDPR",
        )

    # LLM must NOT have been called
    mock_llm_client.chat.completions.create.assert_not_called()
    # access_chain must NOT have been called
    mock_access_chain.assert_not_called()

    # Response must surface the error
    assert result["error"] == breach_error["error"]
    assert result["playbook"] is None
    assert result["breached_asset"] == "db.schema.unknown"
    assert result["regulation"] == "GDPR"
    assert result["total_affected_assets"] == 0
    assert result["notification_list"] == []


@pytest.mark.asyncio
async def test_early_return_breach_impact_error_preserves_regulation():
    """Early return on breach_impact error must preserve the regulation parameter."""
    breach_error = {"error": "Entity not found"}

    with (
        patch(
            "dataguardian.tools.playbook_generator.get_breach_impact_graph",
            new=AsyncMock(return_value=breach_error),
        ),
        patch(
            "dataguardian.tools.playbook_generator.get_data_access_chain",
            new=AsyncMock(),
        ),
        patch("dataguardian.tools.playbook_generator.llm_client.get_client"),
    ):
        result = await generate_incident_playbook(
            table_fqn="db.schema.users",
            regulation="HIPAA",
        )

    assert result["regulation"] == "HIPAA"
    assert result["playbook"] is None
    assert result["error"] is not None


# ---------------------------------------------------------------------------
# Test: Early return without LLM call when data_access_chain returns error
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_early_return_when_data_access_chain_returns_error():
    """When data_access_chain returns an error, the function must return early without calling the LLM."""
    access_error = {"error": "Could not fetch table details for FQN: db.schema.users"}

    mock_llm_client = MagicMock()
    mock_llm_client.chat.completions.create = AsyncMock()

    with (
        patch(
            "dataguardian.tools.playbook_generator.get_breach_impact_graph",
            new=AsyncMock(return_value=_make_breach_impact_success()),
        ),
        patch(
            "dataguardian.tools.playbook_generator.get_data_access_chain",
            new=AsyncMock(return_value=access_error),
        ),
        patch(
            "dataguardian.tools.playbook_generator.llm_client.get_client",
            return_value=mock_llm_client,
        ),
    ):
        result = await generate_incident_playbook(
            table_fqn="db.schema.users",
            regulation="GDPR",
        )

    # LLM must NOT have been called
    mock_llm_client.chat.completions.create.assert_not_called()

    # Response must surface the error
    assert result["error"] == access_error["error"]
    assert result["playbook"] is None
    assert result["breached_asset"] == "db.schema.users"
    assert result["regulation"] == "GDPR"
    assert result["total_affected_assets"] == 0
    assert result["notification_list"] == []


@pytest.mark.asyncio
async def test_early_return_data_access_chain_error_preserves_table_fqn():
    """Early return on data_access_chain error must preserve the table_fqn."""
    access_error = {"error": "Network timeout"}

    with (
        patch(
            "dataguardian.tools.playbook_generator.get_breach_impact_graph",
            new=AsyncMock(return_value=_make_breach_impact_success()),
        ),
        patch(
            "dataguardian.tools.playbook_generator.get_data_access_chain",
            new=AsyncMock(return_value=access_error),
        ),
        patch("dataguardian.tools.playbook_generator.llm_client.get_client"),
    ):
        result = await generate_incident_playbook(
            table_fqn="prod.analytics.sensitive_table",
            regulation="CCPA",
        )

    assert result["breached_asset"] == "prod.analytics.sensitive_table"
    assert result["playbook"] is None
    assert result["error"] is not None


# ---------------------------------------------------------------------------
# Test: Successful playbook generation returns all required fields
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_successful_playbook_generation_returns_all_required_fields():
    """Successful generation must return all required fields with non-null values."""
    playbook_text = "# Incident Playbook\n\n## Step 1: Contain the breach."

    mock_llm_client = MagicMock()
    mock_llm_client.chat.completions.create = AsyncMock(
        return_value=_make_llm_response(playbook_text)
    )

    with (
        patch(
            "dataguardian.tools.playbook_generator.get_breach_impact_graph",
            new=AsyncMock(return_value=_make_breach_impact_success(total_affected=3)),
        ),
        patch(
            "dataguardian.tools.playbook_generator.get_data_access_chain",
            new=AsyncMock(return_value=_make_access_chain_success()),
        ),
        patch(
            "dataguardian.tools.playbook_generator.llm_client.get_client",
            return_value=mock_llm_client,
        ),
        patch(
            "dataguardian.tools.playbook_generator.llm_client.get_model",
            return_value="gemini-2.0-flash",
        ),
    ):
        result = await generate_incident_playbook(
            table_fqn="db.schema.users",
            regulation="GDPR",
            incident_description="Unauthorized access detected in production database.",
        )

    # All required fields must be present and non-null
    assert result["breached_asset"] == "db.schema.users"
    assert result["regulation"] == "GDPR"
    assert result["total_affected_assets"] == 3
    assert result["notification_list"] == ["alice", "bob"]
    assert result["playbook"] == playbook_text
    assert result["error"] is None


@pytest.mark.asyncio
async def test_successful_playbook_generation_calls_llm():
    """Successful generation must invoke the LLM exactly once."""
    mock_llm_client = MagicMock()
    mock_llm_client.chat.completions.create = AsyncMock(
        return_value=_make_llm_response()
    )

    with (
        patch(
            "dataguardian.tools.playbook_generator.get_breach_impact_graph",
            new=AsyncMock(return_value=_make_breach_impact_success()),
        ),
        patch(
            "dataguardian.tools.playbook_generator.get_data_access_chain",
            new=AsyncMock(return_value=_make_access_chain_success()),
        ),
        patch(
            "dataguardian.tools.playbook_generator.llm_client.get_client",
            return_value=mock_llm_client,
        ),
        patch(
            "dataguardian.tools.playbook_generator.llm_client.get_model",
            return_value="gemini-2.0-flash",
        ),
    ):
        await generate_incident_playbook(
            table_fqn="db.schema.users",
            regulation="HIPAA",
        )

    mock_llm_client.chat.completions.create.assert_called_once()


@pytest.mark.asyncio
async def test_successful_playbook_uses_correct_regulation():
    """The returned regulation field must match the input parameter."""
    for regulation in ["GDPR", "HIPAA", "CCPA", "SOC2"]:
        mock_llm_client = MagicMock()
        mock_llm_client.chat.completions.create = AsyncMock(
            return_value=_make_llm_response(f"Playbook for {regulation}")
        )

        with (
            patch(
                "dataguardian.tools.playbook_generator.get_breach_impact_graph",
                new=AsyncMock(return_value=_make_breach_impact_success()),
            ),
            patch(
                "dataguardian.tools.playbook_generator.get_data_access_chain",
                new=AsyncMock(return_value=_make_access_chain_success()),
            ),
            patch(
                "dataguardian.tools.playbook_generator.llm_client.get_client",
                return_value=mock_llm_client,
            ),
            patch(
                "dataguardian.tools.playbook_generator.llm_client.get_model",
                return_value="gemini-2.0-flash",
            ),
        ):
            result = await generate_incident_playbook(
                table_fqn="db.schema.users",
                regulation=regulation,
            )

        assert result["regulation"] == regulation
        assert result["error"] is None
        assert result["playbook"] is not None


# ---------------------------------------------------------------------------
# Test: REGULATION_OBLIGATIONS constant
# ---------------------------------------------------------------------------

def test_regulation_obligations_contains_all_regulations():
    """REGULATION_OBLIGATIONS must contain entries for GDPR, HIPAA, CCPA, and SOC2."""
    assert "GDPR" in REGULATION_OBLIGATIONS
    assert "HIPAA" in REGULATION_OBLIGATIONS
    assert "CCPA" in REGULATION_OBLIGATIONS
    assert "SOC2" in REGULATION_OBLIGATIONS


def test_regulation_obligations_values_are_non_empty_strings():
    """All REGULATION_OBLIGATIONS values must be non-empty strings."""
    for regulation, obligation in REGULATION_OBLIGATIONS.items():
        assert isinstance(obligation, str), f"{regulation} obligation must be a string"
        assert len(obligation) > 0, f"{regulation} obligation must not be empty"
