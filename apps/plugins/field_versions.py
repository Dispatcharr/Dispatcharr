"""Manifest-version bounds for plugin settings schema features.

The type registry is also the serializer's list of supported types. Unlisted
attributes have no additional version restriction.
"""

FIELD_TYPE_VERSIONS = {
    "string": {"min_manifest_version": 0, "max_manifest_version": None},
    "number": {"min_manifest_version": 0, "max_manifest_version": None},
    "boolean": {"min_manifest_version": 0, "max_manifest_version": None},
    "select": {"min_manifest_version": 0, "max_manifest_version": None},
    "text": {"min_manifest_version": 0, "max_manifest_version": None},
    "info": {"min_manifest_version": 0, "max_manifest_version": None},
    "multiselect": {"min_manifest_version": 1, "max_manifest_version": None},
    "section": {"min_manifest_version": 1, "max_manifest_version": None},
    "table": {"min_manifest_version": 1, "max_manifest_version": None},
    "file": {"min_manifest_version": 1, "max_manifest_version": None},
}

# A None field_types value applies to every field type.
FIELD_ATTRIBUTE_VERSIONS = {
    "section": {"field_types": None, "min_manifest_version": 1, "max_manifest_version": None},
    "collapsed": {"field_types": {"section"}, "min_manifest_version": 1, "max_manifest_version": None},
    "columns": {"field_types": {"table"}, "min_manifest_version": 1, "max_manifest_version": None},
    "accept": {"field_types": {"file"}, "min_manifest_version": 1, "max_manifest_version": None},
    "max_size": {"field_types": {"file"}, "min_manifest_version": 1, "max_manifest_version": None},
    "rows": {"field_types": {"text"}, "min_manifest_version": 1, "max_manifest_version": None},
}


def feature_supported(bounds, manifest_version):
    """Check inclusive bounds, allowing an unbounded end in either direction."""
    minimum = bounds.get("min_manifest_version")
    maximum = bounds.get("max_manifest_version")
    return ((minimum is None or manifest_version >= minimum)
            and (maximum is None or manifest_version <= maximum))
