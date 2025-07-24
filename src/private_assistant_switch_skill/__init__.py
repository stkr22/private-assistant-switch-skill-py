"""Home Automation Skill for Modular Private Assistant.

Manages and controls smart plugs and bulbs via Home Assistant.
"""

try:
    from ._version import __version__
except ImportError:
    # Fallback for development installs
    __version__ = "dev"

__all__ = ["__version__"]