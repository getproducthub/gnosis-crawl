"""Shared fixtures and markers for grub-crawl test suite."""

import pytest

# Standalone CLI scripts that use argparse/gnosis_registry — not pytest tests
collect_ignore = ["test_simple.py", "test_batch_crawl.py", "test_screenshot_api.py"]


def pytest_configure(config):
    config.addinivalue_line("markers", "remote: marks tests that hit a deployed API (deselect with '-m \"not remote\"')")
    config.addinivalue_line("markers", "slow: marks slow tests")
