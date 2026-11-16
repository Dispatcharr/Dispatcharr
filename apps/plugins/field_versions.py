"""Manifest-version bounds for plugin settings schema features.

Unlisted types and attributes have no additional version restriction. The
field serializer remains responsible for rejecting unknown types.
"""

FIELD_TYPE_VERSIONS = {
    name: {"min_manifest_version": 1, "max_manifest_version": None}
    for name in ("multiselect", "section", "table", "file")
}

FIELD_ATTRIBUTE_VERSIONS = {
    name: {"min_manifest_version": 1, "max_manifest_version": None}
    for name in ("section", "collapsed", "columns", "accept", "max_size", "rows")
}


def feature_supported(bounds, manifest_version):
    """Check inclusive bounds, allowing an unbounded end in either direction."""
    minimum = bounds.get("min_manifest_version")
    maximum = bounds.get("max_manifest_version")
    return ((minimum is None or manifest_version >= minimum)
            and (maximum is None or manifest_version <= maximum))
