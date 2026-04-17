"""
config.py — Externalizable TAG_MAP and REGULATION_TAGS for DataGuardian.

Loads tag/regulation mappings from env-specified JSON files, falling back
to built-in defaults when the env var is unset, the file is absent, or
the file contains invalid JSON.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Built-in defaults
# ---------------------------------------------------------------------------

DEFAULT_TAG_MAP: dict[str, str | None] = {
    "email": "PII.Email",
    "phone": "PII.Phone",
    "ssn": "PII.SSN",
    "name": "PII.Name",
    "address": "PII.Address",
    "date_of_birth": "PII.DateOfBirth",
    "credit_card": "PII.CreditCard",
    "ip_address": "PII.IPAddress",
    "location": "PII.Location",
    "health": "PHI.HealthData",
    "financial": "Sensitive.Financial",
    "password": "Sensitive.Credential",
    "token": "Sensitive.Credential",
}

DEFAULT_REGULATION_TAGS: dict[str, list[str]] = {
    "GDPR": ["PII", "GDPR", "Sensitive"],
    "HIPAA": ["PHI", "HIPAA", "HealthData"],
    "CCPA": ["PII", "CCPA", "Sensitive"],
    "SOC2": ["Sensitive", "Confidential"],
}


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_tag_map() -> dict[str, str | None]:
    """
    Load TAG_MAP from the file path specified by DATAGUARDIAN_TAG_MAP_PATH.

    - If the env var is unset or the file does not exist: return DEFAULT_TAG_MAP silently.
    - If the file exists and contains valid JSON: return the parsed dict.
    - If the file exists but contains invalid JSON: log an error and return DEFAULT_TAG_MAP.
    """
    path = os.environ.get("DATAGUARDIAN_TAG_MAP_PATH")
    if not path:
        return DEFAULT_TAG_MAP

    if not os.path.exists(path):
        return DEFAULT_TAG_MAP

    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        logger.error(
            "DATAGUARDIAN_TAG_MAP_PATH points to a file with invalid JSON (%s): %s. "
            "Falling back to DEFAULT_TAG_MAP.",
            path,
            exc,
        )
        return DEFAULT_TAG_MAP


def load_regulation_tags() -> dict[str, list[str]]:
    """
    Load REGULATION_TAGS from the file path specified by DATAGUARDIAN_REGULATION_TAGS_PATH.

    - If the env var is unset or the file does not exist: return DEFAULT_REGULATION_TAGS silently.
    - If the file exists and contains valid JSON: return the parsed dict.
    - If the file exists but contains invalid JSON: log an error and return DEFAULT_REGULATION_TAGS.
    """
    path = os.environ.get("DATAGUARDIAN_REGULATION_TAGS_PATH")
    if not path:
        return DEFAULT_REGULATION_TAGS

    if not os.path.exists(path):
        return DEFAULT_REGULATION_TAGS

    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        logger.error(
            "DATAGUARDIAN_REGULATION_TAGS_PATH points to a file with invalid JSON (%s): %s. "
            "Falling back to DEFAULT_REGULATION_TAGS.",
            path,
            exc,
        )
        return DEFAULT_REGULATION_TAGS
