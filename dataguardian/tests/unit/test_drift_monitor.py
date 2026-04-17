"""
Unit tests for dataguardian.tools.drift_monitor.

Tests:
  - BASELINE_CREATED when no snapshot file exists
  - ERROR returned and file unchanged when snapshot contains invalid JSON
  - DRIFT_DETECTED when a tag is removed from a column
  - NO_DRIFT when tags are unchanged
"""

import json
import os
import pytest
from unittest.mock import AsyncMock, patch

from dataguardian.tools.drift_monitor import monitor_tag_drift, ColumnSnapshot


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_table_response(columns: dict[str, list[str]]) -> dict:
    """Build a minimal OpenMetadata table response with the given column tags."""
    return {
        "columns": [
            {
                "name": col_name,
                "tags": [{"tagFQN": tag} for tag in tags],
            }
            for col_name, tags in columns.items()
        ]
    }


# ---------------------------------------------------------------------------
# Test: BASELINE_CREATED when no snapshot file exists
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_baseline_created_when_no_snapshot(tmp_path):
    """When no snapshot file exists, monitor_tag_drift must create one and return BASELINE_CREATED."""
    snapshot_path = str(tmp_path / "snapshot.json")
    table_columns = {
        "email": ["PII.Email", "PII.Sensitive"],
        "name": ["PII.Name"],
    }

    with patch(
        "dataguardian.tools.drift_monitor.om_client.get",
        new=AsyncMock(return_value=_make_table_response(table_columns)),
    ):
        result = await monitor_tag_drift(
            table_fqn="db.schema.users",
            snapshot_path=snapshot_path,
        )

    assert result["drift_status"] == "BASELINE_CREATED"
    assert result["error"] is None
    assert result["lost_tags"] == []
    assert result["gained_tags"] == []
    assert result["table_fqn"] == "db.schema.users"
    assert result["snapshot_timestamp"] is not None

    # Snapshot file must have been created
    assert os.path.exists(snapshot_path)

    with open(snapshot_path) as fh:
        saved = json.load(fh)

    assert saved["table_fqn"] == "db.schema.users"
    assert saved["columns"]["email"] == ["PII.Email", "PII.Sensitive"]
    assert saved["columns"]["name"] == ["PII.Name"]


@pytest.mark.asyncio
async def test_baseline_created_returns_error_on_write_failure(tmp_path):
    """When snapshot write fails, monitor_tag_drift must return ERROR."""
    # Use a path inside a non-existent directory to force a write failure
    snapshot_path = str(tmp_path / "nonexistent_dir" / "snapshot.json")
    table_columns = {"email": ["PII.Email"]}

    with patch(
        "dataguardian.tools.drift_monitor.om_client.get",
        new=AsyncMock(return_value=_make_table_response(table_columns)),
    ):
        result = await monitor_tag_drift(
            table_fqn="db.schema.users",
            snapshot_path=snapshot_path,
        )

    assert result["drift_status"] == "ERROR"
    assert result["error"] is not None
    assert "snapshot" in result["error"].lower() or "write" in result["error"].lower() or "No such file" in result["error"] or "FileNotFoundError" in result["error"]


# ---------------------------------------------------------------------------
# Test: ERROR returned and file unchanged when snapshot contains invalid JSON
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_error_on_invalid_json_snapshot(tmp_path):
    """When snapshot file contains invalid JSON, return ERROR without modifying the file."""
    snapshot_path = str(tmp_path / "snapshot.json")
    invalid_content = "this is not valid json {"

    with open(snapshot_path, "w") as fh:
        fh.write(invalid_content)

    result = await monitor_tag_drift(
        table_fqn="db.schema.users",
        snapshot_path=snapshot_path,
    )

    assert result["drift_status"] == "ERROR"
    assert result["error"] is not None
    assert "invalid" in result["error"].lower() or "json" in result["error"].lower()

    # File must be unchanged
    with open(snapshot_path) as fh:
        content_after = fh.read()
    assert content_after == invalid_content


@pytest.mark.asyncio
async def test_error_on_invalid_json_does_not_call_openmetadata(tmp_path):
    """When snapshot is invalid JSON, OpenMetadata must NOT be called."""
    snapshot_path = str(tmp_path / "snapshot.json")
    with open(snapshot_path, "w") as fh:
        fh.write("{bad json")

    mock_get = AsyncMock()
    with patch("dataguardian.tools.drift_monitor.om_client.get", new=mock_get):
        result = await monitor_tag_drift(
            table_fqn="db.schema.users",
            snapshot_path=snapshot_path,
        )

    mock_get.assert_not_called()
    assert result["drift_status"] == "ERROR"


# ---------------------------------------------------------------------------
# Test: DRIFT_DETECTED when a tag is removed from a column
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_drift_detected_when_tag_removed(tmp_path):
    """DRIFT_DETECTED must be returned when a column loses a tag since the snapshot."""
    snapshot_path = str(tmp_path / "snapshot.json")

    # Snapshot has PII.Email and PII.Sensitive on 'email' column
    snapshot = {
        "table_fqn": "db.schema.users",
        "snapshot_timestamp": "2024-01-15T10:30:00Z",
        "columns": {
            "email": ["PII.Email", "PII.Sensitive"],
            "name": ["PII.Name"],
        },
    }
    with open(snapshot_path, "w") as fh:
        json.dump(snapshot, fh)

    # Current state: PII.Sensitive was removed from 'email'
    current_columns = {
        "email": ["PII.Email"],
        "name": ["PII.Name"],
    }

    with patch(
        "dataguardian.tools.drift_monitor.om_client.get",
        new=AsyncMock(return_value=_make_table_response(current_columns)),
    ):
        result = await monitor_tag_drift(
            table_fqn="db.schema.users",
            snapshot_path=snapshot_path,
        )

    assert result["drift_status"] == "DRIFT_DETECTED"
    assert result["error"] is None
    assert result["snapshot_timestamp"] == "2024-01-15T10:30:00Z"

    # lost_tags must contain the 'email' column with 'PII.Sensitive' removed
    assert len(result["lost_tags"]) == 1
    lost = result["lost_tags"][0]
    assert lost["column"] == "email"
    assert "PII.Sensitive" in lost["removed_tags"]


@pytest.mark.asyncio
async def test_drift_detected_when_all_tags_removed_from_column(tmp_path):
    """DRIFT_DETECTED when all tags are removed from a column."""
    snapshot_path = str(tmp_path / "snapshot.json")

    snapshot = {
        "table_fqn": "db.schema.orders",
        "snapshot_timestamp": "2024-01-15T10:30:00Z",
        "columns": {
            "credit_card": ["PII.CreditCard", "PII.Financial"],
        },
    }
    with open(snapshot_path, "w") as fh:
        json.dump(snapshot, fh)

    # Current state: all tags removed from 'credit_card'
    current_columns = {"credit_card": []}

    with patch(
        "dataguardian.tools.drift_monitor.om_client.get",
        new=AsyncMock(return_value=_make_table_response(current_columns)),
    ):
        result = await monitor_tag_drift(
            table_fqn="db.schema.orders",
            snapshot_path=snapshot_path,
        )

    assert result["drift_status"] == "DRIFT_DETECTED"
    assert len(result["lost_tags"]) == 1
    assert set(result["lost_tags"][0]["removed_tags"]) == {"PII.CreditCard", "PII.Financial"}


# ---------------------------------------------------------------------------
# Test: NO_DRIFT when tags are unchanged
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_drift_when_tags_unchanged(tmp_path):
    """NO_DRIFT must be returned when current tags exactly match the snapshot."""
    snapshot_path = str(tmp_path / "snapshot.json")

    snapshot = {
        "table_fqn": "db.schema.users",
        "snapshot_timestamp": "2024-01-15T10:30:00Z",
        "columns": {
            "email": ["PII.Email"],
            "ssn": ["PII.SSN", "PII.Sensitive"],
        },
    }
    with open(snapshot_path, "w") as fh:
        json.dump(snapshot, fh)

    # Current state: identical to snapshot
    current_columns = {
        "email": ["PII.Email"],
        "ssn": ["PII.SSN", "PII.Sensitive"],
    }

    with patch(
        "dataguardian.tools.drift_monitor.om_client.get",
        new=AsyncMock(return_value=_make_table_response(current_columns)),
    ):
        result = await monitor_tag_drift(
            table_fqn="db.schema.users",
            snapshot_path=snapshot_path,
        )

    assert result["drift_status"] == "NO_DRIFT"
    assert result["lost_tags"] == []
    assert result["error"] is None


@pytest.mark.asyncio
async def test_no_drift_with_empty_columns(tmp_path):
    """NO_DRIFT must be returned when both snapshot and current state have no tags."""
    snapshot_path = str(tmp_path / "snapshot.json")

    snapshot = {
        "table_fqn": "db.schema.empty",
        "snapshot_timestamp": "2024-01-15T10:30:00Z",
        "columns": {},
    }
    with open(snapshot_path, "w") as fh:
        json.dump(snapshot, fh)

    with patch(
        "dataguardian.tools.drift_monitor.om_client.get",
        new=AsyncMock(return_value={"columns": []}),
    ):
        result = await monitor_tag_drift(
            table_fqn="db.schema.empty",
            snapshot_path=snapshot_path,
        )

    assert result["drift_status"] == "NO_DRIFT"
    assert result["lost_tags"] == []
    assert result["gained_tags"] == []


# ---------------------------------------------------------------------------
# Test: gained_tags reported when new tags are added
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_gained_tags_reported_when_new_tag_added(tmp_path):
    """gained_tags must be populated when a column gains a new tag since the snapshot."""
    snapshot_path = str(tmp_path / "snapshot.json")

    snapshot = {
        "table_fqn": "db.schema.users",
        "snapshot_timestamp": "2024-01-15T10:30:00Z",
        "columns": {
            "email": ["PII.Email"],
        },
    }
    with open(snapshot_path, "w") as fh:
        json.dump(snapshot, fh)

    # Current state: PII.Sensitive was added to 'email'
    current_columns = {"email": ["PII.Email", "PII.Sensitive"]}

    with patch(
        "dataguardian.tools.drift_monitor.om_client.get",
        new=AsyncMock(return_value=_make_table_response(current_columns)),
    ):
        result = await monitor_tag_drift(
            table_fqn="db.schema.users",
            snapshot_path=snapshot_path,
        )

    # No lost tags → NO_DRIFT (gained tags alone don't trigger DRIFT_DETECTED)
    assert result["drift_status"] == "NO_DRIFT"
    assert result["lost_tags"] == []
    assert len(result["gained_tags"]) == 1
    gained = result["gained_tags"][0]
    assert gained["column"] == "email"
    assert "PII.Sensitive" in gained["added_tags"]


# ---------------------------------------------------------------------------
# Test: ColumnSnapshot dataclass fields
# ---------------------------------------------------------------------------

def test_column_snapshot_dataclass_fields():
    """ColumnSnapshot must have table_fqn, snapshot_timestamp, and columns fields."""
    snap = ColumnSnapshot(
        table_fqn="db.schema.users",
        snapshot_timestamp="2024-01-15T10:30:00Z",
        columns={"email": ["PII.Email"]},
    )
    assert snap.table_fqn == "db.schema.users"
    assert snap.snapshot_timestamp == "2024-01-15T10:30:00Z"
    assert snap.columns == {"email": ["PII.Email"]}
