from core.utils import validate_flexible_url, ensure_custom_properties_dict
from rest_framework import serializers, status
from rest_framework.response import Response
from .models import (
    M3UAccount,
    M3UFilter,
    M3UGroupRule,
    ServerGroup,
    M3UAccountProfile,
    M3UAccountTemplate,
)
from core.models import UserAgent
from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount
from apps.channels.serializers import (
    ChannelGroupM3UAccountSerializer,
)
from datetime import timezone as dt_tz, timedelta
from django.db import transaction
from django.utils import timezone
import logging
import json

logger = logging.getLogger(__name__)


class M3UFilterSerializer(serializers.ModelSerializer):
    """Serializer for M3U Filters"""

    class Meta:
        model = M3UFilter
        fields = [
            "id",
            "filter_type",
            "regex_pattern",
            "exclude",
            "order",
            "custom_properties",
        ]

    def validate_regex_pattern(self, value):
        import re

        try:
            re.compile(value)
        except re.error as exc:
            raise serializers.ValidationError(f"Invalid regex: {exc}")
        return value

    def validate(self, attrs):
        attrs = super().validate(attrs)
        view = self.context.get("view")
        account_id = getattr(view, "kwargs", {}).get("account_id")
        filter_type = attrs.get(
            "filter_type", getattr(self.instance, "filter_type", "group")
        )
        regex_pattern = attrs.get(
            "regex_pattern", getattr(self.instance, "regex_pattern", "")
        )
        properties = attrs.get(
            "custom_properties",
            getattr(self.instance, "custom_properties", {}) or {},
        ) or {}
        case_sensitive = bool(properties.get("case_sensitive", True))
        duplicates = M3UFilter.objects.filter(
            m3u_account_id=account_id,
            filter_type=filter_type,
            regex_pattern=regex_pattern,
        )
        if self.instance:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        for duplicate in duplicates.only("id", "custom_properties"):
            duplicate_case = bool(
                (duplicate.custom_properties or {}).get("case_sensitive", True)
            )
            if duplicate_case == case_sensitive:
                raise serializers.ValidationError(
                    "An identical stream filter already exists for this field."
                )
        return attrs


class M3UGroupRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = M3UGroupRule
        fields = [
            "id",
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
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_regex_pattern(self, value):
        import re

        try:
            re.compile(value)
        except re.error as exc:
            raise serializers.ValidationError(f"Invalid regex: {exc}")
        return value

    def validate_exclude_regex_pattern(self, value):
        import re

        try:
            if value:
                re.compile(value)
        except re.error as exc:
            raise serializers.ValidationError(f"Invalid regex: {exc}")
        return value

    def validate_metadata_defaults(self, value):
        from apps.vod.metadata import validate_configurable_source_metadata

        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be an object")
        try:
            return validate_configurable_source_metadata(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc))

    def validate(self, attrs):
        attrs = super().validate(attrs)
        view = self.context.get("view")
        account_id = getattr(view, "kwargs", {}).get("account_id")
        values = {
            field: attrs.get(field, getattr(self.instance, field, default))
            for field, default in (
                ("scope", "live"),
                ("match_field", "group_name"),
                ("match_mode", "any"),
                ("regex_pattern", ""),
                ("case_sensitive", False),
            )
        }
        duplicates = M3UGroupRule.objects.filter(
            m3u_account_id=account_id,
            **values,
        )
        if self.instance:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise serializers.ValidationError(
                "An identical import rule already exists in this scope."
            )
        return attrs


class M3UAccountTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = M3UAccountTemplate
        fields = [
            "id",
            "name",
            "description",
            "account_type",
            "account_settings",
            "filters",
            "group_rules",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_account_settings(self, value):
        allowed = {
            "max_streams",
            "refresh_interval",
            "xc_live_refresh_min_age_minutes",
            "cron_expression",
            "vod_refresh_interval",
            "vod_cron_expression",
            "vod_refresh_after_live",
            "stale_stream_days",
            "priority",
            "enable_vod",
            "use_group_rules_live",
            "use_group_rules_movie",
            "use_group_rules_series",
            "group_selections",
        }
        if not isinstance(value, dict) or set(value) - allowed:
            raise serializers.ValidationError(
                "Contains unsupported or non-portable account settings"
            )
        selections = value.get("group_selections")
        if selections is not None:
            self._validate_group_selections(selections)
        return value

    @staticmethod
    def _validate_group_selections(value):
        if not isinstance(value, dict) or set(value) - {
            "live",
            "movie",
            "series",
        }:
            raise serializers.ValidationError(
                "group_selections must contain only live, movie, and series"
            )
        live_fields = {
            "name",
            "enabled",
            "auto_channel_sync",
            "auto_sync_channel_start",
            "auto_sync_channel_end",
            "custom_properties",
            "references",
        }
        vod_fields = {
            "name", "enabled", "metadata_defaults", "title_cleanup",
        }
        for scope in ("live", "movie", "series"):
            rows = value.get(scope, [])
            if not isinstance(rows, list):
                raise serializers.ValidationError(
                    f"group_selections.{scope} must be a list"
                )
            allowed_fields = live_fields if scope == "live" else vod_fields
            for row in rows:
                if (
                    not isinstance(row, dict)
                    or not str(row.get("name") or "").strip()
                    or set(row) - allowed_fields
                ):
                    raise serializers.ValidationError(
                        f"group_selections.{scope} contains an invalid entry"
                    )
                if "enabled" in row and not isinstance(row["enabled"], bool):
                    raise serializers.ValidationError(
                        f"group_selections.{scope}.enabled must be a boolean"
                    )
                if scope != "live":
                    if not isinstance(row.get("metadata_defaults", {}), dict):
                        raise serializers.ValidationError(
                            f"group_selections.{scope}.metadata_defaults must be an object"
                        )
                    from apps.vod.metadata import (
                        validate_configurable_source_metadata,
                    )

                    try:
                        row["metadata_defaults"] = (
                            validate_configurable_source_metadata(
                                row.get("metadata_defaults", {})
                            )
                        )
                    except ValueError as exc:
                        raise serializers.ValidationError(str(exc))
                    from apps.vod.tmdb import normalize_group_title_cleanup

                    try:
                        row["title_cleanup"] = normalize_group_title_cleanup(
                            row.get("title_cleanup")
                        )
                    except ValueError as exc:
                        raise serializers.ValidationError(str(exc))
                    continue
                if "auto_channel_sync" in row and not isinstance(
                    row["auto_channel_sync"], bool
                ):
                    raise serializers.ValidationError(
                        "group_selections.live.auto_channel_sync must be a boolean"
                    )
                for field in (
                    "auto_sync_channel_start",
                    "auto_sync_channel_end",
                ):
                    if row.get(field) is not None and not isinstance(
                        row[field], (int, float)
                    ):
                        raise serializers.ValidationError(
                            f"group_selections.live.{field} must be a number or null"
                        )
                if not isinstance(row.get("custom_properties", {}), dict):
                    raise serializers.ValidationError(
                        "group_selections.live.custom_properties must be an object"
                    )
                if not isinstance(row.get("references", {}), dict):
                    raise serializers.ValidationError(
                        "group_selections.live.references must be an object"
                    )

    def validate_filters(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list")
        for item in value:
            serializer = M3UFilterSerializer(data=item)
            serializer.is_valid(raise_exception=True)
        return value

    def validate_group_rules(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("Must be a list")
        for item in value:
            serializer = M3UGroupRuleSerializer(data=item)
            serializer.is_valid(raise_exception=True)
        return value


class M3UAccountProfileSerializer(serializers.ModelSerializer):
    account = serializers.SerializerMethodField()

    def get_account(self, obj):
        """Include basic account information for frontend use"""
        return {
            'id': obj.m3u_account.id,
            'name': obj.m3u_account.name,
            'account_type': obj.m3u_account.account_type,
            'is_xtream_codes': obj.m3u_account.account_type == 'XC'
        }

    class Meta:
        model = M3UAccountProfile
        fields = [
            "id",
            "name",
            "max_streams",
            "is_active",
            "is_default",
            "current_viewers",
            "search_pattern",
            "replace_pattern",
            "custom_properties",
            "exp_date",
            "account",
        ]
        read_only_fields = ["id", "account"]
        extra_kwargs = {
            'search_pattern': {'required': False, 'allow_blank': True},
            'replace_pattern': {'required': False, 'allow_blank': True},
            'exp_date': {'required': False, 'allow_null': True},
        }

    def create(self, validated_data):
        m3u_account = self.context.get("m3u_account")

        # Use the m3u_account when creating the profile
        validated_data["m3u_account_id"] = m3u_account.id

        return super().create(validated_data)

    def validate(self, data):
        """Custom validation to handle default profiles"""
        # For updates to existing instances
        if self.instance and self.instance.is_default:
            # For default profiles, search_pattern and replace_pattern are not required
            # and we don't want to validate them since they shouldn't be changed
            return data

        # For non-default profiles or new profiles, ensure required fields are present
        if not data.get('search_pattern'):
            raise serializers.ValidationError({
                'search_pattern': ['This field is required for non-default profiles.']
            })
        if not data.get('replace_pattern'):
            raise serializers.ValidationError({
                'replace_pattern': ['This field is required for non-default profiles.']
            })

        return data

    def update(self, instance, validated_data):
        if instance.is_default:
            # For default profiles, only allow updating name, custom_properties, exp_date, and patterns
            allowed_fields = {'name', 'custom_properties', 'exp_date', 'search_pattern', 'replace_pattern'}

            # Remove any fields that aren't allowed for default profiles
            disallowed_fields = set(validated_data.keys()) - allowed_fields
            if disallowed_fields:
                raise serializers.ValidationError(
                    f"Default profiles can only modify name, notes, expiration, and URL patterns. "
                    f"Cannot modify: {', '.join(disallowed_fields)}"
                )

        return super().update(instance, validated_data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.is_default:
            return Response(
                {"error": "Default profiles cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return super().destroy(request, *args, **kwargs)


class M3UAccountSerializer(serializers.ModelSerializer):
    """Serializer for M3U Account"""

    filters = serializers.SerializerMethodField()
    earliest_expiration = serializers.SerializerMethodField()
    all_expirations = serializers.SerializerMethodField()
    catalog_counts = serializers.SerializerMethodField()
    exp_date = serializers.DateTimeField(
        required=False, allow_null=True, write_only=True,
        help_text="Expiration date for the default profile (write-through)",
    )
    # Include user_agent as a mandatory field using its primary key.
    user_agent = serializers.PrimaryKeyRelatedField(
        queryset=UserAgent.objects.all(),
        required=False,
        allow_null=True,
    )
    profiles = M3UAccountProfileSerializer(many=True, read_only=True)
    read_only_fields = ["locked", "created_at", "updated_at"]
    # channel_groups = serializers.SerializerMethodField()
    channel_groups = ChannelGroupM3UAccountSerializer(
        source="channel_group", many=True, required=False
    )
    server_url = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
        validators=[validate_flexible_url],
    )
    enable_vod = serializers.BooleanField(required=False, write_only=True)
    auto_enable_new_groups_live = serializers.BooleanField(required=False, write_only=True)
    auto_enable_new_groups_vod = serializers.BooleanField(required=False, write_only=True)
    auto_enable_new_groups_series = serializers.BooleanField(required=False, write_only=True)
    use_group_rules_live = serializers.BooleanField(required=False, write_only=True)
    use_group_rules_movie = serializers.BooleanField(required=False, write_only=True)
    use_group_rules_series = serializers.BooleanField(required=False, write_only=True)
    cron_expression = serializers.CharField(required=False, allow_blank=True, default="")
    vod_cron_expression = serializers.CharField(required=False, allow_blank=True, default="")
    live_refresh_schedule = serializers.SerializerMethodField()
    vod_refresh_schedule = serializers.SerializerMethodField()
    account_template = serializers.PrimaryKeyRelatedField(
        queryset=M3UAccountTemplate.objects.all(),
        required=False,
        allow_null=True,
        write_only=True,
    )

    class Meta:
        model = M3UAccount
        fields = [
            "id",
            "name",
            "server_url",
            "file_path",
            "server_group",
            "max_streams",
            "is_active",
            "created_at",
            "updated_at",
            "filters",
            "user_agent",
            "profiles",
            "locked",
            "channel_groups",
            "refresh_interval",
            "xc_live_refresh_min_age_minutes",
            "cron_expression",
            "vod_refresh_interval",
            "vod_cron_expression",
            "vod_refresh_after_live",
            "live_refresh_schedule",
            "vod_refresh_schedule",
            "custom_properties",
            "account_type",
            "username",
            "password",
            "stale_stream_days",
            "priority",
            "status",
            "last_message",
            "enable_vod",
            "auto_enable_new_groups_live",
            "auto_enable_new_groups_vod",
            "auto_enable_new_groups_series",
            "use_group_rules_live",
            "use_group_rules_movie",
            "use_group_rules_series",
            "earliest_expiration",
            "all_expirations",
            "exp_date",
            "account_template",
            "catalog_counts",
        ]
        extra_kwargs = {
            "password": {
                "required": False,
                "allow_blank": True,
                "write_only": True,
            },
        }

    def to_representation(self, instance):
        # When the list() view pre-aggregates stream counts for all accounts
        # in a single query, it seeds "stream_counts" into the context before
        # serialization. Avoid issuing a redundant per-instance COUNT in that
        # case. The per-instance fallback handles direct serialization (e.g.
        # retrieve, create) where only one account is in scope.
        if "stream_counts" not in self.context:
            from django.db.models import Count
            from apps.channels.models import Stream

            counts_qs = (
                Stream.objects.filter(m3u_account_id=instance.id)
                .values("channel_group_id")
                .annotate(c=Count("id"))
            )
            self.context["stream_counts"] = {
                (instance.id, row["channel_group_id"]): row["c"] for row in counts_qs
            }

        data = super().to_representation(instance)

        # write_only strips password for everyone; re-add only for admins so
        # operator tooling / profile regex helpers still see credentials.
        request = self.context.get("request")
        user = getattr(request, "user", None) if request else None
        if user is not None and getattr(user, "user_level", 0) >= 10:
            data["password"] = instance.password or ""

        # Parse custom_properties to get VOD preference and auto_enable_new_groups settings
        custom_props = instance.custom_properties or {}

        data["enable_vod"] = custom_props.get("enable_vod", False)
        data["auto_enable_new_groups_live"] = custom_props.get("auto_enable_new_groups_live", True)
        data["auto_enable_new_groups_vod"] = custom_props.get("auto_enable_new_groups_vod", True)
        data["auto_enable_new_groups_series"] = custom_props.get("auto_enable_new_groups_series", True)
        data["use_group_rules_live"] = custom_props.get("use_group_rules_live", True)
        data["use_group_rules_movie"] = custom_props.get("use_group_rules_movie", True)
        data["use_group_rules_series"] = custom_props.get("use_group_rules_series", True)

        # Derive cron_expression from the linked PeriodicTask's crontab (single source of truth)
        # But first check if we have a transient _cron_expression (from create/update before signal runs)
        cron_expr = ""
        if hasattr(instance, '_cron_expression'):
            cron_expr = instance._cron_expression
        elif instance.refresh_task_id and instance.refresh_task and instance.refresh_task.crontab:
            ct = instance.refresh_task.crontab
            cron_expr = f"{ct.minute} {ct.hour} {ct.day_of_month} {ct.month_of_year} {ct.day_of_week}"
        data["cron_expression"] = cron_expr

        vod_cron_expr = ""
        if hasattr(instance, '_vod_cron_expression'):
            vod_cron_expr = instance._vod_cron_expression
        elif (
            instance.vod_refresh_task_id
            and instance.vod_refresh_task
            and instance.vod_refresh_task.crontab
        ):
            ct = instance.vod_refresh_task.crontab
            vod_cron_expr = (
                f"{ct.minute} {ct.hour} {ct.day_of_month} "
                f"{ct.month_of_year} {ct.day_of_week}"
            )
        data["vod_cron_expression"] = vod_cron_expr

        # Surface default profile's exp_date for the form.
        # Use prefetch cache (obj.profiles.all()) to avoid an extra query per account.
        # Always emit a Z-suffix UTC string so JS new Date() never misinterprets it as local.
        default_profile = next((p for p in instance.profiles.all() if p.is_default), None)
        exp = default_profile.exp_date if default_profile else None
        if exp:
            exp_utc = exp.astimezone(dt_tz.utc) if exp.tzinfo else exp.replace(tzinfo=dt_tz.utc)
            data["exp_date"] = exp_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        else:
            data["exp_date"] = None

        return data

    @staticmethod
    def _periodic_task_schedule(task):
        if not task:
            return {"enabled": False, "last_run_at": None, "next_run_at": None}

        last_run = task.last_run_at
        next_run = None
        if task.enabled:
            try:
                reference = last_run or task.date_changed or timezone.now()
                seconds = max(0, float(task.schedule.is_due(reference).next))
                next_run = timezone.now() + timedelta(seconds=seconds)
            except Exception:
                logger.warning(
                    "Could not calculate next run for periodic task %s",
                    task.name,
                    exc_info=True,
                )
        return {
            "enabled": bool(task.enabled),
            "last_run_at": last_run,
            "next_run_at": next_run,
        }

    def get_live_refresh_schedule(self, obj):
        return self._periodic_task_schedule(obj.refresh_task)

    def get_vod_refresh_schedule(self, obj):
        return self._periodic_task_schedule(obj.vod_refresh_task)

    def get_catalog_counts(self, obj):
        custom = obj.custom_properties or {}
        live = custom.get("live_catalog_counts") or {}
        vod = custom.get("vod_catalog_counts") or {}

        def counts(values):
            return {
                "original": int(values.get("provider_total") or 0),
                "selected": int(values.get("selected_total") or 0),
            }

        return {
            "live": counts(live),
            "movies": counts(vod.get("movies") or {}),
            "series": counts(vod.get("series") or {}),
        }

    def update(self, instance, validated_data):
        # Pop exp_date — it's written to the default profile, not the account
        exp_date = validated_data.pop("exp_date", "__NOT_SET__")

        # Pop cron_expression before it reaches model fields
        # If not present (partial update), preserve the existing cron from the PeriodicTask
        if "cron_expression" in validated_data:
            cron_expr = validated_data.pop("cron_expression")
        else:
            cron_expr = ""
            if instance.refresh_task_id and instance.refresh_task and instance.refresh_task.crontab:
                ct = instance.refresh_task.crontab
                cron_expr = f"{ct.minute} {ct.hour} {ct.day_of_month} {ct.month_of_year} {ct.day_of_week}"
        instance._cron_expression = cron_expr

        if "vod_cron_expression" in validated_data:
            vod_cron_expr = validated_data.pop("vod_cron_expression")
        else:
            vod_cron_expr = ""
            if (
                instance.vod_refresh_task_id
                and instance.vod_refresh_task
                and instance.vod_refresh_task.crontab
            ):
                ct = instance.vod_refresh_task.crontab
                vod_cron_expr = (
                    f"{ct.minute} {ct.hour} {ct.day_of_month} "
                    f"{ct.month_of_year} {ct.day_of_week}"
                )
        instance._vod_cron_expression = vod_cron_expr

        # Handle enable_vod preference and auto_enable_new_groups settings
        enable_vod = validated_data.pop("enable_vod", None)
        auto_enable_new_groups_live = validated_data.pop("auto_enable_new_groups_live", None)
        auto_enable_new_groups_vod = validated_data.pop("auto_enable_new_groups_vod", None)
        auto_enable_new_groups_series = validated_data.pop("auto_enable_new_groups_series", None)
        use_group_rules_live = validated_data.pop("use_group_rules_live", None)
        use_group_rules_movie = validated_data.pop("use_group_rules_movie", None)
        use_group_rules_series = validated_data.pop("use_group_rules_series", None)

        # Merge client-supplied custom_properties over the existing blob
        # so unrelated keys persist. The dedicated preference fields below
        # overwrite their corresponding keys; clients should set those via
        # the typed top-level fields rather than the custom_properties
        # payload.
        incoming_custom = {}
        if "custom_properties" in validated_data:
            incoming_custom = validated_data["custom_properties"] or {}
            if not isinstance(incoming_custom, dict):
                incoming_custom = ensure_custom_properties_dict(incoming_custom)
        existing_custom = instance.custom_properties or {}
        if not isinstance(existing_custom, dict):
            existing_custom = ensure_custom_properties_dict(existing_custom)
        custom_props = {**existing_custom, **incoming_custom}

        if enable_vod is not None:
            custom_props["enable_vod"] = enable_vod
        if auto_enable_new_groups_live is not None:
            custom_props["auto_enable_new_groups_live"] = auto_enable_new_groups_live
        if auto_enable_new_groups_vod is not None:
            custom_props["auto_enable_new_groups_vod"] = auto_enable_new_groups_vod
        if auto_enable_new_groups_series is not None:
            custom_props["auto_enable_new_groups_series"] = auto_enable_new_groups_series
        if use_group_rules_live is not None:
            custom_props["use_group_rules_live"] = use_group_rules_live
        if use_group_rules_movie is not None:
            custom_props["use_group_rules_movie"] = use_group_rules_movie
        if use_group_rules_series is not None:
            custom_props["use_group_rules_series"] = use_group_rules_series

        validated_data["custom_properties"] = custom_props

        # Pop out channel group memberships so we can handle them manually
        channel_group_data = validated_data.pop("channel_group", [])

        # First, update the M3UAccount itself
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        # Prepare a list of memberships to update
        memberships_to_update = []
        for group_data in channel_group_data:
            group = group_data.get("channel_group")
            enabled = group_data.get("enabled")

            try:
                membership = ChannelGroupM3UAccount.objects.get(
                    m3u_account=instance, channel_group=group
                )
                membership.enabled = enabled
                memberships_to_update.append(membership)
            except ChannelGroupM3UAccount.DoesNotExist:
                continue

        # Perform the bulk update
        if memberships_to_update:
            ChannelGroupM3UAccount.objects.bulk_update(
                memberships_to_update, ["enabled"]
            )

        # Write exp_date through to the default profile.
        # Use a fresh DB query (not the prefetch cache) so we get the profile
        # object AFTER the post_save signal (create_profile_for_m3u_account)
        # has already updated max_streams, avoiding a stale-value overwrite.
        if exp_date != "__NOT_SET__":
            default_profile = instance.profiles.filter(is_default=True).first()
            if default_profile:
                default_profile.exp_date = exp_date
                default_profile.save(update_fields=['exp_date'])
            # Invalidate the profiles prefetch cache so to_representation
            # sees the updated exp_date rather than the pre-request snapshot.
            if '_prefetched_objects_cache' in instance.__dict__:
                instance._prefetched_objects_cache.pop('profiles', None)

        return instance

    def create(self, validated_data):
        account_template = validated_data.pop("account_template", None)
        # Pop exp_date — it's written to the default profile after creation
        exp_date = validated_data.pop("exp_date", None)

        # Pop cron_expression — it's not a model field
        cron_expr = validated_data.pop("cron_expression", "")
        vod_cron_expr = validated_data.pop("vod_cron_expression", "")

        # Handle enable_vod preference and auto_enable_new_groups settings during creation
        enable_vod = validated_data.pop("enable_vod", False)
        auto_enable_new_groups_live = validated_data.pop("auto_enable_new_groups_live", True)
        auto_enable_new_groups_vod = validated_data.pop("auto_enable_new_groups_vod", True)
        auto_enable_new_groups_series = validated_data.pop("auto_enable_new_groups_series", True)
        use_group_rules_live = validated_data.pop("use_group_rules_live", True)
        use_group_rules_movie = validated_data.pop("use_group_rules_movie", True)
        use_group_rules_series = validated_data.pop("use_group_rules_series", True)

        # Parse existing custom_properties or create new
        custom_props = validated_data.get("custom_properties") or {}
        if not isinstance(custom_props, dict):
            custom_props = ensure_custom_properties_dict(custom_props)

        # Set preferences (default to True for auto_enable_new_groups)
        custom_props["enable_vod"] = enable_vod
        custom_props["auto_enable_new_groups_live"] = auto_enable_new_groups_live
        custom_props["auto_enable_new_groups_vod"] = auto_enable_new_groups_vod
        custom_props["auto_enable_new_groups_series"] = auto_enable_new_groups_series
        custom_props["use_group_rules_live"] = use_group_rules_live
        custom_props["use_group_rules_movie"] = use_group_rules_movie
        custom_props["use_group_rules_series"] = use_group_rules_series
        validated_data["custom_properties"] = custom_props

        # Build instance manually so we can attach transient attr before save triggers signal
        instance = M3UAccount(**validated_data)
        instance._cron_expression = cron_expr
        instance._vod_cron_expression = vod_cron_expr
        with transaction.atomic():
            instance.save()
            if account_template:
                from .account_templates import apply_account_template

                apply_account_template(instance, account_template)

        # Write exp_date through to the default profile created by post_save signal
        if exp_date is not None:
            default_profile = instance.profiles.filter(is_default=True).first()
            if default_profile:
                default_profile.exp_date = exp_date
                default_profile.save()

        return instance

    def get_filters(self, obj):
        # Sort over the prefetch cache; .order_by() would fire one SELECT
        # per account (viewset prefetches "filters").
        filters = sorted(obj.filters.all(), key=lambda f: f.order)
        return M3UFilterSerializer(filters, many=True).data

    def get_earliest_expiration(self, obj):
        """Return the soonest exp_date across all active profiles for this account."""
        # Filter in Python over the prefetch cache to avoid an extra query per account.
        expiring = [p.exp_date for p in obj.profiles.all() if p.is_active and p.exp_date]
        if not expiring:
            return None
        exp = min(expiring)
        exp_utc = exp.astimezone(dt_tz.utc) if exp.tzinfo else exp.replace(tzinfo=dt_tz.utc)
        return exp_utc.strftime('%Y-%m-%dT%H:%M:%SZ')

    def get_all_expirations(self, obj):
        """Return exp_date info for every profile that has one (for tooltip)."""
        # Filter in Python over the prefetch cache to avoid an extra query per account.
        profiles = sorted(
            (p for p in obj.profiles.all() if p.exp_date),
            key=lambda p: p.exp_date,
        )
        return [
            {
                "profile_id": p.id,
                "profile_name": p.name,
                "exp_date": (p.exp_date.astimezone(dt_tz.utc) if p.exp_date.tzinfo else p.exp_date.replace(tzinfo=dt_tz.utc)).strftime('%Y-%m-%dT%H:%M:%SZ'),
                "is_active": p.is_active,
            }
            for p in profiles
        ]


class ServerGroupSerializer(serializers.ModelSerializer):
    """Serializer for Server Group"""

    class Meta:
        model = ServerGroup
        fields = ["id", "name"]
