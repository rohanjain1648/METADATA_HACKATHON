"""
Tool: monitor_tag_drift
Compares current column-level tags in OpenMetadata against a stored snapshot
to detect when sensitive tags have been removed (or added) since the baseline.

Workflow:
  - First run (no snapshot): fetches current tags, writes snapshot JSON, returns BASELINE_CREATED.
  - Subsequent runs: loads snapshot, fetches current tags, computes lost/gained tags.
  - Invalid snapshot file: returns ERROR without overwriting the file.
"""

import dataclasses
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from dataguardian import om_client


@dataclass
class ColumnSnapshot:
    """Snapshot of column-level tag assignments for a table at a point in time."""
    table_fqn: str
    snapshot_timestamp: str          # ISO 8601
    columns: dict[str, list[str]]    # column_name -> [tag_fqn, ...]


def _fetch_column_tags(table: dict) -> dict[str, list[str]]:
    """Extract column name -> list of tag FQNs from a table record."""
    result: dict[str, list[str]] = {}
    for col in table.get("columns", []):
        name = col.get("name", "")
        if not name:
            continue
        tags = [t.get("tagFQN", "") for t in col.get("tags", []) if t.get("tagFQN")]
        result[name] = tags
    return result


async def monitor_tag_drift(
    table_fqn: str,
    snapshot_path: str,
) -> dict:
    """
    Monitor a table for sensitive tag drift — detect removed or added column tags.

    On first run (no snapshot file), creates a baseline snapshot and returns
    BASELINE_CREATED. On subsequent runs, compares current tags against the
    snapshot and reports lost_tags and gained_tags.

    Args:
        table_fqn: Fully qualified name of the table to monitor.
        snapshot_path: File path to save/load the tag snapshot (JSON).

    Returns:
        Dict with table_fqn, snapshot_timestamp, drift_status, lost_tags,
        gained_tags, and error fields.
    """
    snapshot_exists = os.path.exists(snapshot_path)

    # ------------------------------------------------------------------
    # Branch 1: No snapshot file — create baseline
    # ------------------------------------------------------------------
    if not snapshot_exists:
        try:
            table = await om_client.get(
                f"/tables/name/{table_fqn}",
                params={"fields": "columns,name,fullyQualifiedName"},
            )
        except Exception as exc:
            return {
                "table_fqn": table_fqn,
                "snapshot_timestamp": None,
                "drift_status": "ERROR",
                "lost_tags": [],
                "gained_tags": [],
                "error": f"Failed to fetch table from OpenMetadata: {exc}",
            }

        columns = _fetch_column_tags(table)
        now_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        snapshot = ColumnSnapshot(
            table_fqn=table_fqn,
            snapshot_timestamp=now_ts,
            columns=columns,
        )

        try:
            with open(snapshot_path, "w", encoding="utf-8", newline="") as fh:
                json.dump(dataclasses.asdict(snapshot), fh, indent=2)
        except Exception as exc:
            return {
                "table_fqn": table_fqn,
                "snapshot_timestamp": None,
                "drift_status": "ERROR",
                "lost_tags": [],
                "gained_tags": [],
                "error": f"Failed to write snapshot file: {exc}",
            }

        return {
            "table_fqn": table_fqn,
            "snapshot_timestamp": now_ts,
            "drift_status": "BASELINE_CREATED",
            "lost_tags": [],
            "gained_tags": [],
            "error": None,
        }

    # ------------------------------------------------------------------
    # Branch 2: Snapshot file exists — try to parse it
    # ------------------------------------------------------------------
    try:
        with open(snapshot_path, "r", encoding="utf-8", newline="") as fh:
            raw = fh.read()
        snapshot_data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return {
            "table_fqn": table_fqn,
            "snapshot_timestamp": None,
            "drift_status": "ERROR",
            "lost_tags": [],
            "gained_tags": [],
            "error": f"Snapshot file contains invalid JSON: {exc}",
        }
    except Exception as exc:
        return {
            "table_fqn": table_fqn,
            "snapshot_timestamp": None,
            "drift_status": "ERROR",
            "lost_tags": [],
            "gained_tags": [],
            "error": f"Failed to read snapshot file: {exc}",
        }

    snapshot_timestamp = snapshot_data.get("snapshot_timestamp")
    snapshot_columns: dict[str, list[str]] = snapshot_data.get("columns", {})

    # ------------------------------------------------------------------
    # Branch 3: Valid snapshot — fetch current tags and compare
    # ------------------------------------------------------------------
    try:
        table = await om_client.get(
            f"/tables/name/{table_fqn}",
            params={"fields": "columns,name,fullyQualifiedName"},
        )
    except Exception as exc:
        return {
            "table_fqn": table_fqn,
            "snapshot_timestamp": snapshot_timestamp,
            "drift_status": "ERROR",
            "lost_tags": [],
            "gained_tags": [],
            "error": f"Failed to fetch table from OpenMetadata: {exc}",
        }

    current_columns = _fetch_column_tags(table)

    # Compute lost_tags: columns where current tags ⊂ snapshot tags
    # (i.e. some snapshot tags are no longer present)
    lost_tags: list[dict] = []
    for col_name, snap_tags in snapshot_columns.items():
        curr_tags = set(current_columns.get(col_name, []))
        snap_tags_set = set(snap_tags)
        removed = snap_tags_set - curr_tags
        if removed:
            lost_tags.append({
                "column": col_name,
                "removed_tags": sorted(removed),
            })

    # Compute gained_tags: columns where current tags ⊃ snapshot tags
    # (i.e. new tags have been added since the snapshot)
    gained_tags: list[dict] = []
    all_columns = set(snapshot_columns.keys()) | set(current_columns.keys())
    for col_name in all_columns:
        curr_tags = set(current_columns.get(col_name, []))
        snap_tags_set = set(snapshot_columns.get(col_name, []))
        added = curr_tags - snap_tags_set
        if added:
            gained_tags.append({
                "column": col_name,
                "added_tags": sorted(added),
            })

    drift_status = "DRIFT_DETECTED" if lost_tags else "NO_DRIFT"

    return {
        "table_fqn": table_fqn,
        "snapshot_timestamp": snapshot_timestamp,
        "drift_status": drift_status,
        "lost_tags": lost_tags,
        "gained_tags": gained_tags,
        "error": None,
    }
