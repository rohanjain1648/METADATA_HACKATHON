"""
Property-based tests for dataguardian.config.

# Feature: dataguardian-enhancements

Properties tested:
  Property 9: Config loading round-trip
  Property 10: Invalid JSON config falls back to built-in default
"""

import json
import os
import tempfile
from contextlib import contextmanager

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from dataguardian.config import DEFAULT_TAG_MAP, DEFAULT_REGULATION_TAGS, load_tag_map, load_regulation_tags


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _is_valid_json(s: str) -> bool:
    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


@contextmanager
def _env_var(name: str, value: str):
    """Context manager to temporarily set an env var and restore it afterwards."""
    old = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if old is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = old


# ---------------------------------------------------------------------------
# Property 9: Config loading round-trip
# Validates: Requirements 5.1, 5.2
# ---------------------------------------------------------------------------

@given(
    data=st.dictionaries(
        st.text(min_size=1, max_size=10),
        st.text(max_size=20),
        max_size=5,
    )
)
@settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property9_load_tag_map_round_trip(data):
    """
    Property 9: Config loading round-trip.
    For any valid JSON dict written to a temp file and referenced via env var,
    load_tag_map() returns a dict equal to the written dict.
    Validates: Requirements 5.1, 5.2
    """
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

        with _env_var("DATAGUARDIAN_TAG_MAP_PATH", path):
            result = load_tag_map()

        assert result == data
    finally:
        if os.path.exists(path):
            os.unlink(path)


@given(
    data=st.dictionaries(
        st.text(min_size=1, max_size=10),
        st.lists(st.text(max_size=20), max_size=5),
        max_size=5,
    )
)
@settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property9_load_regulation_tags_round_trip(data):
    """
    Property 9 (regulation_tags variant): Config loading round-trip.
    For any valid JSON dict written to a temp file and referenced via env var,
    load_regulation_tags() returns a dict equal to the written dict.
    Validates: Requirements 5.1, 5.2
    """
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

        with _env_var("DATAGUARDIAN_REGULATION_TAGS_PATH", path):
            result = load_regulation_tags()

        assert result == data
    finally:
        if os.path.exists(path):
            os.unlink(path)


# ---------------------------------------------------------------------------
# Property 10: Invalid JSON config falls back to built-in default
# Validates: Requirements 5.3, 5.4
# ---------------------------------------------------------------------------

@given(
    invalid_content=st.text().filter(lambda s: not _is_valid_json(s))
)
@settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property10_invalid_json_load_tag_map_falls_back_to_default(invalid_content):
    """
    Property 10: Invalid JSON config falls back to built-in default.
    For any string that is not valid JSON, load_tag_map() returns DEFAULT_TAG_MAP unchanged.
    Validates: Requirements 5.3, 5.4
    """
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(invalid_content)

        with _env_var("DATAGUARDIAN_TAG_MAP_PATH", path):
            result = load_tag_map()

        assert result == DEFAULT_TAG_MAP
    finally:
        if os.path.exists(path):
            os.unlink(path)


@given(
    invalid_content=st.text().filter(lambda s: not _is_valid_json(s))
)
@settings(max_examples=10, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property10_invalid_json_load_regulation_tags_falls_back_to_default(invalid_content):
    """
    Property 10 (regulation_tags variant): Invalid JSON config falls back to built-in default.
    For any string that is not valid JSON, load_regulation_tags() returns DEFAULT_REGULATION_TAGS unchanged.
    Validates: Requirements 5.3, 5.4
    """
    fd, path = tempfile.mkstemp(suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(invalid_content)

        with _env_var("DATAGUARDIAN_REGULATION_TAGS_PATH", path):
            result = load_regulation_tags()

        assert result == DEFAULT_REGULATION_TAGS
    finally:
        if os.path.exists(path):
            os.unlink(path)
