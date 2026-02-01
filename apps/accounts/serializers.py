import json

from rest_framework import serializers
from django.contrib.auth.models import Group, Permission
from .models import User
from apps.channels.models import ChannelProfile


# Valid navigation item IDs for validation
VALID_NAV_ITEM_IDS = {
    'channels', 'vods', 'sources', 'guide', 'dvr',
    'stats', 'plugins', 'users', 'logos', 'settings'
}
MAX_CUSTOM_PROPS_SIZE = 10240  # 10KB limit


def validate_nav_array(value, field_name):
    """Validate that a value is an array of strings."""
    if not isinstance(value, list):
        raise serializers.ValidationError(f"{field_name} must be an array")
    if len(value) > 50:
        raise serializers.ValidationError(f"{field_name} exceeds maximum length of 50 items")
    for item in value:
        if not isinstance(item, str):
            raise serializers.ValidationError(f"{field_name} items must be strings")
        if len(item) > 50:
            raise serializers.ValidationError(f"{field_name} item exceeds maximum length of 50 characters")


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

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "user_level",
            "password",
            "channel_profiles",
            "custom_properties",
            "avatar_config",
            "is_active",
            "is_staff",
            "is_superuser",
            "last_login",
            "date_joined",
            "first_name",
            "last_name",
        ]

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

        return value

    def create(self, validated_data):
        channel_profiles = validated_data.pop("channel_profiles", [])

        user = User(**validated_data)
        user.set_password(validated_data["password"])
        user.is_active = True
        user.save()

        user.channel_profiles.set(channel_profiles)

        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        channel_profiles = validated_data.pop("channel_profiles", None)

        # Merge custom_properties instead of replacing (prevents data loss)
        custom_properties = validated_data.pop("custom_properties", None)
        if custom_properties is not None:
            existing = instance.custom_properties or {}
            instance.custom_properties = {**existing, **custom_properties}

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()

        if channel_profiles is not None:
            instance.channel_profiles.set(channel_profiles)

        return instance
