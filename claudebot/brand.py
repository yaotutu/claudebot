"""Central product identity constants.

Keep runtime-facing names here so a future product rename has a small, obvious
surface area. Import paths and packaging metadata still need explicit updates
when the Python package name changes.
"""

from __future__ import annotations

PRODUCT_NAME = "claudebot"
DISPLAY_NAME = "claudebot"
CLI_NAME = "claudebot"
PYTHON_PACKAGE = "claudebot"
DISTRIBUTION_NAME = "claudebot"
CONFIG_DIR_NAME = ".claudebot"
ENV_PREFIX = "CLAUDEBOT"
HTTP_AUTH_HEADER = "X-Claudebot-Auth"


def env_name(name: str) -> str:
    """Return a product-prefixed environment variable name."""
    return f"{ENV_PREFIX}_{name}"
