import re
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ClassificationResult:
    detected_type: str
    title: str
    year: Optional[int] = None
    season: Optional[int] = None
    episode: Optional[int] = None
    episode_title: Optional[str] = None
    data: dict[str, Any] = field(default_factory=dict)


def normalize_title(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[^A-Za-z0-9]+", " ", value)
    normalized = re.sub(r"\s+", " ", normalized).strip().lower()
    return normalized


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(val) for val in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
