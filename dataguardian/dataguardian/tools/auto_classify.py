"""
Tool: auto_classify_table
Fetches a table's schema from OpenMetadata, sends column names + sample descriptions
to an LLM for PII/sensitivity detection, then writes tags back to OpenMetadata.
This is the closed-loop governance feature — discovery to tagging in one shot.
"""

import json
from dataguardian import om_client
from dataguardian.llm_client import get_client, get_model
from dataguardian.config import load_tag_map

TAG_MAP = load_tag_map()

CLASSIFICATION_PROMPT = """You are a data privacy expert. Analyze the following table columns and identify which ones contain sensitive or PII data.

Table: {table_name}
Columns:
{columns}

For each column that contains sensitive data, return a JSON array of objects with:
- "column": column name
- "category": one of [email, phone, ssn, name, address, date_of_birth, credit_card, ip_address, location, health, financial, password, token]
- "confidence": high | medium | low
- "reason": brief explanation

Return ONLY the JSON array, no other text. If no sensitive columns found, return [].
"""


async def auto_classify_table(
    table_fqn: str,
    dry_run: bool = False,
) -> dict:
    """
    Auto-classify a table's columns for PII/sensitivity using LLM, then tag in OpenMetadata.

    Args:
        table_fqn: Fully qualified name of the table (e.g. mysql.prod.analytics.users).
        dry_run: If True, returns what would be tagged without writing to OpenMetadata.

    Returns:
        Classification results and list of tags applied.
    """
    # 1. Fetch table schema
    table = await om_client.get(
        f"/tables/name/{table_fqn}",
        params={"fields": "columns,name,description,fullyQualifiedName,id"},
    )

    columns = table.get("columns", [])
    table_id = table["id"]

    if not columns:
        return {"error": "No columns found for table", "fqn": table_fqn}

    # 2. Build column summary for LLM
    col_summary = "\n".join(
        f"- {c['name']} ({c.get('dataType', 'unknown')}): {c.get('description', 'no description')}"
        for c in columns
    )

    # 3. Ask LLM to classify
    client = get_client()
    response = await client.chat.completions.create(
        model=get_model(),
        messages=[{
            "role": "user",
            "content": CLASSIFICATION_PROMPT.format(
                table_name=table_fqn,
                columns=col_summary,
            ),
        }],
        temperature=0,
    )

    raw = response.choices[0].message.content.strip()

    try:
        classifications = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "LLM returned invalid JSON", "raw_response": raw}

    if not classifications:
        return {
            "table": table_fqn,
            "message": "No sensitive columns detected",
            "classifications": [],
        }

    # 4. Build tag patches for each sensitive column
    tags_applied = []
    column_patches = []

    for clf in classifications:
        col_name = clf.get("column")
        category = clf.get("category", "").lower()
        tag_fqn = TAG_MAP.get(category)

        if not tag_fqn or not col_name:
            continue

        # Find column index in schema
        col_idx = next(
            (i for i, c in enumerate(columns) if c["name"] == col_name), None
        )
        if col_idx is None:
            continue

        column_patches.append({
            "op": "add",
            "path": f"/columns/{col_idx}/tags/-",
            "value": {
                "tagFQN": tag_fqn,
                "source": "Classification",
                "labelType": "Automated",
                "state": "Suggested",
            },
        })

        tags_applied.append({
            "column": col_name,
            "tag": tag_fqn,
            "confidence": clf.get("confidence"),
            "reason": clf.get("reason"),
        })

    # 5. Write tags back to OpenMetadata (unless dry_run)
    if not dry_run and column_patches:
        await om_client.patch(f"/tables/{table_id}", column_patches)

    return {
        "table": table_fqn,
        "dry_run": dry_run,
        "columns_analyzed": len(columns),
        "sensitive_columns_found": len(tags_applied),
        "tags_applied": tags_applied,
        "written_to_openmetadata": not dry_run and len(column_patches) > 0,
    }
