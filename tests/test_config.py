"""Tests for config parsing hardening."""

import importlib

from watcher import config


def test_valid_timeout_parses(monkeypatch):
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "5.5")
    importlib.reload(config)
    assert config.HTTP_TIMEOUT_SECONDS == 5.5


def test_non_numeric_timeout_falls_back(monkeypatch):
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "abc")
    importlib.reload(config)
    assert config.HTTP_TIMEOUT_SECONDS == 20


def test_non_positive_timeout_falls_back(monkeypatch):
    monkeypatch.setenv("HTTP_TIMEOUT_SECONDS", "-3")
    importlib.reload(config)
    assert config.HTTP_TIMEOUT_SECONDS == 20


def test_missing_timeout_uses_default(monkeypatch):
    monkeypatch.delenv("HTTP_TIMEOUT_SECONDS", raising=False)
    importlib.reload(config)
    assert config.HTTP_TIMEOUT_SECONDS == 20


def test_topic_is_stripped(monkeypatch):
    monkeypatch.setenv("NTFY_TOPIC", "  my-topic  ")
    importlib.reload(config)
    assert config.NTFY_TOPIC == "my-topic"