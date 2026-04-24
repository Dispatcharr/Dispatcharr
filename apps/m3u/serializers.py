from core.utils import validate_flexible_url
from rest_framework import serializers, status
from rest_framework.response import Response
from .models import M3UAccount, M3UFilter, ServerGroup, M3UAccountProfile
from core.models import UserAgent
from apps.channels.models import ChannelGroup, ChannelGroupM3UAccount
from apps.channels.serializers import (
    ChannelGroupM3UAccountSerializer,
)
from datetime import timezone as dt_tz
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
    cron_expression = serializers.CharField(required=False, allow_blank=True, default="")

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
            "cron_expression",
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
            "earliest_expiration",
            "all_expirations",
            "exp_date",
        ]
        extra_kwargs = {
            "password": {
                "required": False,
                "allow_blank": True,
            },
        }

    def to_representation(self, instance):
        data = super().to_representation(instance)

        # Parse custom_properties to get VOD preference and auto_enable_new_groups settings
        custom_props = instance.custom_properties or {}

        data["enable_vod"] = custom_props.get("enable_vod", False)
        data["auto_enable_new_groups_live"] = custom_props.get("auto_enable_new_groups_live", True)
        data["auto_enable_new_groups_vod"] = custom_props.get("auto_enable_new_groups_vod", True)
        data["auto_enable_new_groups_series"] = custom_props.get("auto_enable_new_groups_series", True)

        # Derive cron_expression from the linked PeriodicTask's crontab (single source of truth)
        # But first check if we have a transient _cron_expression (from create/update before signal runs)
        cron_expr = ""
        if hasattr(instance, '_cron_expression'):
            cron_expr = instance._cron_expression
        elif instance.refresh_task_id and instance.refresh_task and instance.refresh_task.crontab:
            ct = instance.refresh_task.crontab
            cron_expr = f"{ct.minute} {ct.hour} {ct.day_of_month} {ct.month_of_year} {ct.day_of_week}"
        data["cron_expression"] = cron_expr

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

        # Handle enable_vod preference and auto_enable_new_groups settings
        enable_vod = validated_data.pop("enable_vod", None)
        auto_enable_new_groups_live = validated_data.pop("auto_enable_new_groups_live", None)
        auto_enable_new_groups_vod = validated_data.pop("auto_enable_new_groups_vod", None)
        auto_enable_new_groups_series = validated_data.pop("auto_enable_new_groups_series", None)

        # Get existing custom_properties
        custom_props = instance.custom_properties or {}

        # Update preferences
        if enable_vod is not None:
            custom_props["enable_vod"] = enable_vod
        if auto_enable_new_groups_live is not None:
            custom_props["auto_enable_new_groups_live"] = auto_enable_new_groups_live
        if auto_enable_new_groups_vod is not None:
            custom_props["auto_enable_new_groups_vod"] = auto_enable_new_groups_vod
        if auto_enable_new_groups_series is not None:
            custom_props["auto_enable_new_groups_series"] = auto_enable_new_groups_series

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
        # Pop exp_date — it's written to the default profile after creation
        exp_date = validated_data.pop("exp_date", None)

        # Pop cron_expression — it's not a model field
        cron_expr = validated_data.pop("cron_expression", "")

        # Handle enable_vod preference and auto_enable_new_groups settings during creation
        enable_vod = validated_data.pop("enable_vod", False)
        auto_enable_new_groups_live = validated_data.pop("auto_enable_new_groups_live", True)
        auto_enable_new_groups_vod = validated_data.pop("auto_enable_new_groups_vod", True)
        auto_enable_new_groups_series = validated_data.pop("auto_enable_new_groups_series", True)

        # Parse existing custom_properties or create new
        custom_props = validated_data.get("custom_properties", {})

        # Set preferences (default to True for auto_enable_new_groups)
        custom_props["enable_vod"] = enable_vod
        custom_props["auto_enable_new_groups_live"] = auto_enable_new_groups_live
        custom_props["auto_enable_new_groups_vod"] = auto_enable_new_groups_vod
        custom_props["auto_enable_new_groups_series"] = auto_enable_new_groups_series
        validated_data["custom_properties"] = custom_props

        # Build instance manually so we can attach transient attr before save triggers signal
        instance = M3UAccount(**validated_data)
        instance._cron_expression = cron_expr
        instance.save()

        # Write exp_date through to the default profile created by post_save signal
        if exp_date is not None:
            default_profile = instance.profiles.filter(is_default=True).first()
            if default_profile:
                default_profile.exp_date = exp_date
                default_profile.save()

        return instance

    def get_filters(self, obj):
        filters = obj.filters.order_by("order")
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
