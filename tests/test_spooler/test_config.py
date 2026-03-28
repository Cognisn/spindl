"""Tests for SpoolerConfig."""

import pytest

from spindl.spooler.config import SpoolerConfig


class TestSpoolerConfig:
    def test_defaults(self):
        config = SpoolerConfig()
        assert config.max_inline_tokens == 2000
        assert config.max_inline_items == 10
        assert config.default_page_size == 20
        assert config.max_page_size == 50
        assert config.summary_sample_size == 3
        assert config.chars_per_token == 4

    def test_estimate_tokens(self):
        config = SpoolerConfig()
        assert config.estimate_tokens("abcdefgh") == 2

    def test_validate_ok(self, spooler_config):
        spooler_config.validate()

    def test_validate_page_size(self, tmp_path):
        config = SpoolerConfig(
            db_path=str(tmp_path / "test.db"),
            max_page_size=0,
        )
        with pytest.raises(ValueError, match="max_page_size"):
            config.validate()

    def test_validate_default_exceeds_max(self, tmp_path):
        config = SpoolerConfig(
            db_path=str(tmp_path / "test.db"),
            default_page_size=100,
            max_page_size=50,
        )
        with pytest.raises(ValueError, match="default_page_size"):
            config.validate()

    def test_validate_negative_items(self, tmp_path):
        config = SpoolerConfig(
            db_path=str(tmp_path / "test.db"),
            max_inline_items=-1,
        )
        with pytest.raises(ValueError, match="max_inline_items"):
            config.validate()
