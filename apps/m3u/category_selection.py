"""Normalize reversible per-account category selection without deleting rows."""


def category_selection_state(values, current=None):
    enabled = values.get("enabled", getattr(current, "enabled", True))
    ignored = values.get("ignored", getattr(current, "ignored", False))
    if not isinstance(enabled, bool) or not isinstance(ignored, bool):
        raise ValueError("enabled and ignored must be booleans.")
    if values.get("ignored") is True:
        enabled = False
    elif values.get("enabled") is True:
        ignored = False
    return {"enabled": enabled, "ignored": ignored}
