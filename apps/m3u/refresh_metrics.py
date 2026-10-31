from django.db import transaction

from apps.m3u.models import M3UAccount
from core.utils import ensure_custom_properties_dict


def record_refresh_metrics(account_id, kind, counts, duration_seconds, completed_at, *, auto_sync=None):
    """Preserve account settings; return whether VOD first imported any content."""
    if kind not in ("live", "vod"):
        raise ValueError(f"Unsupported refresh kind: {kind}")

    with transaction.atomic():
        account = M3UAccount.objects.select_for_update().only("custom_properties").get(pk=account_id)
        custom = ensure_custom_properties_dict(account.custom_properties).copy()
        timings = dict(custom.get("refresh_timings") or {})
        first_vod_import = False
        if kind == "vod" and not timings.get("vod_first_imported_at"):
            previous = custom.get("vod_catalog_counts") or {}
            previously_imported = any(
                (previous.get(scope) or {}).get("selected_total", 0) > 0
                for scope in ("movies", "series")
            )
            imported = any(
                (counts.get(scope) or {}).get("selected_total", 0) > 0
                for scope in ("movies", "series")
            )
            if previously_imported or imported:
                timings["vod_first_imported_at"] = (
                    timings.get("vod_completed_at") if previously_imported else None
                ) or completed_at.isoformat()
                first_vod_import = not previously_imported
        custom[f"{kind}_catalog_counts"] = counts
        if kind == "live":
            result = auto_sync or {}
            custom["live_auto_sync_result"] = {
                "status": result.get("status"),
                "channels_failed": result.get("channels_failed", 0),
                "error": result.get("error", "") if result.get("status") == "error" else "",
            }
        timings[f"{kind}_seconds"] = round(duration_seconds, 2)
        timings[f"{kind}_completed_at"] = completed_at.isoformat()
        custom["refresh_timings"] = timings
        M3UAccount.objects.filter(pk=account_id).update(custom_properties=custom)
        return first_vod_import
