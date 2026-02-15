"""Shared fixtures and markers for gnosis-crawl test suite."""

import pytest


def pytest_configure(config):
    config.addinivalue_line("markers", "remote: marks tests that hit a deployed API (deselect with '-m \"not remote\"')")
    config.addinivalue_line("markers", "slow: marks slow tests")
