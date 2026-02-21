from rest_framework import serializers
from django.contrib.auth.models import Group, Permission
from .models import User
from apps.channels.models import ChannelProfile


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
    password = serializers.CharField(write_only=True)
    channel_profiles = serializers.PrimaryKeyRelatedField(
        queryset=ChannelProfile.objects.all(), many=True, required=False
    )
    api_key = serializers.CharField(read_only=True, allow_null=True)

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
            "is_active",
            "is_staff",
            "is_superuser",
            "last_login",
            "date_joined",
            "first_name",
            "last_name",
        ]

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

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if password:
            instance.set_password(password)

        instance.save()

        if channel_profiles is not None:
            instance.channel_profiles.set(channel_profiles)

        return instance
