from core.utils import validate_flexible_url, ensure_custom_properties_dict
from rest_framework import serializers, status
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema_field
from .models import M3UAccount, M3UFilter, M3UGroupRule, ServerGroup, M3UAccountProfile
from .utils import parse_m3u_hash_keys
from .category_selection import category_selection_state
from core.models import UserAgent
from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount
from apps.channels.serializers import (
    ChannelGroupM3UAccountSerializer,
)
from datetime import timezone as dt_tz
from django.db import transaction
import logging
import json

logger = logging.getLogger(__name__)


def rule_match_identity(rule):
    """Compare identical predicates, not arbitrary regex equivalence or results."""
    if isinstance(rule, M3UGroupRule):
        if not rule.enabled or rule.requires_review:
            return None
        return (
            rule.scope,
            rule.regex_pattern,
            rule.case_sensitive,
        )
    if not rule.enabled:
        return None
    return (
        rule.filter_type,
        rule.regex_pattern,
        (rule.custom_properties or {}).get("case_sensitive", True),
    )


def validate_unique_rule_matches(rules):
    seen = {}
    for position, rule in enumerate(rules, 1):
        identity = rule_match_identity(rule)
        if identity is None:
            continue
        targets = rule_result_fields(rule)
        previous = seen.setdefault(identity, {})
        overlap = targets & previous.keys()
        if overlap:
            previous_position = min(previous[key] for key in overlap)
            raise serializers.ValidationError(
                {
                    "regex_pattern": (
                        f"Rules {previous_position} and {position} have an identical "
                        "active match. Edit the existing rule instead."
                    )
                }
            )
        previous.update({key: position for key in targets})


def rule_result_fields(rule):
    """Fields used by ordered coverage and duplicate validation."""
    if not isinstance(rule, M3UGroupRule):
        return {"import"}
    return set(rule.metadata_defaults or {}) | (
        {"import"} if rule.action != M3UGroupRule.Action.KEEP else set()
    )


class UniqueRuleMatchMixin:
    """Serialize account rule writes so concurrent saves cannot add duplicates."""

    def _validate_unique_match(self, account, values, instance=None):
        data = (
            {
                field: getattr(instance, field)
                for field in self.Meta.fields
                if not self.fields[field].read_only
            }
            if instance is not None
            else {}
        )
        candidate = self.Meta.model(**{**data, **values})
        identity = rule_match_identity(candidate)
        if identity is None:
            return
        existing = self.Meta.model.objects.filter(m3u_account=account).order_by(
            "order", "id"
        )
        if instance is not None:
            existing = existing.exclude(pk=instance.pk)
        for rule in existing:
            if (
                rule_match_identity(rule) == identity
                and rule_result_fields(rule) & rule_result_fields(candidate)
            ):
                raise serializers.ValidationError(
                    {
                        "regex_pattern": (
                            "An identical active match already exists "
                            f"(rule ID {rule.pk}). Edit that rule instead."
                        )
                    }
                )

    def create(self, validated_data):
        if self.context.get("validated_rule_list"):
            return super().create(validated_data)
        account = validated_data["m3u_account"]
        with transaction.atomic():
            M3UAccount.objects.select_for_update().get(pk=account.pk)
            self._validate_unique_match(account, validated_data)
            return super().create(validated_data)

    def update(self, instance, validated_data):
        if self.context.get("validated_rule_list"):
            return super().update(instance, validated_data)
        with transaction.atomic():
            M3UAccount.objects.select_for_update().get(pk=instance.m3u_account_id)
            instance.refresh_from_db()
            self._validate_unique_match(
                instance.m3u_account, validated_data, instance
            )
            return super().update(instance, validated_data)


class M3UFilterSerializer(UniqueRuleMatchMixin, serializers.ModelSerializer):
    """Serializer for M3U Filters"""

    class Meta:
        model = M3UFilter
        fields = [
            "id",
            "filter_type",
            "regex_pattern",
            "exclude",
            "enabled",
            "order",
            "custom_properties",
        ]

    def validate_regex_pattern(self, value):
        import regex

        if not value.strip():
            raise serializers.ValidationError("Enter a regular expression.")
        try:
            regex.compile(value)
        except regex.error as exc:
            raise serializers.ValidationError(
                f"Invalid regular expression: {exc}"
            ) from exc
        return value

    def validate_custom_properties(self, value):
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be an object.")
        if "case_sensitive" in value and not isinstance(value["case_sensitive"], bool):
            raise serializers.ValidationError("case_sensitive must be a boolean.")
        return value


class M3UGroupRuleSerializer(UniqueRuleMatchMixin, serializers.ModelSerializer):
    requires_review = serializers.BooleanField(read_only=True)
    match_field = serializers.ChoiceField(choices=("group_name",), required=False)
    match_mode = serializers.ChoiceField(choices=("any",), required=False)

    class Meta:
        model = M3UGroupRule
        fields = [
            "id",
            "scope",
            "match_field",
            "match_mode",
            "regex_pattern",
            "action",
            "case_sensitive",
            "enabled",
            "order",
            "metadata_defaults",
            "requires_review",
        ]
        extra_kwargs = {
            "action": {
                "help_text": (
                    "Choose enable, disable or reversible ignore. Saved keep results are "
                    "retained for review only and cannot run."
                )
            },
        }

    validate_regex_pattern = M3UFilterSerializer.validate_regex_pattern

    def to_representation(self, instance):
        data = super().to_representation(instance)
        if instance.requires_review:
            data["enabled"] = False
        return data

    def validate_metadata_defaults(self, value):
        from apps.vod.metadata import validate_source_metadata

        try:
            return validate_source_metadata(value)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc

    def validate(self, attrs):
        scope = attrs.get("scope", getattr(self.instance, "scope", None))
        existing = self.instance or self.context.get(
            "existing_group_rules", {}
        ).get(attrs.get("preview_id"))
        action = attrs.get("action", getattr(self.instance, "action", "disable"))
        if action not in {M3UGroupRule.Action.ENABLE, M3UGroupRule.Action.DISABLE, M3UGroupRule.Action.IGNORE}:
            if (
                existing is None
                or action != existing.action
                or scope != existing.scope
                or attrs.get("enabled", False)
            ):
                raise serializers.ValidationError({
                    "action": (
                        "Choose Enabled, Disabled or Ignore. Removed "
                        "import results are paused until explicitly replaced."
                    )
                })
            attrs["enabled"] = False
        elif existing is not None and existing.requires_review:
            attrs.setdefault("enabled", False)
        match_field = attrs.get(
            "match_field", getattr(existing, "match_field", "group_name")
        )
        match_mode = attrs.get(
            "match_mode", getattr(existing, "match_mode", "any")
        )
        if match_field != "group_name" or match_mode != "any":
            raise serializers.ValidationError(
                {"match_field": "Import rules match category names only."}
            )
        metadata = attrs.get(
            "metadata_defaults", getattr(self.instance, "metadata_defaults", {})
        )
        if scope == M3UGroupRule.Scope.LIVE and metadata:
            raise serializers.ValidationError(
                {"metadata_defaults": (
                    "Metadata defaults are available for VOD categories only."
                )}
            )
        return attrs


class M3UFilterPreviewRowSerializer(M3UFilterSerializer):
    preview_id = serializers.CharField(max_length=128)

    class Meta(M3UFilterSerializer.Meta):
        fields = M3UFilterSerializer.Meta.fields + ["preview_id"]


class M3UGroupRulePreviewRowSerializer(M3UGroupRuleSerializer):
    preview_id = serializers.CharField(max_length=128)

    class Meta(M3UGroupRuleSerializer.Meta):
        fields = M3UGroupRuleSerializer.Meta.fields + ["preview_id"]


class M3UFilterPreviewRequestSerializer(serializers.Serializer):
    target_id = serializers.CharField(max_length=128)
    rules = M3UFilterPreviewRowSerializer(many=True, allow_empty=False)
    group_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        required=False,
    )


class M3UFilterSelectionSerializer(serializers.Serializer):
    group_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1), allow_empty=False,
    )


class M3UGroupRulePreviewRequestSerializer(serializers.Serializer):
    target_id = serializers.CharField(max_length=128)
    rules = M3UGroupRulePreviewRowSerializer(many=True, allow_empty=False)


class M3URuleOrderSerializer(serializers.Serializer):
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1))
    positions = serializers.ListField(
        child=serializers.IntegerField(min_value=0), required=False
    )
    scope = serializers.ChoiceField(choices=M3UGroupRule.Scope.choices, required=False)


class M3UGroupRuleOrderSerializer(M3URuleOrderSerializer):
    scope = serializers.ChoiceField(choices=M3UGroupRule.Scope.choices)


class M3UPreviewResultSerializer(serializers.Serializer):
    name = serializers.CharField()
    source_metadata = serializers.JSONField(required=False)
    group = serializers.CharField(required=False)
    result = serializers.CharField(required=False)
    relation_id = serializers.IntegerField(required=False)
    target_id = serializers.IntegerField(required=False)
    currently_enabled = serializers.BooleanField(required=False)
    currently_ignored = serializers.BooleanField(required=False)
    would_enable = serializers.BooleanField(allow_null=True, required=False)
    would_ignore = serializers.BooleanField(allow_null=True, required=False)
    action = serializers.CharField(required=False)
    item_count = serializers.IntegerField(required=False)
    metadata_defaults = serializers.JSONField(required=False)


class M3UGroupContentQuerySerializer(serializers.Serializer):
    scope = serializers.ChoiceField(choices=M3UGroupRule.Scope.choices)
    group_id = serializers.IntegerField(min_value=1)
    search = serializers.CharField(required=False, allow_blank=True, max_length=500)


class M3UGroupContentAvailabilitySerializer(serializers.Serializer):
    live = serializers.ListField(child=serializers.IntegerField())
    movie = serializers.ListField(child=serializers.IntegerField())
    series = serializers.ListField(child=serializers.IntegerField())


class M3URuleCoverageSerializer(serializers.Serializer):
    rule_id = serializers.CharField()
    count = serializers.IntegerField()
    field_counts = serializers.DictField(
        child=serializers.IntegerField(), required=False
    )


class M3UFilterAvailabilitySerializer(serializers.Serializer):
    ready = serializers.BooleanField()
    selected_count = serializers.IntegerField()
    refresh_in_progress = serializers.BooleanField()
    refresh_failed = serializers.BooleanField()
    last_completed_refresh = serializers.DateTimeField(allow_null=True)
    missing_group_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False,
    )
    can_load_provider = serializers.BooleanField(required=False)


class M3UPreviewResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = M3UPreviewResultSerializer(many=True)
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()
    content_source = serializers.ChoiceField(
        choices=("imported", "provider"), required=False
    )
    can_load_provider = serializers.BooleanField(required=False)
    inventory_count = serializers.IntegerField(required=False)
    catalog_complete = serializers.BooleanField(required=False)
    last_completed_refresh = serializers.DateTimeField(allow_null=True, required=False)
    refresh_in_progress = serializers.BooleanField(required=False)
    rule_coverage = M3URuleCoverageSerializer(many=True, required=False)


class M3UCategoryRuleUpdateSerializer(serializers.Serializer):
    target_id = serializers.IntegerField()
    enabled = serializers.BooleanField(allow_null=True)
    ignored = serializers.BooleanField(allow_null=True)
    metadata_defaults = serializers.JSONField()


class M3URuleApplyResponseSerializer(serializers.Serializer):
    updated = serializers.IntegerField()
    target_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    scope = serializers.CharField(required=False)
    enabled = serializers.BooleanField(required=False, allow_null=True)
    ignored = serializers.BooleanField(required=False, allow_null=True)
    category_updates = M3UCategoryRuleUpdateSerializer(many=True, required=False)


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


class M3URefreshScheduleSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    last_run_at = serializers.DateTimeField(allow_null=True)
    next_run_at = serializers.DateTimeField(allow_null=True)


class M3UCategorySelectionCountSerializer(serializers.Serializer):
    selected = serializers.IntegerField(min_value=0)
    total = serializers.IntegerField(min_value=0)


class M3UCategorySelectionCountsSerializer(serializers.Serializer):
    live = M3UCategorySelectionCountSerializer()
    movie = M3UCategorySelectionCountSerializer()
    series = M3UCategorySelectionCountSerializer()


class M3USetupActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=(
            "create_epg", "skip_epg", "retry_categories", "complete",
            "back_to_epg", "back_to_content", "back_to_account",
            "continue_content", "continue_epg", "continue_categories",
            "confirm_categories",
        )
    )


class M3UConnectionCheckSerializer(serializers.Serializer):
    account_id = serializers.PrimaryKeyRelatedField(
        queryset=M3UAccount.objects.all(), required=False, write_only=True,
    )
    account_type = serializers.ChoiceField(choices=M3UAccount.Types.choices)
    server_url = serializers.CharField(
        max_length=1000, validators=[validate_flexible_url],
    )
    username = serializers.CharField(
        max_length=255, required=False, allow_blank=True,
    )
    password = serializers.CharField(
        max_length=255, required=False, allow_blank=True, trim_whitespace=False,
        write_only=True,
    )
    user_agent = serializers.PrimaryKeyRelatedField(
        queryset=UserAgent.objects.all(), required=False, allow_null=True,
    )

    def validate_server_url(self, value):
        from urllib.parse import urlsplit

        try:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError()
            parsed.port
        except ValueError as exc:
            raise serializers.ValidationError(
                "Enter a complete HTTP or HTTPS URL."
            ) from exc
        return value

    def validate(self, attrs):
        from core.xtream_codes import normalize_server_url

        account = attrs.pop("account_id", None)
        if attrs["account_type"] == "XC":
            if not attrs.get("username"):
                raise serializers.ValidationError({
                    "username": "Enter the provider username.",
                })
            # Never send a stored secret to a caller-supplied different server.
            # A changed destination requires the password to be entered again.
            if (
                not attrs.get("password")
                and account
                and account.account_type == "XC"
                and normalize_server_url(attrs["server_url"])
                == normalize_server_url(account.server_url)
            ):
                attrs["password"] = account.password
        agent = attrs.pop("user_agent", None)
        attrs["user_agent_string"] = (
            agent.user_agent if agent and agent.user_agent
            else M3UAccount().get_user_agent_string()
        )
        return attrs


class M3UConnectionCheckResultSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    code = serializers.CharField()
    message = serializers.CharField()
    http_status = serializers.IntegerField(required=False)


class M3UMatchingEPGSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    is_active = serializers.BooleanField()
    status = serializers.CharField()
    source_type = serializers.CharField()
    updated_at = serializers.DateTimeField(allow_null=True)


class M3UAccountEPGSerializer(M3UMatchingEPGSerializer):
    epg_data_count = serializers.IntegerField(
        source="epgs.count", read_only=True, min_value=0,
    )


class M3UMatchingEPGResponseSerializer(serializers.Serializer):
    source = M3UAccountEPGSerializer(allow_null=True)
    can_create = serializers.BooleanField()
    other_sources = M3UMatchingEPGSerializer(many=True)


class M3UAccountSerializer(serializers.ModelSerializer):
    """Serializer for M3U Account"""

    filters = serializers.SerializerMethodField()
    group_rule_counts = serializers.SerializerMethodField()
    start_setup = serializers.BooleanField(write_only=True, required=False)
    setup_step = serializers.CharField(read_only=True)
    setup_categories_reviewed = serializers.SerializerMethodField()
    earliest_expiration = serializers.SerializerMethodField()
    all_expirations = serializers.SerializerMethodField()
    live_refresh_schedule = serializers.SerializerMethodField()
    vod_refresh_schedule = serializers.SerializerMethodField()
    category_selection_counts = serializers.SerializerMethodField()
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
    # Not a model field - stored under custom_properties["hash_key"]. A
    # missing key means this account inherits the global M3U Hash Key.
    hash_key = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, write_only=True
    )
    cron_expression = serializers.CharField(required=False, allow_blank=True, default="")
    vod_cron_expression = serializers.CharField(required=False, allow_blank=True, default="")

    def validate_hash_key(self, value):
        """Normalize and reject unknown hash key fields.

        Empty/null clears the override. Non-empty values are stripped,
        validated against the known field set, and stored as a clean CSV.
        """
        if value is None or value == "":
            return value
        try:
            keys = parse_m3u_hash_keys(value, strict=True)
        except ValueError as exc:
            raise serializers.ValidationError(str(exc)) from exc
        if not keys:
            raise serializers.ValidationError(
                "hash_key must include at least one valid field "
                "(name, url, tvg_id, m3u_id, group), or be empty to inherit "
                "the global default."
            )
        return ",".join(keys)

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
            "group_rule_counts",
            "user_agent",
            "profiles",
            "locked",
            "channel_groups",
            "category_selection_counts",
            "refresh_interval",
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
            "hash_key",
            "status",
            "start_setup",
            "setup_step",
            "setup_categories_reviewed",
            "last_message",
            "enable_vod",
            "auto_enable_new_groups_live",
            "auto_enable_new_groups_vod",
            "auto_enable_new_groups_series",
            "earliest_expiration",
            "all_expirations",
            "exp_date",
        ]
        extra_kwargs = {
            "password": {
                "required": False,
                "allow_blank": True,
                "write_only": True,
            },
        }

    def validate(self, attrs):
        if self.instance is not None:
            attrs.pop("start_setup", None)
            return attrs
        if not attrs.get("start_setup"):
            return attrs
        errors = {}
        if attrs.get("account_type", M3UAccount.Types.STADNARD) == "XC":
            for field in ("server_url", "username", "password"):
                if not attrs.get(field):
                    errors[field] = "Required for a new Xtream Codes account."
        elif not attrs.get("server_url") and not attrs.get("file_path"):
            errors["server_url"] = "Enter a playlist URL or upload a file."
        if errors:
            raise serializers.ValidationError(errors)
        return attrs

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
        # Missing key means this account inherits the global M3U Hash Key.
        data["hash_key"] = custom_props.get("hash_key")

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
        if hasattr(instance, "_vod_cron_expression"):
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
        _HASH_KEY_NOT_SET = object()
        hash_key = validated_data.pop("hash_key", _HASH_KEY_NOT_SET)

        # Merge client-supplied custom_properties over the existing blob
        # so unrelated keys persist. The dedicated preference fields below
        # overwrite their corresponding keys; clients should set those via
        # the typed top-level fields rather than the custom_properties
        # payload. Raw properties cannot bypass hash-key validation or mark
        # the guided category selection as reviewed.
        incoming_custom = {}
        if "custom_properties" in validated_data:
            incoming_custom = validated_data["custom_properties"] or {}
            if not isinstance(incoming_custom, dict):
                incoming_custom = ensure_custom_properties_dict(incoming_custom)
            incoming_custom = {
                k: v for k, v in incoming_custom.items()
                if k not in {"hash_key", "setup_categories_reviewed"}
            }
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

        # A hash_key override is stored under custom_properties["hash_key"].
        # An empty/null value means "clear the override" - remove the key
        # entirely rather than storing a null/empty value, so the account
        # falls back to the global default.
        if hash_key is not _HASH_KEY_NOT_SET:
            if hash_key:
                custom_props["hash_key"] = hash_key
            else:
                custom_props.pop("hash_key", None)

        validated_data["custom_properties"] = custom_props

        # Pop out channel group memberships so we can handle them manually
        channel_group_data = validated_data.pop("channel_group", [])

        # First, update the M3UAccount itself
        previous_account_type = instance.account_type
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.update_setup_step_for_account_type(previous_account_type)
        instance.save()

        # Prepare a list of memberships to update
        memberships_to_update = []
        for group_data in channel_group_data:
            group = group_data.get("channel_group")

            try:
                membership = ChannelGroupM3UAccount.objects.get(
                    m3u_account=instance, channel_group=group
                )
                selection = category_selection_state(group_data, membership)
                membership.enabled = selection["enabled"]
                membership.ignored = selection["ignored"]
                memberships_to_update.append(membership)
            except ChannelGroupM3UAccount.DoesNotExist:
                continue

        # Perform the bulk update
        if memberships_to_update:
            ChannelGroupM3UAccount.objects.bulk_update(
                memberships_to_update, ["enabled", "ignored"]
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
        start_setup = validated_data.pop("start_setup", False)
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
        hash_key = validated_data.pop("hash_key", None)

        # Only the typed hash-key field and the setup action may write their
        # reserved properties.
        custom_props = validated_data.get("custom_properties") or {}
        if not isinstance(custom_props, dict):
            custom_props = ensure_custom_properties_dict(custom_props)
        custom_props = {
            k: v for k, v in custom_props.items()
            if k not in {"hash_key", "setup_categories_reviewed"}
        }

        # Set preferences (default to True for auto_enable_new_groups)
        custom_props["enable_vod"] = enable_vod
        custom_props["auto_enable_new_groups_live"] = auto_enable_new_groups_live
        custom_props["auto_enable_new_groups_vod"] = auto_enable_new_groups_vod
        custom_props["auto_enable_new_groups_series"] = auto_enable_new_groups_series
        # A hash_key override is stored under custom_properties["hash_key"];
        # a missing key means this account inherits the global default, so
        # only set it when a non-empty override was supplied.
        if hash_key:
            custom_props["hash_key"] = hash_key
        validated_data["custom_properties"] = custom_props

        # Build instance manually so we can attach transient attr before save triggers signal
        instance = M3UAccount(**validated_data)
        if start_setup:
            instance.setup_step = (
                M3UAccount.SetupStep.EPG
                if instance.account_type == M3UAccount.Types.XC
                else M3UAccount.SetupStep.CATEGORIES
            )
        instance._cron_expression = cron_expr
        instance._vod_cron_expression = vod_cron_expr
        instance.save()

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
        filters = sorted(obj.filters.all(), key=lambda f: (f.order, f.id))
        return M3UFilterSerializer(filters, many=True).data

    def get_group_rule_counts(self, obj) -> dict[str, int]:
        counts = {scope: 0 for scope in ("live", "movie", "series")}
        for rule in obj.group_rules.all():
            if rule.enabled and rule.action in ("enable", "disable", "ignore"):
                counts[rule.scope] += 1
        return counts

    @extend_schema_field(M3UCategorySelectionCountsSerializer)
    def get_category_selection_counts(self, obj):
        counts = self.context.get("vod_category_selection_counts")
        return obj.get_category_selection_counts(
            vod_counts=counts.get(obj.pk, {}) if counts is not None else None
        )

    @extend_schema_field(serializers.BooleanField)
    def get_setup_categories_reviewed(self, obj):
        return bool((obj.custom_properties or {}).get("setup_categories_reviewed"))

    @extend_schema_field(M3URefreshScheduleSerializer)
    def get_live_refresh_schedule(self, obj):
        return M3URefreshScheduleSerializer(obj.get_refresh_schedule()).data

    @extend_schema_field(M3URefreshScheduleSerializer)
    def get_vod_refresh_schedule(self, obj):
        return M3URefreshScheduleSerializer(obj.get_refresh_schedule(vod=True)).data

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
