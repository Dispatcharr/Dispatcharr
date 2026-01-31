"""Version compatibility checking for plugins."""

from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version, InvalidVersion

from version import __version__


def check_compatibility(requires_spec: str) -> tuple[bool, str]:
    """
    Check if the current Dispatcharr version satisfies the given constraint.

    Args:
        requires_spec: A PEP 440 version specifier string (e.g., ">=0.18.0", "<1.0.0,>=0.18.0")

    Returns:
        A tuple of (is_compatible, error_message).
        If compatible, error_message is empty.
        If incompatible or invalid, error_message describes the issue.
    """
    try:
        specifier = SpecifierSet(requires_spec)
        current = Version(__version__)
        if current in specifier:
            return True, ""
        return False, f"Requires Dispatcharr {requires_spec}, but running {__version__}"
    except InvalidSpecifier as e:
        return False, f"Invalid version constraint: {e}"
    except InvalidVersion as e:
        return False, f"Invalid Dispatcharr version '{__version__}': {e}"
