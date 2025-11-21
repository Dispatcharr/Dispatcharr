from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.views import APIView
from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_action,
    permission_classes_by_method,
)
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.core.cache import cache
import os
from rest_framework.decorators import action
from django.conf import settings
from .tasks import refresh_m3u_groups
import json

from .models import M3UAccount, M3UFilter, ServerGroup, M3UAccountProfile, M3UAccountMac
from core.models import UserAgent
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

    queryset = M3UAccount.objects.prefetch_related("channel_group")
    serializer_class = M3UAccountSerializer

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def create(self, request, *args, **kwargs):
        # Handle file upload first, if any
        file_path = None
        if "file" in request.FILES:
            file = request.FILES["file"]
            file_name = file.name
            file_path = os.path.join("/data/uploads/m3us", file_name)

            os.makedirs(os.path.dirname(file_path), exist_ok=True)
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
            file_name = file.name
            file_path = os.path.join("/data/uploads/m3us", file_name)

            os.makedirs(os.path.dirname(file_path), exist_ok=True)
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
                group_id = setting.get("channel_group")
                enabled = setting.get("enabled", True)
                auto_sync = setting.get("auto_channel_sync", False)
                sync_start = setting.get("auto_sync_channel_start")
                custom_properties = setting.get("custom_properties", {})

                if group_id:
                    ChannelGroupM3UAccount.objects.update_or_create(
                        channel_group_id=group_id,
                        m3u_account=account,
                        defaults={
                            "enabled": enabled,
                            "auto_channel_sync": auto_sync,
                            "auto_sync_channel_start": sync_start,
                            "custom_properties": custom_properties,
                        },
                    )

            for setting in category_settings:
                category_id = setting.get("id")
                enabled = setting.get("enabled", True)
                custom_properties = setting.get("custom_properties", {})

                if category_id:
                    M3UVODCategoryRelation.objects.update_or_create(
                        category_id=category_id,
                        m3u_account=account,
                        defaults={
                            "enabled": enabled,
                            "custom_properties": custom_properties,
                        },
                    )

            return Response({"message": "Group settings updated successfully"})

        except Exception as e:
            return Response(
                {"error": f"Failed to update group settings: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )
    def _delete_expired_macs_impl(self, account):
        """
        Interne Logik zum Löschen abgelaufener/unklarer MACs.
        Löscht EXPIRED und UNKNOWN, sortiert Prioritäten neu und
        aktualisiert das mac_address-Feld auf Basis der verbleibenden MACs.
        Gibt (deleted_count, remaining_addresses) zurück.
        """
        from .models import M3UAccountMac
        from django.db import transaction
        import logging

        logger = logging.getLogger(__name__)

        if account.account_type != M3UAccount.Types.MAC:
            return 0, []

        with transaction.atomic():
            qs = account.macs.filter(
                status__in=[
                    M3UAccountMac.Status.EXPIRED,
                    M3UAccountMac.Status.UNKNOWN,
                ]
            )
            deleted_count = qs.count()
            qs.delete()

            remaining = list(account.macs.order_by("priority", "id"))
            # Prioritäten neu setzen
            for idx, m in enumerate(remaining):
                if m.priority != idx:
                    m.priority = idx
                    m.save(update_fields=["priority"])

            # mac_address-Feld aus verbleibenden MACs aufbauen
            mac_list = [m.address for m in remaining]
            account.mac_address = " ".join(mac_list)
            account.save(update_fields=["mac_address"])

        logger.info(
            "Deleted %s expired/unknown MACs for account %s; remaining MACs: %s",
            deleted_count,
            account.id,
            mac_list,
        )
        return deleted_count, mac_list

    @action(detail=True, methods=["post"], url_path="delete-expired-macs")
    def delete_expired_macs(self, request, pk=None):
        """
        Löscht alle EXPIRED- und UNKNOWN-MAC-Einträge für diesen Account.
        Wird vom Button im M3U-Manager verwendet (Pfad: delete-expired-macs/).
        """
        account = self.get_object()

        deleted_count, mac_list = self._delete_expired_macs_impl(account)

        # Aktualisierte Account-Daten zurückgeben (inkl. frischer MAC-Liste)
        serializer = self.get_serializer(account)
        return Response(
            {
                "deleted": deleted_count,
                "account": serializer.data,
                "remaining_macs": mac_list,
            }
        )

    @action(detail=True, methods=["post"], url_path="delete_expired_macs")
    def delete_expired_macs_underscore(self, request, pk=None):
        """
        Alias-Endpoint mit Unterstrich im Pfad, falls das Frontend
        /delete_expired_macs/ verwendet. Verwendet die gleiche Logik.
        """
        account = self.get_object()
        deleted_count, mac_list = self._delete_expired_macs_impl(account)
        serializer = self.get_serializer(account)
        return Response(
            {
                "deleted": deleted_count,
                "account": serializer.data,
                "remaining_macs": mac_list,
            }
        )

    @action(detail=True, methods=["delete"], url_path=r"macs/(?P<mac_id>[^/.]+)")
    def delete_single_mac(self, request, pk=None, mac_id=None):
        """
        Löscht eine einzelne MAC anhand ihrer ID (für das rote X im UI).
        """
        from .models import M3UAccountMac

        account = self.get_object()
        try:
            mac_obj = account.macs.get(id=mac_id)
        except M3UAccountMac.DoesNotExist:
            return Response(
                {"error": "MAC not found"},
                status=status.HTTP_404_NOT_FOUND,
            )

        mac_obj.delete()

        # Prioritäten neu setzen und mac_address aktualisieren
        remaining = list(account.macs.order_by("priority", "id"))
        for idx, m in enumerate(remaining):
            if m.priority != idx:
                m.priority = idx
                m.save(update_fields=["priority"])

        account.mac_address = " ".join(m.address for m in remaining)
        account.save(update_fields=["mac_address"])

        serializer = self.get_serializer(account)
        return Response(
            {
                "account": serializer.data,
            }
        )

    @action(detail=True, methods=["post"], url_path="reorder-macs")
    def reorder_macs(self, request, pk=None):
        """
        Passt die Reihenfolge (Priorität) der MACs an.
        Erwartet im Body: {"order": [mac_id1, mac_id2, ...]} in gewünschter Reihenfolge.
        """
        from .models import M3UAccountMac

        account = self.get_object()
        order = request.data.get("order", [])
        if not isinstance(order, list):
            return Response(
                {"error": "Field 'order' must be a list of MAC IDs."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Map bestehende MACs nach ID
        mac_qs = account.macs.all()
        mac_map = {str(m.id): m for m in mac_qs}

        next_idx = 0
        # Zuerst die IDs aus 'order' in genau dieser Reihenfolge
        for mac_id in order:
            m = mac_map.pop(str(mac_id), None)
            if m is None:
                continue
            if m.priority != next_idx:
                m.priority = next_idx
                m.save(update_fields=["priority"])
            next_idx += 1

        # Alle übrigen MACs hinten anhängen
        for m in mac_map.values():
            if m.priority != next_idx:
                m.priority = next_idx
                m.save(update_fields=["priority"])
            next_idx += 1

        remaining = list(account.macs.order_by("priority", "id"))
        account.mac_address = " ".join(m.address for m in remaining)
        account.save(update_fields=["mac_address"])

        serializer = self.get_serializer(account)
        return Response(
            {
                "account": serializer.data,
            }
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

    @swagger_auto_schema(
        operation_description="Triggers a refresh of all active M3U accounts",
        responses={202: "M3U refresh initiated"},
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

    @swagger_auto_schema(
        operation_description="Triggers a refresh of a single M3U account",
        responses={202: "M3U account refresh initiated"},
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

    @swagger_auto_schema(
        operation_description="Triggers a refresh of account information for a specific M3U profile",
        responses={202: "Account info refresh initiated", 400: "Profile not found or not XtreamCodes"},
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
