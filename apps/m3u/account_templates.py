"""Portable M3U account template capture and application helpers."""

from copy import deepcopy

from django.db import transaction

from core.utils import ensure_custom_properties_dict

from .models import M3UAccountTemplate, M3UFilter, M3UGroupRule


ACCOUNT_SETTING_FIELDS = (
    "max_streams",
    "refresh_interval",
    "xc_live_refresh_min_age_minutes",
    "vod_refresh_interval",
    "vod_refresh_after_live",
    "stale_stream_days",
    "priority",
)
CUSTOM_SETTING_FIELDS = (
    "enable_vod",
    "use_group_rules_live",
    "use_group_rules_movie",
    "use_group_rules_series",
)
GROUP_SELECTIONS_SETTING = "group_selections"
ACCOUNT_GROUP_SELECTIONS_PROPERTY = "template_group_selections"
LIVE_PROVIDER_PROPERTY_KEYS = {"xc_id", "discovery_rule_id"}
LIVE_AUTO_SYNC_PROPERTY_KEYS = {
    "force_dummy_epg",
    "name_regex_pattern",
    "name_replace_pattern",
    "name_match_regex",
    "name_match_exclude_regex",
    "channel_sort_order",
    "channel_sort_reverse",
    "channel_numbering_mode",
    "channel_numbering_fallback",
    "compact_numbering",
    "orphan_channel_cleanup",
    "skip_channel_profile_memberships",
}


def _cron_expression(task):
    if not task or not task.crontab:
        return ""
    crontab = task.crontab
    return (
        f"{crontab.minute} {crontab.hour} {crontab.day_of_month} "
        f"{crontab.month_of_year} {crontab.day_of_week}"
    )


def _selection_key(name):
    return str(name or "").strip().casefold()


def template_group_selection_map(account, scope):
    custom = ensure_custom_properties_dict(account.custom_properties)
    selections = custom.get(ACCOUNT_GROUP_SELECTIONS_PROPERTY) or {}
    rows = selections.get(scope) if isinstance(selections, dict) else []
    if not isinstance(rows, list):
        return {}
    return {
        _selection_key(row.get("name")): row
        for row in rows
        if isinstance(row, dict) and _selection_key(row.get("name"))
    }


def _capture_group_selections(account):
    from apps.channels.models import (
        ChannelGroup,
        ChannelGroupM3UAccount,
        ChannelProfile,
        Logo,
    )
    from apps.epg.models import EPGSource
    from apps.vod.models import M3UVODCategoryRelation
    from core.models import StreamProfile

    live_relations = list(
        ChannelGroupM3UAccount.objects.filter(m3u_account=account)
        .select_related("channel_group")
        .order_by("channel_group__name", "id")
    )
    relation_properties = {
        relation.id: ensure_custom_properties_dict(relation.custom_properties)
        for relation in live_relations
    }

    def referenced_ids(key):
        values = set()
        for properties in relation_properties.values():
            value = properties.get(key)
            if value in (None, ""):
                continue
            candidates = value if isinstance(value, list) else [value]
            for candidate in candidates:
                try:
                    values.add(int(candidate))
                except (TypeError, ValueError):
                    continue
        return values

    def reference_name(mapping, value):
        try:
            return mapping.get(int(value))
        except (TypeError, ValueError):
            return None

    group_names = dict(
        ChannelGroup.objects.filter(id__in=referenced_ids("group_override"))
        .values_list("id", "name")
    )
    channel_profile_names = dict(
        ChannelProfile.objects.filter(id__in=referenced_ids("channel_profile_ids"))
        .values_list("id", "name")
    )
    epg_names = dict(
        EPGSource.objects.filter(id__in=referenced_ids("custom_epg_id"))
        .values_list("id", "name")
    )
    stream_profile_names = dict(
        StreamProfile.objects.filter(id__in=referenced_ids("stream_profile_id"))
        .values_list("id", "name")
    )
    logos = {
        logo.id: {"name": logo.name, "url": logo.url}
        for logo in Logo.objects.filter(id__in=referenced_ids("custom_logo_id"))
    }

    live = []
    for relation in live_relations:
        properties = relation_properties[relation.id]
        portable_properties = {
            key: deepcopy(properties[key])
            for key in LIVE_AUTO_SYNC_PROPERTY_KEYS
            if key in properties
        }
        references = {}
        group_name = reference_name(
            group_names, properties.get("group_override")
        )
        if group_name:
            references["group_override"] = group_name
        profile_ids = properties.get("channel_profile_ids") or []
        if not isinstance(profile_ids, list):
            profile_ids = [profile_ids]
        profile_names = []
        for profile_id in profile_ids:
            profile_name = reference_name(channel_profile_names, profile_id)
            if profile_name:
                profile_names.append(profile_name)
        if profile_names:
            references["channel_profiles"] = profile_names
        epg_name = reference_name(epg_names, properties.get("custom_epg_id"))
        if epg_name:
            references["epg_source"] = epg_name
        stream_profile_name = reference_name(
            stream_profile_names,
            properties.get("stream_profile_id"),
        )
        if stream_profile_name:
            references["stream_profile"] = stream_profile_name
        logo = None
        try:
            logo = logos.get(int(properties.get("custom_logo_id")))
        except (TypeError, ValueError):
            pass
        if logo:
            references["logo"] = logo
        live.append(
            {
                "name": relation.channel_group.name,
                "enabled": relation.enabled,
                "auto_channel_sync": relation.auto_channel_sync,
                "auto_sync_channel_start": relation.auto_sync_channel_start,
                "auto_sync_channel_end": relation.auto_sync_channel_end,
                "custom_properties": portable_properties,
                "references": references,
            }
        )

    vod = {"movie": [], "series": []}
    for relation in (
        M3UVODCategoryRelation.objects.filter(m3u_account=account)
        .select_related("category")
        .order_by("category__category_type", "category__name", "id")
    ):
        vod[relation.category.category_type].append(
            {
                "name": relation.category.name,
                "enabled": relation.enabled,
                "metadata_defaults": deepcopy(relation.metadata_defaults or {}),
            }
        )
    return {"live": live, **vod}


def _live_reference_maps(selections):
    from apps.channels.models import ChannelGroup, ChannelProfile, Logo
    from apps.epg.models import EPGSource
    from core.models import StreamProfile

    group_names = set()
    channel_profile_names = set()
    epg_names = set()
    stream_profile_names = set()
    logo_urls = set()
    for selection in selections:
        references = selection.get("references") or {}
        if not isinstance(references, dict):
            continue
        group_override = references.get("group_override")
        if isinstance(group_override, str) and group_override:
            group_names.add(group_override)
        profile_names = references.get("channel_profiles") or []
        if isinstance(profile_names, list):
            channel_profile_names.update(
                name for name in profile_names if isinstance(name, str) and name
            )
        epg_source = references.get("epg_source")
        if isinstance(epg_source, str) and epg_source:
            epg_names.add(epg_source)
        stream_profile = references.get("stream_profile")
        if isinstance(stream_profile, str) and stream_profile:
            stream_profile_names.add(stream_profile)
        logo = references.get("logo") or {}
        if isinstance(logo, dict) and logo.get("url"):
            logo_urls.add(logo["url"])
    return {
        "groups": dict(
            ChannelGroup.objects.filter(name__in=group_names).values_list(
                "name", "id"
            )
        ),
        "channel_profiles": dict(
            ChannelProfile.objects.filter(name__in=channel_profile_names).values_list(
                "name", "id"
            )
        ),
        "epg_sources": dict(
            EPGSource.objects.filter(name__in=epg_names).values_list("name", "id")
        ),
        "stream_profiles": dict(
            StreamProfile.objects.filter(name__in=stream_profile_names)
            .order_by("id")
            .values_list("name", "id")
        ),
        "logos": dict(
            Logo.objects.filter(url__in=logo_urls).values_list("url", "id")
        ),
    }


def _resolved_live_properties(selection, reference_maps):
    raw_properties = selection.get("custom_properties") or {}
    if not isinstance(raw_properties, dict):
        raw_properties = {}
    properties = {
        key: deepcopy(value)
        for key, value in raw_properties.items()
        if key in LIVE_AUTO_SYNC_PROPERTY_KEYS
    }
    references = selection.get("references") or {}
    if not isinstance(references, dict):
        references = {}
    group_id = reference_maps["groups"].get(references.get("group_override"))
    if group_id:
        properties["group_override"] = group_id
    profile_names = references.get("channel_profiles") or []
    if isinstance(profile_names, list) and profile_names:
        properties["channel_profile_ids"] = [
            reference_maps["channel_profiles"][name]
            for name in profile_names
            if name in reference_maps["channel_profiles"]
        ]
    epg_id = reference_maps["epg_sources"].get(references.get("epg_source"))
    if epg_id:
        properties["custom_epg_id"] = epg_id
    stream_profile_id = reference_maps["stream_profiles"].get(
        references.get("stream_profile")
    )
    if stream_profile_id:
        properties["stream_profile_id"] = stream_profile_id
    logo_reference = references.get("logo") or {}
    logo_url = logo_reference.get("url") if isinstance(logo_reference, dict) else None
    logo_id = reference_maps["logos"].get(logo_url)
    if logo_id:
        properties["custom_logo_id"] = logo_id
    return properties


def _live_group_template_values(selection, reference_maps):
    return {
        "enabled": bool(selection.get("enabled", False)),
        "auto_channel_sync": bool(selection.get("auto_channel_sync", False)),
        "auto_sync_channel_start": selection.get("auto_sync_channel_start"),
        "auto_sync_channel_end": selection.get("auto_sync_channel_end"),
        "custom_properties": _resolved_live_properties(
            selection, reference_maps
        ),
    }


def template_live_group_values_map(account):
    selections = template_group_selection_map(account, "live")
    reference_maps = _live_reference_maps(selections.values())
    return {
        key: _live_group_template_values(selection, reference_maps)
        for key, selection in selections.items()
    }


def merge_live_group_template_values(values, provider_properties=None):
    properties = {
        key: value
        for key, value in ensure_custom_properties_dict(
            provider_properties
        ).items()
        if key in LIVE_PROVIDER_PROPERTY_KEYS
    }
    properties.update(deepcopy(values.get("custom_properties") or {}))
    merged = deepcopy(values)
    merged["custom_properties"] = properties
    return merged


def _apply_group_selections(account, selections):
    from apps.channels.models import ChannelGroupM3UAccount
    from apps.vod.models import M3UVODCategoryRelation

    live_values_by_name = template_live_group_values_map(account)
    live_updates = []
    for relation in ChannelGroupM3UAccount.objects.filter(
        m3u_account=account
    ).select_related("channel_group"):
        values = live_values_by_name.get(_selection_key(relation.channel_group.name))
        if not values:
            continue
        values = merge_live_group_template_values(
            values, relation.custom_properties
        )
        for field, value in values.items():
            setattr(relation, field, value)
        live_updates.append(relation)
    if live_updates:
        ChannelGroupM3UAccount.objects.bulk_update(
            live_updates,
            [
                "enabled",
                "auto_channel_sync",
                "auto_sync_channel_start",
                "auto_sync_channel_end",
                "custom_properties",
            ],
        )

    for scope in ("movie", "series"):
        rows = selections.get(scope, [])
        if not isinstance(rows, list):
            rows = []
        by_name = {
            _selection_key(row.get("name")): row
            for row in rows
            if isinstance(row, dict)
        }
        updates = []
        for relation in M3UVODCategoryRelation.objects.filter(
            m3u_account=account,
            category__category_type=scope,
        ).select_related("category"):
            selection = by_name.get(_selection_key(relation.category.name))
            if not selection:
                continue
            relation.enabled = bool(selection.get("enabled", False))
            relation.metadata_defaults = deepcopy(
                selection.get("metadata_defaults") or {}
            )
            updates.append(relation)
        if updates:
            M3UVODCategoryRelation.objects.bulk_update(
                updates, ["enabled", "metadata_defaults"]
            )
            from apps.vod.metadata import sync_category_relations_metadata

            sync_category_relations_metadata(updates)


def capture_account_template(account, *, name, description=""):
    custom = ensure_custom_properties_dict(account.custom_properties)
    settings = {
        field: getattr(account, field) for field in ACCOUNT_SETTING_FIELDS
    }
    settings.update(
        {
            field: custom.get(field, field.startswith("use_group_rules_"))
            for field in CUSTOM_SETTING_FIELDS
        }
    )
    settings["cron_expression"] = _cron_expression(account.refresh_task)
    settings["vod_cron_expression"] = _cron_expression(account.vod_refresh_task)
    settings[GROUP_SELECTIONS_SETTING] = _capture_group_selections(account)
    filters = list(
        account.filters.order_by("order", "id").values(
            "filter_type", "regex_pattern", "exclude", "order", "custom_properties"
        )
    )
    rules = list(
        account.group_rules.order_by("scope", "order", "id").values(
            "scope",
            "match_field",
            "match_mode",
            "regex_pattern",
            "exclude_regex_pattern",
            "action",
            "case_sensitive",
            "enabled",
            "metadata_defaults",
            "order",
        )
    )
    return M3UAccountTemplate.objects.create(
        name=name,
        description=description,
        account_type=account.account_type,
        account_settings=settings,
        filters=filters,
        group_rules=rules,
    )


@transaction.atomic
def apply_account_template(account, template):
    settings = template.account_settings or {}
    update_fields = []
    account.account_type = template.account_type
    update_fields.append("account_type")
    for field in ACCOUNT_SETTING_FIELDS:
        if field in settings:
            setattr(account, field, settings[field])
            update_fields.append(field)
    custom = dict(ensure_custom_properties_dict(account.custom_properties))
    for field in CUSTOM_SETTING_FIELDS:
        if field in settings:
            custom[field] = settings[field]
    selections = settings.get(GROUP_SELECTIONS_SETTING)
    if isinstance(selections, dict):
        custom[ACCOUNT_GROUP_SELECTIONS_PROPERTY] = deepcopy(selections)
    else:
        custom.pop(ACCOUNT_GROUP_SELECTIONS_PROPERTY, None)
    account.custom_properties = custom
    update_fields.append("custom_properties")
    if "cron_expression" in settings:
        account._cron_expression = settings["cron_expression"] or ""
    if "vod_cron_expression" in settings:
        account._vod_cron_expression = settings["vod_cron_expression"] or ""
    account.save(update_fields=list(dict.fromkeys(update_fields)))

    account.filters.all().delete()
    M3UFilter.objects.bulk_create(
        [M3UFilter(m3u_account=account, **values) for values in (template.filters or [])]
    )
    account.group_rules.all().delete()
    M3UGroupRule.objects.bulk_create(
        [
            M3UGroupRule(m3u_account=account, **values)
            for values in (template.group_rules or [])
        ]
    )
    if isinstance(selections, dict):
        _apply_group_selections(account, selections)
    return account
