"""
LLM-powered PII classifier.
Given a list of column names + descriptions, returns which ones contain PII
and which OpenMetadata tag FQNs to apply.
"""

import os
import json
from openai import AsyncOpenAI

_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

# Map PII categories to OpenMetadata standard tag FQNs
PII_TAG_MAP = {
    "email": "PII.Sensitive",
    "phone": "PII.Sensitive",
    "ssn": "PII.Sensitive",
    "credit_card": "PII.Sensitive",
    "password": "PII.Sensitive",
    "name": "PII.NonSensitive",
    "address": "PII.Sensitive",
    "date_of_birth": "PII.Sensitive",
    "ip_address": "PII.Sensitive",
    "location": "PII.NonSensitive",
    "user_id": "PII.NonSensitive",
    "none": None,
}

SYSTEM_PROMPT = """You are a data privacy expert. Given a list of database column names and descriptions,
identify which columns contain Personally Identifiable Information (PII).

For each column, respond with a JSON array of objects:
{
  "column_name": "<name>",
  "pii_category": "<one of: email, phone, ssn, credit_card, password, name, address, date_of_birth, ip_address, location, user_id, none>",
  "confidence": "<high|medium|low>",
  "reason": "<brief explanation>"
}

Be conservative — if unsure, lean toward flagging as PII."""


async def classify_columns(columns: list[dict]) -> list[dict]:
    """
    columns: list of {"name": str, "description": str, "dataType": str}
    returns: list of {"column_name", "pii_category", "tag_fqn", "confidence", "reason"}
    """
    col_text = "\n".join(
        f"- {c.get('name', '')} (type: {c.get('dataType', 'unknown')}): {c.get('description', 'no description')}"
        for c in columns
    )

    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Classify these columns:\n{col_text}"},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    raw = response.choices[0].message.content
    parsed = json.loads(raw)

    # Handle both {"results": [...]} and direct array responses
    results = parsed if isinstance(parsed, list) else parsed.get("results", list(parsed.values())[0] if parsed else [])

    enriched = []
    for item in results:
        category = item.get("pii_category", "none").lower()
        tag_fqn = PII_TAG_MAP.get(category)
        enriched.append({**item, "tag_fqn": tag_fqn})

    return enriched


async def generate_compliance_summary(assets: list[dict], regulation: str) -> str:
    """Generate a human-readable compliance report from a list of asset metadata dicts."""
    assets_text = json.dumps(assets, indent=2)

    prompt = f"""You are a data compliance officer. Based on the following data assets from OpenMetadata,
generate a {regulation} compliance inventory report.

Include:
1. Executive summary of data processing activities
2. Table of assets with: name, data type, sensitivity, owner, purpose
3. Risk assessment — assets with no owner or no quality tests
4. Recommended remediation actions

Data assets:
{assets_text}

Format the output as clean markdown."""

    response = await _client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return response.choices[0].message.content
