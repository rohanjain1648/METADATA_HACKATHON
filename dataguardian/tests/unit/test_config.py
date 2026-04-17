"""
Unit tests for dataguardian.config — load_tag_map and load_regulation_tags.
"""

import json
import logging
import os
import tempfile

import pytest

from dataguardian.config import (
    DEFAULT_TAG_MAP,
    DEFAULT_REGULATION_TAGS,
    load_tag_map,
    load_regulation_tags,
)


# ===========================================================================
# load_tag_map
# ===========================================================================

class TestLoadTagMap:
    def test_env_var_unset_returns_default(self, monkeypatch):
        """When DATAGUARDIAN_TAG_MAP_PATH is unset, return DEFAULT_TAG_MAP."""
        monkeypatch.delenv("DATAGUARDIAN_TAG_MAP_PATH", raising=False)
        result = load_tag_map()
        assert result == DEFAULT_TAG_MAP

    def test_file_absent_returns_default(self, monkeypatch, tmp_path):
        """When the env var points to a non-existent file, return DEFAULT_TAG_MAP silently."""
        missing = str(tmp_path / "does_not_exist.json")
        monkeypatch.setenv("DATAGUARDIAN_TAG_MAP_PATH", missing)
        result = load_tag_map()
        assert result == DEFAULT_TAG_MAP

    def test_valid_json_file_returns_file_contents(self, monkeypatch, tmp_path):
        """When the env var points to a valid JSON file, return its contents."""
        custom = {"custom_key": "Custom.Tag", "another": "Another.Tag"}
        json_file = tmp_path / "tag_map.json"
        json_file.write_text(json.dumps(custom), encoding="utf-8")

        monkeypatch.setenv("DATAGUARDIAN_TAG_MAP_PATH", str(json_file))
        result = load_tag_map()
        assert result == custom

    def test_invalid_json_returns_default_and_logs_error(self, monkeypatch, tmp_path, caplog):
        """When the file contains invalid JSON, return DEFAULT_TAG_MAP and log an error."""
        bad_file = tmp_path / "bad_tag_map.json"
        bad_file.write_text("this is not valid json {{{", encoding="utf-8")

        monkeypatch.setenv("DATAGUARDIAN_TAG_MAP_PATH", str(bad_file))

        with caplog.at_level(logging.ERROR, logger="dataguardian.config"):
            result = load_tag_map()

        assert result == DEFAULT_TAG_MAP
        assert any("invalid JSON" in record.message or "DATAGUARDIAN_TAG_MAP_PATH" in record.message
                   for record in caplog.records), (
            f"Expected an error log mentioning invalid JSON or the env var. Got: {[r.message for r in caplog.records]}"
        )


# ===========================================================================
# load_regulation_tags
# ===========================================================================

class TestLoadRegulationTags:
    def test_env_var_unset_returns_default(self, monkeypatch):
        """When DATAGUARDIAN_REGULATION_TAGS_PATH is unset, return DEFAULT_REGULATION_TAGS."""
        monkeypatch.delenv("DATAGUARDIAN_REGULATION_TAGS_PATH", raising=False)
        result = load_regulation_tags()
        assert result == DEFAULT_REGULATION_TAGS

    def test_file_absent_returns_default(self, monkeypatch, tmp_path):
        """When the env var points to a non-existent file, return DEFAULT_REGULATION_TAGS silently."""
        missing = str(tmp_path / "does_not_exist.json")
        monkeypatch.setenv("DATAGUARDIAN_REGULATION_TAGS_PATH", missing)
        result = load_regulation_tags()
        assert result == DEFAULT_REGULATION_TAGS

    def test_valid_json_file_returns_file_contents(self, monkeypatch, tmp_path):
        """When the env var points to a valid JSON file, return its contents."""
        custom = {
            "CUSTOM_REG": ["Tag1", "Tag2"],
            "ANOTHER_REG": ["TagA"],
        }
        json_file = tmp_path / "regulation_tags.json"
        json_file.write_text(json.dumps(custom), encoding="utf-8")

        monkeypatch.setenv("DATAGUARDIAN_REGULATION_TAGS_PATH", str(json_file))
        result = load_regulation_tags()
        assert result == custom

    def test_invalid_json_returns_default_and_logs_error(self, monkeypatch, tmp_path, caplog):
        """When the file contains invalid JSON, return DEFAULT_REGULATION_TAGS and log an error."""
        bad_file = tmp_path / "bad_regulation_tags.json"
        bad_file.write_text("[not valid json", encoding="utf-8")

        monkeypatch.setenv("DATAGUARDIAN_REGULATION_TAGS_PATH", str(bad_file))

        with caplog.at_level(logging.ERROR, logger="dataguardian.config"):
            result = load_regulation_tags()

        assert result == DEFAULT_REGULATION_TAGS
        assert any("invalid JSON" in record.message or "DATAGUARDIAN_REGULATION_TAGS_PATH" in record.message
                   for record in caplog.records), (
            f"Expected an error log mentioning invalid JSON or the env var. Got: {[r.message for r in caplog.records]}"
        )
