from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_action,
    permission_classes_by_method,
)
from drf_spectacular.utils import extend_schema, OpenApiParameter
from drf_spectacular.types import OpenApiTypes
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.core.cache import cache
import os
from rest_framework.decorators import action
from django.conf import settings
from .tasks import refresh_m3u_groups
import json
import logging

logger = logging.getLogger(__name__)

from .models import M3UAccount, M3UFilter, ServerGroup, M3UAccountProfile
from core.models import UserAgent
from core.utils import safe_upload_path
from apps.channels.models import ChannelGroupM3UAccount
from core.serializers import UserAgentSerializer
from apps.vod.models import M3UVODCategoryRelation

from .serializers import (
    M3UAccountSerializer,
    M3UFilterSerializer,
    ServerGroupSerializer,
    M3UAccountProfileSerializer,
)

from .tasks import refresh_single_m3u_account, refresh_m3u_accounts, refresh_account_info
import json


class M3UAccountViewSet(viewsets.ModelViewSet):
    """Handles CRUD operations for M3U accounts"""

    queryset = M3UAccount.objects.select_related(
        "refresh_task__crontab", "refresh_task__interval"
    ).prefetch_related("channel_group", "profiles", "filters")
    serializer_class = M3UAccountSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())

        # Pre-aggregate stream counts for all accounts in one query so the
        # nested ChannelGroupM3UAccountSerializer never issues a COUNT per
        # group row. The serializer checks for this key and skips its own
        # per-instance query when it is present.
        from apps.channels.models import Stream
        from django.db.models import Count

        account_ids = list(queryset.values_list("id", flat=True))
        counts_qs = (
            Stream.objects.filter(m3u_account_id__in=account_ids)
            .values("m3u_account_id", "channel_group_id")
            .annotate(c=Count("id"))
        )
        stream_counts = {
            (row["m3u_account_id"], row["channel_group_id"]): row["c"]
            for row in counts_qs
        }

        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(
                page, many=True,
                context={**self.get_serializer_context(), "stream_counts": stream_counts},
            )
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(
            queryset, many=True,
            context={**self.get_serializer_context(), "stream_counts": stream_counts},
        )
        return Response(serializer.data)

    def create(self, request, *args, **kwargs):
        # Handle file upload first, if any
        file_path = None
        if "file" in request.FILES:
            file = request.FILES["file"]
            try:
                file_path = safe_upload_path(file.name, "/data/uploads/m3us")
            except ValueError:
                return Response({"detail": "Invalid filename."}, status=status.HTTP_400_BAD_REQUEST)

            os.makedirs("/data/uploads/m3us", exist_ok=True)
            with open(file_path, "wb+") as destination:
                for chunk in file.chunks():
                    destination.write(chunk)

            # Add file_path to the request data so it's available during creation
            request.data._mutable = True  # Allow modification of the request data
            request.data["file_path"] = (
                file_path  # Include the file path if a file was uploaded
            )

            # Handle the user_agent field - convert "null" string to None
            if "user_agent" in request.data and request.data["user_agent"] == "null":
                request.data["user_agent"] = None

            # Handle server_url appropriately
            if "server_url" in request.data and not request.data["server_url"]:
                request.data.pop("server_url")

            request.data._mutable = False  # Make the request data immutable again

        # Now call super().create() to create the instance
        response = super().create(request, *args, **kwargs)

        account_type = response.data.get("account_type")
        account_id = response.data.get("id")

        # Notify frontend that a new playlist was created
        from core.utils import send_websocket_update
        send_websocket_update('updates', 'update', {
            'type': 'playlist_created',
            'playlist_id': account_id
        })

        if account_type == M3UAccount.Types.XC:
            refresh_m3u_groups(account_id)

            # Check if VOD is enabled
            enable_vod = request.data.get("enable_vod", False)
            if enable_vod:
                from apps.vod.tasks import refresh_categories

                refresh_categories(account_id)

        # After the instance is created, return the response
        return response

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        old_vod_enabled = False

        # Check current VOD setting
        if instance.custom_properties:
            custom_props = instance.custom_properties or {}
            old_vod_enabled = custom_props.get("enable_vod", False)

        # Handle file upload first, if any
        file_path = None
        if "file" in request.FILES:
            file = request.FILES["file"]
            try:
                file_path = safe_upload_path(file.name, "/data/uploads/m3us")
            except ValueError:
                return Response({"detail": "Invalid filename."}, status=status.HTTP_400_BAD_REQUEST)

            os.makedirs("/data/uploads/m3us", exist_ok=True)
            with open(file_path, "wb+") as destination:
                for chunk in file.chunks():
                    destination.write(chunk)

            # Add file_path to the request data so it's available during creation
            request.data._mutable = True  # Allow modification of the request data
            request.data["file_path"] = (
                file_path  # Include the file path if a file was uploaded
            )

            # Handle the user_agent field - convert "null" string to None
            if "user_agent" in request.data and request.data["user_agent"] == "null":
                request.data["user_agent"] = None

            # Handle server_url appropriately
            if "server_url" in request.data and not request.data["server_url"]:
                request.data.pop("server_url")

            request.data._mutable = False  # Make the request data immutable again

            if instance.file_path and os.path.exists(instance.file_path):
                os.remove(instance.file_path)

        # Now call super().update() to update the instance
        response = super().update(request, *args, **kwargs)

        # Check if VOD setting changed and trigger refresh if needed
        new_vod_enabled = request.data.get("enable_vod", old_vod_enabled)

        if (
            instance.account_type == M3UAccount.Types.XC
            and not old_vod_enabled
            and new_vod_enabled
        ):
            # Create Uncategorized categories immediately so they're available in the UI
            from apps.vod.models import VODCategory, M3UVODCategoryRelation

            # Create movie Uncategorized category
            movie_category, _ = VODCategory.objects.get_or_create(
                name="Uncategorized",
                category_type="movie",
                defaults={}
            )

            # Create series Uncategorized category
            series_category, _ = VODCategory.objects.get_or_create(
                name="Uncategorized",
                category_type="series",
                defaults={}
            )

            # Create relations for both categories (disabled by default until first refresh)
            account_custom_props = instance.custom_properties or {}
            auto_enable_new = account_custom_props.get("auto_enable_new_groups_vod", True)

            M3UVODCategoryRelation.objects.get_or_create(
                category=movie_category,
                m3u_account=instance,
                defaults={
                    'enabled': auto_enable_new,
                    'custom_properties': {}
                }
            )

            M3UVODCategoryRelation.objects.get_or_create(
                category=series_category,
                m3u_account=instance,
                defaults={
                    'enabled': auto_enable_new,
                    'custom_properties': {}
                }
            )

            # Trigger full VOD refresh
            from apps.vod.tasks import refresh_vod_content

            refresh_vod_content.delay(instance.id)

        # After the instance is updated, return the response
        return response

    def partial_update(self, request, *args, **kwargs):
        """Handle partial updates with special logic for is_active field"""
        instance = self.get_object()

        # Check if we're toggling is_active
        if (
            "is_active" in request.data
            and instance.is_active != request.data["is_active"]
        ):
            # Set appropriate status based on new is_active value
            if request.data["is_active"]:
                request.data["status"] = M3UAccount.Status.IDLE
            else:
                request.data["status"] = M3UAccount.Status.DISABLED

        # Continue with regular partial update
        return super().partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        """
        Delete an M3U account and all auto-created channels attributed
        to it. Auto-created channels with no surviving provider have no
        useful state (they cannot sync, their streams are about to
        cascade away), so the delete is unconditional: the only
        question for the user is whether to confirm. Manual channels
        are untouched, even if they include streams from this account;
        those streams cascade away independently and the channels
        survive with their other streams. The legacy
        ``?cleanup_channels`` query parameter is accepted for backward
        compatibility but ignored.
        """
        instance = self.get_object()
        from apps.channels.models import Channel
        from apps.proxy.ts_proxy.services.channel_service import (
            ChannelService,
        )

        # Snapshot channels so proxy sessions can be stopped outside
        # the DB transaction. The pre_delete signal would otherwise
        # fire ChannelService.stop_channel (Redis pub / hgetall /
        # setex) per channel inside the atomic, holding the DB
        # connection across thousands of blocking RPCs and gumming up
        # the connection pool.
        channels_to_delete = list(
            Channel.objects.filter(
                auto_created=True,
                auto_created_by=instance,
            ).values_list("id", "uuid")
        )
        for _, channel_uuid in channels_to_delete:
            if not channel_uuid:
                continue
            try:
                ChannelService.stop_channel(str(channel_uuid))
            except Exception as e:
                logger.warning(
                    "Failed to stop proxy session for channel %s "
                    "during account cleanup: %s",
                    channel_uuid,
                    e,
                )

        channel_ids = [cid for cid, _ in channels_to_delete]
        # Channel + account writes share an atomic so an account
        # delete failure rolls back the channel deletes too. The
        # pre_delete signal will fire again here but its proxy stop
        # is fast on already-stopped channels (a single Redis check
        # returns "not found" immediately).
        with transaction.atomic():
            if channel_ids:
                _, per_model = Channel.objects.filter(
                    id__in=channel_ids
                ).delete()
                deleted_channels = per_model.get(
                    "dispatcharr_channels.Channel", 0
                )
            else:
                deleted_channels = 0
            response = super().destroy(request, *args, **kwargs)

        # Surface the channel count alongside the standard 204; the
        # confirmation toast renders the number to acknowledge what
        # the cascade actually removed.
        if response.status_code == status.HTTP_204_NO_CONTENT:
            return Response(
                {"deleted_channels": deleted_channels},
                status=status.HTTP_200_OK,
            )
        return response

    @extend_schema(
        responses={
            200: {
                "type": "object",
                "properties": {
                    "count": {"type": "integer"},
                    "sample_names": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    )
    @action(detail=True, methods=["get"], url_path="auto-created-channels-count")
    def auto_created_channels_count(self, request, pk=None):
        """
        Preview how many auto-created channels would be removed if the account
        were deleted with cleanup_channels=true. The frontend calls this when
        the user clicks Delete, to render a truthful confirmation dialog
        ("Also delete N channels auto-created by this provider?").
        """
        account = self.get_object()
        from apps.channels.models import Channel

        qs = Channel.objects.filter(
            auto_created=True, auto_created_by=account
        )
        count = qs.count()
        sample_names = list(qs.values_list("name", flat=True)[:5])
        return Response({"count": count, "sample_names": sample_names})

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="channel_group_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description=(
                    "ID of the ChannelGroup whose auto-created channels "
                    "should be repacked."
                ),
            ),
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "assigned": {"type": "integer"},
                    "released": {"type": "integer"},
                    "failed": {"type": "integer"},
                },
            },
        },
    )
    @action(detail=True, methods=["post"], url_path="repack-group")
    def repack_group(self, request, pk=None):
        """
        Manually re-pack visible channels in one of this account's
        groups into the group's [start, end] range. Override-pinned
        numbers are treated as reservations and skipped. Hidden channels
        without overrides have their channel_number set to NULL.

        Useful when the user has just finished customizing channels
        (setting overrides as pins, hiding unwanted streams) and wants
        the result reflected immediately rather than on the next M3U
        refresh. Also acts as a one-shot cleanup for groups that aren't
        running in compact mode but have accumulated gaps.
        """
        account = self.get_object()
        group_id_raw = request.query_params.get("channel_group_id")
        if not group_id_raw:
            return Response(
                {"detail": "channel_group_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            group_id = int(group_id_raw)
        except (TypeError, ValueError):
            return Response(
                {"detail": "channel_group_id must be an integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from apps.channels.models import ChannelGroupM3UAccount
        from apps.channels.compact_numbering import repack_group as _repack
        from core.utils import acquire_task_lock, release_task_lock

        # Share the lock that wraps the entire refresh-plus-sync pipeline
        # (`refresh_single_m3u_account`). The narrower
        # `refresh_m3u_account_groups` lock is released before
        # `sync_auto_channels` runs, so it would not protect this writer
        # from racing against the channel_number writes inside sync.
        if not acquire_task_lock("refresh_single_m3u_account", account.id):
            return Response(
                {"detail": "An M3U refresh is in progress for this account."},
                status=status.HTTP_409_CONFLICT,
            )
        try:
            # Re-fetch under the lock so a sync that just released its lock
            # cannot leave the cached group_relation reflecting pre-sync
            # custom_properties (auto_sync_channel_start/end, etc.).
            try:
                group_relation = ChannelGroupM3UAccount.objects.get(
                    m3u_account=account, channel_group_id=group_id
                )
            except ChannelGroupM3UAccount.DoesNotExist:
                return Response(
                    {"detail": "Group is not associated with this account"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            result = _repack(group_relation)
        finally:
            try:
                release_task_lock("refresh_single_m3u_account", account.id)
            except Exception as e:
                logger.warning(
                    f"Failed to release repack lock for account "
                    f"{account.id}: {e}"
                )
        return Response(result)

    @action(detail=True, methods=["post"], url_path="refresh-vod")
    def refresh_vod(self, request, pk=None):
        """Trigger VOD content refresh for XtreamCodes accounts"""
        account = self.get_object()

        if account.account_type != M3UAccount.Types.XC:
            return Response(
                {"error": "VOD refresh is only available for XtreamCodes accounts"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if VOD is enabled
        vod_enabled = False
        if account.custom_properties:
            custom_props = account.custom_properties or {}
            vod_enabled = custom_props.get("enable_vod", False)

        if not vod_enabled:
            return Response(
                {"error": "VOD is not enabled for this account"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            from apps.vod.tasks import refresh_vod_content

            refresh_vod_content.delay(account.id)
            return Response(
                {"message": f"VOD refresh initiated for account {account.name}"},
                status=status.HTTP_202_ACCEPTED,
            )
        except Exception as e:
            return Response(
                {"error": f"Failed to initiate VOD refresh: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=True, methods=["patch"], url_path="group-settings")
    def update_group_settings(self, request, pk=None):
        """Update auto channel sync settings for M3U account groups"""
        account = self.get_object()
        group_settings = request.data.get("group_settings", [])
        category_settings = request.data.get("category_settings", [])

        try:
            for setting in group_settings:
                start = setting.get("auto_sync_channel_start")
                end = setting.get("auto_sync_channel_end")
                if (start is not None and start < 1) or (
                    end is not None and end < 1
                ):
                    return Response(
                        {
                            "error": (
                                f"Channel group {setting.get('channel_group')}: "
                                f"channel range must be >= 1."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if start is not None and end is not None and end < start:
                    return Response(
                        {
                            "error": (
                                f"Channel group {setting.get('channel_group')}: "
                                f"auto_sync_channel_end must be >= "
                                f"auto_sync_channel_start."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            with transaction.atomic():
                group_objects = [
                    ChannelGroupM3UAccount(
                        channel_group_id=setting["channel_group"],
                        m3u_account=account,
                        enabled=setting.get("enabled", True),
                        auto_channel_sync=setting.get("auto_channel_sync", False),
                        auto_sync_channel_start=setting.get("auto_sync_channel_start"),
                        auto_sync_channel_end=setting.get("auto_sync_channel_end"),
                        custom_properties=setting.get("custom_properties", {}),
                    )
                    for setting in group_settings
                    if setting.get("channel_group")
                ]

                if group_objects:
                    ChannelGroupM3UAccount.objects.bulk_create(
                        group_objects,
                        update_conflicts=True,
                        unique_fields=["channel_group", "m3u_account"],
                        update_fields=[
                            "enabled",
                            "auto_channel_sync",
                            "auto_sync_channel_start",
                            "auto_sync_channel_end",
                            "custom_properties",
                        ],
                    )

                category_objects = [
                    M3UVODCategoryRelation(
                        category_id=setting["id"],
                        m3u_account=account,
                        enabled=setting.get("enabled", True),
                        custom_properties=setting.get("custom_properties", {}),
                    )
                    for setting in category_settings
                    if setting.get("id")
                ]

                if category_objects:
                    M3UVODCategoryRelation.objects.bulk_create(
                        category_objects,
                        update_conflicts=True,
                        unique_fields=["m3u_account", "category"],
                        update_fields=["enabled", "custom_properties"],
                    )

            return Response({"message": "Group settings updated successfully"})

        except Exception as e:
            return Response(
                {"error": f"Failed to update group settings: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )


class M3UFilterViewSet(viewsets.ModelViewSet):
    queryset = M3UFilter.objects.all()
    serializer_class = M3UFilterSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        m3u_account_id = self.kwargs["account_id"]
        return M3UFilter.objects.filter(m3u_account_id=m3u_account_id)

    def perform_create(self, serializer):
        # Get the account ID from the URL
        account_id = self.kwargs["account_id"]

        # # Get the M3UAccount instance for the account_id
        # m3u_account = M3UAccount.objects.get(id=account_id)

        # Save the 'm3u_account' in the serializer context
        serializer.context["m3u_account"] = account_id

        # Perform the actual save
        serializer.save(m3u_account_id=account_id)


class ServerGroupViewSet(viewsets.ModelViewSet):
    """Handles CRUD operations for Server Groups"""

    queryset = ServerGroup.objects.all()
    serializer_class = ServerGroupSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]


class RefreshM3UAPIView(APIView):
    """Triggers refresh for all active M3U accounts"""

    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @extend_schema(
        description="Triggers a refresh of all active M3U accounts",
    )
    def post(self, request, format=None):
        refresh_m3u_accounts.delay()
        return Response(
            {"success": True, "message": "M3U refresh initiated."},
            status=status.HTTP_202_ACCEPTED,
        )


class RefreshSingleM3UAPIView(APIView):
    """Triggers refresh for a single M3U account"""

    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @extend_schema(
        description="Triggers a refresh of a single M3U account",
    )
    def post(self, request, account_id, format=None):
        refresh_single_m3u_account.delay(account_id)
        return Response(
            {
                "success": True,
                "message": f"M3U account {account_id} refresh initiated.",
            },
            status=status.HTTP_202_ACCEPTED,
        )


class RefreshAccountInfoAPIView(APIView):
    """Triggers account info refresh for a single M3U account"""

    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]

    @extend_schema(
        description="Triggers a refresh of account information for a specific M3U profile",
    )
    def post(self, request, profile_id, format=None):
        try:
            from .models import M3UAccountProfile
            profile = M3UAccountProfile.objects.get(id=profile_id)
            account = profile.m3u_account

            if account.account_type != M3UAccount.Types.XC:
                return Response(
                    {
                        "success": False,
                        "error": "Account info refresh is only available for XtreamCodes accounts",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            refresh_account_info.delay(profile_id)
            return Response(
                {
                    "success": True,
                    "message": f"Account info refresh initiated for profile {profile.name}.",
                },
                status=status.HTTP_202_ACCEPTED,
            )
        except M3UAccountProfile.DoesNotExist:
            return Response(
                {
                    "success": False,
                    "error": "Profile not found",
                },
                status=status.HTTP_404_NOT_FOUND,
            )


class UserAgentViewSet(viewsets.ModelViewSet):
    """Handles CRUD operations for User Agents"""

    queryset = UserAgent.objects.all()
    serializer_class = UserAgentSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]


class M3UAccountProfileViewSet(viewsets.ModelViewSet):
    queryset = M3UAccountProfile.objects.all()
    serializer_class = M3UAccountProfileSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        m3u_account_id = self.kwargs["account_id"]
        return M3UAccountProfile.objects.filter(m3u_account_id=m3u_account_id)

    def perform_create(self, serializer):
        # Get the account ID from the URL
        account_id = self.kwargs["account_id"]

        # Get the M3UAccount instance for the account_id
        m3u_account = M3UAccount.objects.get(id=account_id)

        # Save the 'm3u_account' in the serializer context
        serializer.context["m3u_account"] = m3u_account

        # Perform the actual save
        serializer.save(m3u_account_id=m3u_account)
