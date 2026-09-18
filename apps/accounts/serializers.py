import json
import re

from rest_framework import serializers
from django.contrib.auth.models import Group, Permission
from .models import User
from apps.channels.models import ChannelProfile


# Valid navigation item IDs for validation
VALID_NAV_ITEM_IDS = {
    'channels', 'vods', 'sources', 'guide', 'dvr',
    'stats', 'plugins', 'integrations', 'system', 'settings'
}
MAX_CUSTOM_PROPS_SIZE = 102400  # 100KB limit
SAFE_CREDENTIAL_RE = re.compile(r"^[A-Za-z0-9._@-]+$")


def validate_nav_array(value, field_name):
    """Validate that a value is an array of valid nav item ID strings."""
    if not isinstance(value, list):
        raise serializers.ValidationError(f"{field_name} must be an array")
    if len(value) > 50:
        raise serializers.ValidationError(f"{field_name} exceeds maximum length of 50 items")
    for item in value:
        if not isinstance(item, str):
            raise serializers.ValidationError(f"{field_name} items must be strings")
        if item not in VALID_NAV_ITEM_IDS:
            raise serializers.ValidationError(f"'{item}' is not a valid navigation item ID")


# 🔹 Fix for Permission serialization
class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = ["id", "name", "codename"]


# 🔹 Fix for Group serialization
class GroupSerializer(serializers.ModelSerializer):
    permissions = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Permission.objects.all()
    )  # ✅ Fixes ManyToManyField `_meta` error

    class Meta:
        model = Group
        fields = ["id", "name", "permissions"]


# 🔹 Fix for User serialization
class UserSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)
    channel_profiles = serializers.PrimaryKeyRelatedField(
        queryset=ChannelProfile.objects.all(), many=True, required=False
    )
    api_key = serializers.CharField(read_only=True, allow_null=True)
    vod_policy = serializers.SerializerMethodField()
    vod_policy_id = serializers.IntegerField(
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "api_key",
            "email",
            "user_level",
            "password",
            "channel_profiles",
            "custom_properties",
            "avatar_config",
            "stream_limit",
            "is_staff",
            "is_superuser",
            "last_login",
            "date_joined",
            "first_name",
            "last_name",
            "vod_policy",
            "vod_policy_id",
        ]

    def validate_vod_policy_id(self, value):
        if value is None:
            return None
        from apps.vod.models import VODAccessPolicy

        if not VODAccessPolicy.objects.filter(pk=value, is_active=True).exists():
            raise serializers.ValidationError("Unknown or inactive VOD output profile")
        return value

    def get_vod_policy(self, obj):
        from apps.vod.models import VODAccessPolicy

        prefetched = getattr(obj, "_prefetched_objects_cache", {}).get(
            "vod_access_policies"
        )
        if prefetched is None:
            assigned = list(
                obj.vod_access_policies.filter(is_active=True).order_by(
                    "is_default", "id"
                )[:1]
            )
        else:
            assigned = sorted(
                (policy for policy in prefetched if policy.is_active),
                key=lambda policy: (policy.is_default, policy.id),
            )[:1]
        if assigned:
            policy = assigned[0]
            inherited = False
        else:
            if not hasattr(self, "_default_vod_policy"):
                self._default_vod_policy = (
                    VODAccessPolicy.objects.filter(is_active=True, is_default=True)
                    .order_by("id")
                    .first()
                )
            policy = self._default_vod_policy
            inherited = policy is not None
        if not policy:
            return None
        return {
            "id": policy.id,
            "name": policy.name,
            "export_mode": policy.export_mode,
            "hard_constraints": policy.hard_constraints or {},
            "ranking": policy.ranking or [],
            "category_relation_ids": list(
                policy.vodpolicycategory_set.filter(enabled=True).values_list(
                    "category_relation_id", flat=True
                )
            ),
            "inherited": inherited,
        }

    def _assign_vod_policy(self, user, policy_id):
        from apps.vod.models import VODAccessPolicy

        for policy in VODAccessPolicy.objects.filter(users=user):
            policy.users.remove(user)
        if policy_id is not None:
            VODAccessPolicy.objects.get(pk=policy_id, is_active=True).users.add(user)

    def validate_username(self, value):
        if not SAFE_CREDENTIAL_RE.fullmatch(value):
            raise serializers.ValidationError(
                "Username may only contain letters, numbers, periods (.), underscores (_), at signs (@), and hyphens (-)"
            )
        return value

    def validate_custom_properties(self, value):
        """Validate custom_properties structure and size."""
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise serializers.ValidationError("custom_properties must be a dictionary")

        # Size limit check
        try:
            if len(json.dumps(value)) > MAX_CUSTOM_PROPS_SIZE:
                raise serializers.ValidationError(
                    f"custom_properties exceeds maximum size of {MAX_CUSTOM_PROPS_SIZE} bytes"
                )
        except (TypeError, ValueError):
            raise serializers.ValidationError("custom_properties contains non-serializable data")

        # Validate navOrder if present
        if 'navOrder' in value:
            validate_nav_array(value['navOrder'], 'navOrder')

        # Validate hiddenNav if present
        if 'hiddenNav' in value:
            validate_nav_array(value['hiddenNav'], 'hiddenNav')

        if (
            "xc_live_refresh_on_request" in value
            and not isinstance(value["xc_live_refresh_on_request"], bool)
        ):
            raise serializers.ValidationError(
                "xc_live_refresh_on_request must be a boolean"
            )

        request_interval = value.get(
            "xc_live_refresh_request_interval_minutes",
            55,
        )
        if (
            isinstance(request_interval, bool)
            or not isinstance(request_interval, int)
            or request_interval < 0
            or request_interval > 10080
        ):
            raise serializers.ValidationError(
                "xc_live_refresh_request_interval_minutes must be an integer "
                "between 0 and 10080"
            )

        wait_for_completion = value.get(
            "xc_live_refresh_wait_for_completion",
            False,
        )
        if not isinstance(wait_for_completion, bool):
            raise serializers.ValidationError(
                "xc_live_refresh_wait_for_completion must be a boolean"
            )

        wait_timeout = value.get("xc_live_refresh_wait_timeout_seconds", 15)
        if (
            isinstance(wait_timeout, bool)
            or not isinstance(wait_timeout, int)
            or wait_timeout < 1
            or wait_timeout > 60
        ):
            raise serializers.ValidationError(
                "xc_live_refresh_wait_timeout_seconds must be an integer "
                "between 1 and 60"
            )

        xc_password = value.get("xc_password")

        if xc_password and not SAFE_CREDENTIAL_RE.fullmatch(xc_password):
            raise serializers.ValidationError(
                "XC password may only contain letters, numbers, periods (.), underscores (_), at signs (@), and hyphens (-)"
            )

        allowed_m3u_profile_ids = value.get("allowed_m3u_profile_ids")
        if allowed_m3u_profile_ids is not None and (
            not isinstance(allowed_m3u_profile_ids, list)
            or any(
                not isinstance(profile_id, int) or isinstance(profile_id, bool) or profile_id <= 0
                for profile_id in allowed_m3u_profile_ids
            )
        ):
            raise serializers.ValidationError(
                "allowed_m3u_profile_ids must be a list of positive integer IDs"
            )

        return value

    def create(self, validated_data):
        channel_profiles = validated_data.pop("channel_profiles", [])
        vod_policy_id = validated_data.pop("vod_policy_id", serializers.empty)

        user = User(**validated_data)
        user.set_password(validated_data["password"])
        user.save()

        user.channel_profiles.set(channel_profiles)
        if vod_policy_id is not serializers.empty:
            self._assign_vod_policy(user, vod_policy_id)

        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        channel_profiles = validated_data.pop("channel_profiles", None)
        vod_policy_id = validated_data.pop("vod_policy_id", serializers.empty)

        # Merge custom_properties instead of replacing (prevents data loss)
        # null values are explicit deletions; all other values overwrite existing
        custom_properties = validated_data.pop("custom_properties", None)
        if custom_properties is not None:
            existing = instance.custom_properties or {}
            merged = dict(existing)
            for k, v in custom_properties.items():
                if v is None:
                    merged.pop(k, None)
                else:
                    merged[k] = v
            # Scrub stale nav IDs so the DB self-heals on next save
            for nav_field in ('navOrder', 'hiddenNav'):
                if nav_field in merged and isinstance(merged[nav_field], list):
                    merged[nav_field] = [
                        item for item in merged[nav_field]
                        if item in VALID_NAV_ITEM_IDS
                    ]
            instance.custom_properties = merged

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()

        if channel_profiles is not None:
            instance.channel_profiles.set(channel_profiles)

        if vod_policy_id is not serializers.empty:
            self._assign_vod_policy(instance, vod_policy_id)

        return instance
