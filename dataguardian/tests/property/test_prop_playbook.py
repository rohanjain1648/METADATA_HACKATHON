"""
Property-based tests for dataguardian.tools.playbook_generator.

# Feature: dataguardian-enhancements

Properties tested:
  Property 22: Playbook generator response completeness (all required fields non-null on success)
  Property 23: Playbook generator short-circuits on dependency error (LLM not called when
               breach_impact or data_access_chain returns error)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dataguardian.tools.playbook_generator import generate_incident_playbook, REGULATION_OBLIGATIONS


# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

_regulation_strategy = st.sampled_from(["GDPR", "HIPAA", "CCPA", "SOC2"])

_fqn_strategy = st.from_regex(
    r"[a-z][a-z0-9]{1,8}\.[a-z][a-z0-9]{1,8}\.[a-z][a-z0-9]{1,12}",
    fullmatch=True,
)

_owner_name_strategy = st.from_regex(r"[a-z][a-z0-9]{2,10}", fullmatch=True)

_notification_list_strategy = st.lists(
    _owner_name_strategy,
    min_size=0,
    max_size=5,
    unique=True,
)

_entity_type_strategy = st.sampled_from(["table", "dashboard", "pipeline"])

_asset_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{2,15}", fullmatch=True)

_error_message_strategy = st.text(min_size=5, max_size=100).filter(
    lambda s: s.strip() != ""
)

_playbook_text_strategy = st.text(min_size=10, max_size=500).filter(
    lambda s: s.strip() != ""
)


def _make_breach_impact_success(total_affected: int, notification_list: list[str]) -> dict:
    """Build a minimal successful breach_impact response."""
    return {
        "breached_asset": "db.schema.users",
        "direction": "downstream",
        "total_affected": total_affected,
        "owners_to_notify": notification_list,
        "affected_by_type": {"table": ["db.schema.orders"]} if total_affected > 0 else {},
        "nodes": [],
        "edges": [],
    }


def _make_access_chain_success(notification_list: list[str]) -> dict:
    """Build a minimal successful access_chain response."""
    return {
        "table": "db.schema.users",
        "direct_owner": None,
        "owner_details": None,
        "followers": [],
        "domain": None,
        "data_products": [],
        "downstream_asset_count": len(notification_list),
        "downstream_owners": notification_list,
        "downstream_owner_details": [],
        "notification_list": notification_list,
    }


def _make_llm_response(text: str) -> MagicMock:
    """Build a mock LLM response."""
    mock_message = MagicMock()
    mock_message.content = text
    mock_choice = MagicMock()
    mock_choice.message = mock_message
    mock_response = MagicMock()
    mock_response.choices = [mock_choice]
    return mock_response


# ---------------------------------------------------------------------------
# Property 22: Playbook generator response completeness
# Validates: Requirements 11.5
# ---------------------------------------------------------------------------

@given(
    table_fqn=_fqn_strategy,
    regulation=_regulation_strategy,
    total_affected=st.integers(min_value=0, max_value=50),
    notification_list=_notification_list_strategy,
    playbook_text=_playbook_text_strategy,
    incident_description=st.one_of(st.none(), st.text(min_size=5, max_size=100)),
)
@settings(max_examples=10)
def test_property22_response_completeness_on_success(
    table_fqn,
    regulation,
    total_affected,
    notification_list,
    playbook_text,
    incident_description,
):
    """
    Property 22: Playbook generator response completeness.

    For any successful call to generate_incident_playbook (where neither breach_impact
    nor data_access_chain returns an error), the response SHALL contain non-null values
    for breached_asset, total_affected_assets, notification_list, regulation, and playbook.

    Validates: Requirements 11.5
    """
    mock_llm_client = MagicMock()
    mock_llm_client.chat.completions.create = AsyncMock(
        return_value=_make_llm_response(playbook_text)
    )

    with (
        patch(
            "dataguardian.tools.playbook_generator.get_breach_impact_graph",
            new=AsyncMock(
                return_value=_make_breach_impact_success(total_affected, notification_list)
            ),
        ),
        patch(
            "dataguardian.tools.playbook_generator.get_data_access_chain",
            new=AsyncMock(
                return_value=_make_access_chain_success(notification_list)
            ),
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
        result = asyncio.run(
            generate_incident_playbook(
                table_fqn=table_fqn,
                regulation=regulation,
                incident_description=incident_description,
            )
        )

    # All required fields must be present
    required_fields = [
        "breached_asset",
        "regulation",
        "total_affected_assets",
        "notification_list",
        "playbook",
        "error",
    ]
    for field in required_fields:
        assert field in result, f"Required field '{field}' missing from response"

    # On success, these fields must be non-null
    assert result["breached_asset"] is not None, "breached_asset must be non-null on success"
    assert result["regulation"] is not None, "regulation must be non-null on success"
    assert result["total_affected_assets"] is not None, "total_affected_assets must be non-null on success"
    assert result["notification_list"] is not None, "notification_list must be non-null on success"
    assert result["playbook"] is not None, "playbook must be non-null on success"

    # Values must match inputs
    assert result["breached_asset"] == table_fqn, (
        f"breached_asset mismatch: expected {table_fqn}, got {result['breached_asset']}"
    )
    assert result["regulation"] == regulation, (
        f"regulation mismatch: expected {regulation}, got {result['regulation']}"
    )
    assert result["total_affected_assets"] == total_affected, (
        f"total_affected_assets mismatch: expected {total_affected}, got {result['total_affected_assets']}"
    )
    assert result["notification_list"] == notification_list, (
        f"notification_list mismatch: expected {notification_list}, got {result['notification_list']}"
    )
    assert result["playbook"] == playbook_text, (
        f"playbook text mismatch: expected {playbook_text!r}, got {result['playbook']!r}"
    )
    assert result["error"] is None, f"error must be None on success, got {result['error']}"


# ---------------------------------------------------------------------------
# Property 23: Playbook generator short-circuits on dependency error
# Validates: Requirements 11.6
# ---------------------------------------------------------------------------

@given(
    table_fqn=_fqn_strategy,
    regulation=_regulation_strategy,
    error_message=_error_message_strategy,
)
@settings(max_examples=10)
def test_property23_short_circuit_on_breach_impact_error(
    table_fqn,
    regulation,
    error_message,
):
    """
    Property 23 (breach_impact branch): Playbook generator short-circuits on dependency error.

    For any call to generate_incident_playbook where breach_impact returns a response
    containing an "error" key, the LLM SHALL NOT be invoked and the response SHALL
    surface the error.

    Validates: Requirements 11.6
    """
    mock_llm_client = MagicMock()
    mock_llm_client.chat.completions.create = AsyncMock()

    with (
        patch(
            "dataguardian.tools.playbook_generator.get_breach_impact_graph",
            new=AsyncMock(return_value={"error": error_message}),
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
        result = asyncio.run(
            generate_incident_playbook(
                table_fqn=table_fqn,
                regulation=regulation,
            )
        )

    # LLM must NOT have been called
    mock_llm_client.chat.completions.create.assert_not_called()

    # data_access_chain must NOT have been called
    mock_access_chain.assert_not_called()

    # Response must surface the error
    assert result["error"] == error_message, (
        f"error mismatch: expected {error_message!r}, got {result['error']!r}"
    )
    assert result["playbook"] is None, (
        f"playbook must be None when breach_impact errors, got {result['playbook']!r}"
    )

    # Required fields must still be present
    assert result["breached_asset"] == table_fqn
    assert result["regulation"] == regulation
    assert result["total_affected_assets"] == 0
    assert result["notification_list"] == []


@given(
    table_fqn=_fqn_strategy,
    regulation=_regulation_strategy,
    error_message=_error_message_strategy,
)
@settings(max_examples=10)
def test_property23_short_circuit_on_data_access_chain_error(
    table_fqn,
    regulation,
    error_message,
):
    """
    Property 23 (data_access_chain branch): Playbook generator short-circuits on dependency error.

    For any call to generate_incident_playbook where data_access_chain returns a response
    containing an "error" key, the LLM SHALL NOT be invoked and the response SHALL
    surface the error.

    Validates: Requirements 11.6
    """
    mock_llm_client = MagicMock()
    mock_llm_client.chat.completions.create = AsyncMock()

    with (
        patch(
            "dataguardian.tools.playbook_generator.get_breach_impact_graph",
            new=AsyncMock(
                return_value=_make_breach_impact_success(
                    total_affected=2,
                    notification_list=["owner1"],
                )
            ),
        ),
        patch(
            "dataguardian.tools.playbook_generator.get_data_access_chain",
            new=AsyncMock(return_value={"error": error_message}),
        ),
        patch(
            "dataguardian.tools.playbook_generator.llm_client.get_client",
            return_value=mock_llm_client,
        ),
    ):
        result = asyncio.run(
            generate_incident_playbook(
                table_fqn=table_fqn,
                regulation=regulation,
            )
        )

    # LLM must NOT have been called
    mock_llm_client.chat.completions.create.assert_not_called()

    # Response must surface the error
    assert result["error"] == error_message, (
        f"error mismatch: expected {error_message!r}, got {result['error']!r}"
    )
    assert result["playbook"] is None, (
        f"playbook must be None when data_access_chain errors, got {result['playbook']!r}"
    )

    # Required fields must still be present
    assert result["breached_asset"] == table_fqn
    assert result["regulation"] == regulation
    assert result["total_affected_assets"] == 0
    assert result["notification_list"] == []
