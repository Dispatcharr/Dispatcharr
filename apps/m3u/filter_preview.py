"""Complete, selection-scoped filter previews without saving or importing."""

from apps.channels.models import ChannelGroupM3UAccount
from core.xtream_codes import normalize_server_url

from .category_preview import CategoryPreviewError, cached_preview, can_load_preview
from .filter_catalog import iter_live_filter_catalog, live_group_catalog_ready


def preview_relations(account, group_ids):
    relations = list(
        ChannelGroupM3UAccount.objects.filter(
            m3u_account=account, channel_group_id__in=group_ids
        )
        .select_related("channel_group")
        .order_by("channel_group_id")
    )
    if len(relations) != len(set(group_ids)):
        raise CategoryPreviewError("Select categories belonging to this account.")
    return relations


def selection_availability(account, group_ids):
    relations = preview_relations(account, group_ids)
    if account.account_type == "XC":
        missing = [
            row for row in relations if cached_preview(account, "live", row) is None
        ]
        ready = not missing
        can_load = all(can_load_preview(account, "live", row) for row in missing)
    else:
        ready = live_group_catalog_ready(account)
        missing = [] if ready else relations
        can_load = False
    return {
        "ready": ready,
        "selected_count": len(relations),
        "missing_group_ids": [row.channel_group_id for row in missing],
        "can_load_provider": bool(missing) and can_load,
        "refresh_in_progress": False,
        "refresh_failed": False,
        "last_completed_refresh": None,
    }


def selection_inventory(account, group_ids):
    relations = preview_relations(account, group_ids)
    if account.account_type == "XC":
        prefix = (
            f"{normalize_server_url(account.server_url).rstrip('/')}/live/"
            f"{account.username}/{account.password}/"
        )
        for relation in relations:
            rows = cached_preview(account, "live", relation)
            if rows is None:
                # The response is built only after the entire inventory passes.
                raise CategoryPreviewError(
                    "Category previews are missing or expired. Reopen stream filters to load them."
                )
            for row in rows:
                name = row.get("name") or (
                    f"{account.name} - {row.get('stream_id', 'Unknown')}"
                )
                yield {
                    "name": name,
                    "group": relation.channel_group.name,
                    "url": f"{prefix}{row.get('stream_id')}.ts",
                }
    else:
        if not live_group_catalog_ready(account):
            raise CategoryPreviewError(
                "Playlist preview data is unavailable. Reload categories before configuring stream filters."
            )
        names = {row.channel_group.name for row in relations}
        for row in iter_live_filter_catalog(account.id, "live-groups"):
            if row["group"] in names:
                yield row
