"""Typed application errors safe to expose at service boundaries."""


class V365Error(Exception):
    """Base error for expected application failures."""


class InvalidModelError(V365Error):
    """Raised when a source model is missing, corrupt, or unsupported."""


class ConfigurationError(V365Error):
    """Raised when a requested capability lacks required configuration."""


class ProviderError(V365Error):
    """Raised when an external geometry or generation provider fails."""
