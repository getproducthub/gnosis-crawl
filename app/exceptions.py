"""Custom exceptions for gnosis-crawl."""


class QueueOverflowError(Exception):
    """Raised when the crawl request queue depth exceeds the configured limit."""
    pass
