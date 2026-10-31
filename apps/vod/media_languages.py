"""Local UI choices, not the complete language validation/migration catalogue.

Curated modern film/TV subset of TMDB's configuration/languages example,
checked against its official OpenAPI snapshot on 2026-10-22:
https://developer.themoviedb.org/openapi/tmdb-api.json
https://developer.themoviedb.org/reference/configuration-languages

Values use our ISO 639-2/B identifiers; legacyValue records TMDB's alpha-2 tag.
Chinese keeps the ISO macrolanguage name rather than claiming a specific dialect.
Extend this data file deliberately; do not add a runtime TMDB/key dependency or
replace language_codes.LANGUAGES, which is also used by migration 0007.
The frontend imports the same data so fallback/search cannot expose the full ISO list.
"""

import json
from pathlib import Path

MEDIA_LANGUAGE_OPTIONS = json.loads(
    Path(__file__).with_suffix(".json").read_text(encoding="utf-8")
)
