"""
Property-based tests for dataguardian.tools.drift_monitor.

# Feature: dataguardian-enhancements

Properties tested:
  Property 19: Drift monitor snapshot round-trip
  Property 20: Drift monitor lost-tag detection and status consistency
  Property 21: Drift monitor invalid snapshot file is not overwritten
"""

import asyncio
import dataclasses
import json
import os
import tempfile
from unittest.mock import AsyncMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from dataguardian.tools.drift_monitor import monitor_tag_drift, ColumnSnapshot


# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# Strategy for a single tag FQN (e.g. "PII.Email")
_tag_fqn_strategy = st.from_regex(r"[A-Za-z]{2,10}\.[A-Za-z]{2,15}", fullmatch=True)

# Strategy for a column name
_col_name_strategy = st.from_regex(r"[a-z][a-z0-9_]{0,19}", fullmatch=True)

# Strategy for a columns dict: column_name -> list of tag FQNs
_columns_strategy = st.dictionaries(
    keys=_col_name_strategy,
    values=st.lists(_tag_fqn_strategy, min_size=0, max_size=4),
    min_size=0,
    max_size=6,
)


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
# Property 19: Drift monitor snapshot round-trip
# Validates: Requirements 10.3, 10.5
# ---------------------------------------------------------------------------

@given(
    table_fqn=st.from_regex(r"[a-z]{2,8}\.[a-z]{2,8}\.[a-z]{2,12}", fullmatch=True),
    columns=_columns_strategy,
)
@settings(max_examples=10)
def test_property19_snapshot_round_trip(table_fqn, columns):
    """
    Property 19: Drift monitor snapshot round-trip.

    Creating a baseline snapshot (when no snapshot file exists) and then reading
    back the snapshot file SHALL produce a valid JSON document whose `columns`
    mapping exactly matches the column tags fetched from OpenMetadata at the time
    of baseline creation.

    Validates: Requirements 10.3, 10.5
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_path = os.path.join(tmpdir, "snapshot.json")

        with patch(
            "dataguardian.tools.drift_monitor.om_client.get",
            new=AsyncMock(return_value=_make_table_response(columns)),
        ):
            result = asyncio.run(
                monitor_tag_drift(table_fqn=table_fqn, snapshot_path=snapshot_path)
            )

        assert result["drift_status"] == "BASELINE_CREATED", (
            f"Expected BASELINE_CREATED, got {result['drift_status']}"
        )

        # Snapshot file must exist and be valid JSON
        assert os.path.exists(snapshot_path), "Snapshot file must be created"

        with open(snapshot_path, "r", encoding="utf-8") as fh:
            saved = json.load(fh)

        # table_fqn must match
        assert saved["table_fqn"] == table_fqn, (
            f"Snapshot table_fqn mismatch: expected {table_fqn}, got {saved['table_fqn']}"
        )

        # snapshot_timestamp must be present
        assert "snapshot_timestamp" in saved and saved["snapshot_timestamp"], (
            "Snapshot must contain a non-empty snapshot_timestamp"
        )

        # columns mapping must exactly match what was fetched
        saved_columns = saved.get("columns", {})
        for col_name, tags in columns.items():
            assert col_name in saved_columns, (
                f"Column '{col_name}' missing from snapshot"
            )
            assert set(saved_columns[col_name]) == set(tags), (
                f"Tags for column '{col_name}' mismatch: "
                f"expected {set(tags)}, got {set(saved_columns[col_name])}"
            )


# ---------------------------------------------------------------------------
# Property 20: Drift monitor lost-tag detection and status consistency
# Validates: Requirements 10.2, 10.4
# ---------------------------------------------------------------------------

@given(
    table_fqn=st.from_regex(r"[a-z]{2,8}\.[a-z]{2,8}\.[a-z]{2,12}", fullmatch=True),
    snapshot_columns=_columns_strategy,
    current_columns=_columns_strategy,
)
@settings(max_examples=10)
def test_property20_lost_tag_detection_and_status_consistency(
    table_fqn, snapshot_columns, current_columns
):
    """
    Property 20: Drift monitor lost-tag detection and status consistency.

    For any snapshot and any current column tag state, monitor_tag_drift SHALL
    report in lost_tags exactly the columns whose tag sets have shrunk since the
    snapshot, and drift_status SHALL be DRIFT_DETECTED if and only if lost_tags
    is non-empty.

    Validates: Requirements 10.2, 10.4
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_path = os.path.join(tmpdir, "snapshot.json")

        # Write the snapshot file directly
        snapshot_data = {
            "table_fqn": table_fqn,
            "snapshot_timestamp": "2024-01-15T10:30:00Z",
            "columns": snapshot_columns,
        }
        with open(snapshot_path, "w", encoding="utf-8") as fh:
            json.dump(snapshot_data, fh)

        with patch(
            "dataguardian.tools.drift_monitor.om_client.get",
            new=AsyncMock(return_value=_make_table_response(current_columns)),
        ):
            result = asyncio.run(
                monitor_tag_drift(table_fqn=table_fqn, snapshot_path=snapshot_path)
            )

    assert result["drift_status"] in ("DRIFT_DETECTED", "NO_DRIFT"), (
        f"Unexpected drift_status: {result['drift_status']}"
    )

    # Compute expected lost_tags manually
    expected_lost: dict[str, set] = {}
    for col_name, snap_tags in snapshot_columns.items():
        curr_tags = set(current_columns.get(col_name, []))
        snap_tags_set = set(snap_tags)
        removed = snap_tags_set - curr_tags
        if removed:
            expected_lost[col_name] = removed

    # lost_tags in result must match expected
    result_lost: dict[str, set] = {
        entry["column"]: set(entry["removed_tags"])
        for entry in result["lost_tags"]
    }
    assert result_lost == expected_lost, (
        f"lost_tags mismatch:\n  expected: {expected_lost}\n  got: {result_lost}"
    )

    # drift_status consistency: DRIFT_DETECTED iff lost_tags non-empty
    if expected_lost:
        assert result["drift_status"] == "DRIFT_DETECTED", (
            f"Expected DRIFT_DETECTED when lost_tags={expected_lost}, "
            f"got {result['drift_status']}"
        )
    else:
        assert result["drift_status"] == "NO_DRIFT", (
            f"Expected NO_DRIFT when no lost_tags, got {result['drift_status']}"
        )


# ---------------------------------------------------------------------------
# Property 21: Drift monitor invalid snapshot file is not overwritten
# Validates: Requirements 10.6
# ---------------------------------------------------------------------------

@given(
    table_fqn=st.from_regex(r"[a-z]{2,8}\.[a-z]{2,8}\.[a-z]{2,12}", fullmatch=True),
    invalid_content=st.text(min_size=1, max_size=200).filter(
        lambda s: _is_invalid_json(s)
    ),
)
@settings(max_examples=10)
def test_property21_invalid_snapshot_not_overwritten(table_fqn, invalid_content):
    """
    Property 21: Drift monitor invalid snapshot file is not overwritten.

    For any file path containing a string that is not valid JSON, calling
    monitor_tag_drift SHALL return a response with drift_status = "ERROR" and
    SHALL leave the file contents unchanged.

    Validates: Requirements 10.6
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        snapshot_path = os.path.join(tmpdir, "snapshot.json")

        with open(snapshot_path, "w", encoding="utf-8", newline="") as fh:
            fh.write(invalid_content)

        result = asyncio.run(
            monitor_tag_drift(table_fqn=table_fqn, snapshot_path=snapshot_path)
        )

        # Must return ERROR
        assert result["drift_status"] == "ERROR", (
            f"Expected ERROR for invalid JSON, got {result['drift_status']}"
        )
        assert result["error"] is not None, "error field must be non-None for ERROR status"

        # File must be unchanged
        with open(snapshot_path, "r", encoding="utf-8", newline="") as fh:
            content_after = fh.read()

        assert content_after == invalid_content, (
            "Snapshot file must not be modified when it contains invalid JSON"
        )


def _is_invalid_json(s: str) -> bool:
    """Return True if s is NOT valid JSON."""
    try:
        json.loads(s)
        return False
    except (json.JSONDecodeError, ValueError):
        return True
