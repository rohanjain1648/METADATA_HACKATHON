"""
Tool: generate_incident_playbook
Combines breach impact analysis, access chain resolution, and regulation-specific
obligations to produce a ready-to-send incident response playbook.
"""

from dataguardian.tools.breach_impact import get_breach_impact_graph
from dataguardian.tools.access_chain import get_data_access_chain
from dataguardian import llm_client


REGULATION_OBLIGATIONS = {
    "GDPR": "Notify supervisory authority within 72 hours (Article 33). Notify affected individuals without undue delay if high risk (Article 34).",
    "HIPAA": "Notify affected individuals within 60 days. Notify HHS. If >500 individuals, notify prominent media.",
    "CCPA": "No mandatory breach notification timeline, but California breach notification law (Civil Code 1798.82) requires expedient notification.",
    "SOC2": "Follow contractual SLA for customer notification. Document incident in audit trail.",
}


async def generate_incident_playbook(
    table_fqn: str,
    regulation: str = "GDPR",
    incident_description: str | None = None,
) -> dict:
    """
    Generate a complete incident response playbook for a breached data asset.

    Combines breach impact analysis, access chain resolution, and regulation-specific
    obligations to produce a ready-to-send notification draft.

    Args:
        table_fqn: Fully qualified name of the breached asset.
        regulation: GDPR | HIPAA | CCPA | SOC2 (default GDPR).
        incident_description: Optional context about the incident for the LLM.

    Returns:
        Structured playbook dict with breached_asset, regulation, total_affected_assets,
        notification_list, playbook text, and error.
    """
    # Step 1: Get breach impact graph
    breach_impact = await get_breach_impact_graph(
        fqn=table_fqn,
        direction="downstream",
        depth=5,
    )
    if "error" in breach_impact:
        return {
            "breached_asset": table_fqn,
            "regulation": regulation,
            "total_affected_assets": 0,
            "notification_list": [],
            "playbook": None,
            "error": breach_impact["error"],
        }

    # Step 2: Get data access chain
    access_chain = await get_data_access_chain(table_fqn=table_fqn)
    if "error" in access_chain:
        return {
            "breached_asset": table_fqn,
            "regulation": regulation,
            "total_affected_assets": 0,
            "notification_list": [],
            "playbook": None,
            "error": access_chain["error"],
        }

    # Step 3: Build LLM prompt
    total_affected = breach_impact.get("total_affected", 0)
    notification_list = access_chain.get("notification_list", [])
    obligations = REGULATION_OBLIGATIONS.get(
        regulation,
        "Follow applicable regulatory requirements for breach notification.",
    )

    # Build affected assets summary
    affected_by_type = breach_impact.get("affected_by_type", {})
    affected_assets_lines = []
    for entity_type, names in affected_by_type.items():
        for name in names:
            affected_assets_lines.append(f"  - [{entity_type}] {name}")
    affected_assets_text = "\n".join(affected_assets_lines) if affected_assets_lines else "  (none)"

    notification_text = "\n".join(f"  - {n}" for n in notification_list) if notification_list else "  (none)"

    incident_context = (
        f"Incident description: {incident_description}"
        if incident_description
        else "No additional incident description provided."
    )

    prompt = f"""You are a data breach incident response specialist. Generate a comprehensive incident response playbook in Markdown format.

## Incident Details
- Breached Asset: {table_fqn}
- Regulation: {regulation}
- {incident_context}

## Regulatory Obligations
{obligations}

## Affected Assets ({total_affected} total)
{affected_assets_text}

## Notification List
{notification_text}

## Instructions
Generate a detailed incident response playbook that includes:
1. **Incident Summary** — brief description of the breach and its scope
2. **Immediate Actions** — steps to take in the first hour (containment, evidence preservation)
3. **Affected Assets** — list of all downstream assets impacted
4. **Notification Plan** — who to notify, when, and how (per {regulation} obligations)
5. **Regulatory Timeline** — specific deadlines and requirements for {regulation}
6. **Communication Templates** — draft notification messages for stakeholders
7. **Post-Incident Actions** — remediation steps and lessons learned

Be specific, actionable, and reference the {regulation} obligations above.
"""

    # Step 4: Call LLM to generate playbook text
    client = llm_client.get_client()
    model = llm_client.get_model()

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": prompt,
            }
        ],
    )
    playbook_text = response.choices[0].message.content

    # Step 5: Return structured result
    return {
        "breached_asset": table_fqn,
        "regulation": regulation,
        "total_affected_assets": total_affected,
        "notification_list": notification_list,
        "playbook": playbook_text,
        "error": None,
    }
