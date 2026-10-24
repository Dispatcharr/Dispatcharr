"""Persistent, private Live inventory before account stream filtering."""

import gzip
import json
import logging
import os
import tempfile
from datetime import datetime, timezone

from django.conf import settings
from django.utils.crypto import salted_hmac
from core.utils import ensure_custom_properties_dict

logger = logging.getLogger(__name__)


def _catalog_path(account_id, scope="live"):
    if scope not in ("live", "live-groups", "movie", "series"):
        raise ValueError("Unknown catalog scope")
    return os.path.join(
        settings.M3U_FILTER_CATALOG_ROOT,
        f"{int(account_id)}.{scope}-filter-preview.jsonl.gz",
    )


def live_filter_selection(account):
    """Identify the connection and exact saved selection fetched by a refresh."""
    connection = json.dumps(
        [
            account.account_type,
            account.server_url,
            str(account.file_path or ""),
            account.username,
            account.password,
            account.get_user_agent_string(),
        ]
    )
    return {
        "connection": salted_hmac("m3u.filter-catalog", connection).hexdigest(),
        "categories": [
            (group_id, name, ensure_custom_properties_dict(properties).get("xc_id"))
            for group_id, name, properties in account.channel_group.filter(enabled=True)
            .order_by("channel_group_id")
            .values_list("channel_group_id", "channel_group__name", "custom_properties")
        ],
    }


def live_filter_catalog_ready(account):
    """Legacy or differently scoped snapshots must be refreshed before testing."""
    try:
        with gzip.open(_catalog_path(account.id), "rt", encoding="utf-8") as catalog:
            metadata = json.loads(catalog.readline()).get("_selection")
        # JSON converts tuples to lists, including the category snapshot.
        return metadata == json.loads(json.dumps(live_filter_selection(account)))
    except (OSError, ValueError, TypeError, AttributeError, EOFError):
        return False


def live_group_catalog_ready(account):
    """A Standard playlist's discovery snapshot must match this connection."""
    try:
        with gzip.open(
            _catalog_path(account.id, "live-groups"), "rt", encoding="utf-8"
        ) as catalog:
            metadata = json.loads(catalog.readline()).get("_selection") or {}
        return (
            metadata.get("connection") == live_filter_selection(account)["connection"]
        )
    except (OSError, ValueError, TypeError, AttributeError, EOFError):
        return False


def write_live_filter_catalog(
    account_id, streams, *, publish=True, scope="live", selection=None
):
    """Atomically replace the snapshot; failures keep the previous snapshot."""
    path = _catalog_path(account_id, scope)
    temporary_path = None
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=os.path.dirname(path), prefix=f".{int(account_id)}-", delete=False
        ) as temporary:
            temporary_path = temporary.name
        with gzip.open(temporary_path, "wt", encoding="utf-8") as output:
            if selection is not None:
                output.write(json.dumps({"_selection": selection}) + "\n")
            for index, stream in enumerate(streams):
                attributes = stream.get("attributes") or {}
                output.write(
                    json.dumps(
                        {
                            "id": f"catalog-{index}",
                            "name": str(stream.get("name") or ""),
                            "group": str(attributes.get("group-title") or ""),
                            "url": str(stream.get("url") or ""),
                        },
                        ensure_ascii=False,
                    )
                )
                output.write("\n")
        if publish:
            os.replace(temporary_path, path)
            return True
        return temporary_path
    except Exception:
        logger.warning(
            "Could not update Live filter catalog for account %s",
            account_id,
            exc_info=True,
        )
        if temporary_path:
            try:
                os.remove(temporary_path)
            except OSError:
                pass
        return False


def publish_live_filter_catalog(account_id, temporary_path, *, scope="live"):
    if temporary_path:
        try:
            os.utime(temporary_path, None)
            os.replace(temporary_path, _catalog_path(account_id, scope))
        except OSError:
            logger.warning(
                "Could not publish Live filter catalog for account %s",
                account_id,
                exc_info=True,
            )
            discard_live_filter_catalog(temporary_path)


def discard_live_filter_catalog(temporary_path):
    if temporary_path:
        try:
            os.remove(temporary_path)
        except FileNotFoundError:
            pass
        except OSError:
            logger.warning(
                "Could not discard staged Live filter catalog", exc_info=True
            )


def has_live_filter_catalog(account_id, scope="live"):
    return os.path.isfile(_catalog_path(account_id, scope))


def live_filter_catalog_timestamp(account_id, scope="live"):
    return datetime.fromtimestamp(
        os.path.getmtime(_catalog_path(account_id, scope)), timezone.utc
    )


def iter_live_filter_catalog(account_id, scope="live"):
    with gzip.open(_catalog_path(account_id, scope), "rt", encoding="utf-8") as catalog:
        for line in catalog:
            if line.strip():
                row = json.loads(line)
                if "_selection" not in row:
                    yield row


def remove_live_filter_catalog(account_id, scope="live"):
    try:
        os.remove(_catalog_path(account_id, scope))
    except FileNotFoundError:
        pass
    except OSError:
        logger.warning(
            "Could not remove Live filter catalog for account %s",
            account_id,
            exc_info=True,
        )
