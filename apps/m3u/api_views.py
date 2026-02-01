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
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.core.cache import cache
import os
from rest_framework.decorators import action
from django.conf import settings
from .tasks import refresh_m3u_groups
import json

from .models import M3UAccount, M3UFilter, ServerGroup, M3UAccountProfile
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

    @action(detail=False, methods=["post"], url_path="validate-urls")
    def validate_urls(self, request):
        """
        Validate all URLs for an M3U account (tests each URL regardless of success).

        Request body:
        {
            "account_type": "XC" or "M3U",
            "server_url": "url1|url2|url3",
            "username": "...",  # Required for XC
            "password": "...",  # Required for XC
            "user_agent": "..."  # Optional
        }

        Returns:
        {
            "results": [
                {"url": "http://...", "success": true, "response_time_ms": 123},
                {"url": "http://...", "success": false, "error": "Connection refused"}
            ]
        }
        """
        import time
        import requests
        from core.utils import parse_failover_urls

        account_type = request.data.get("account_type", "M3U")
        server_url = request.data.get("server_url", "")
        username = request.data.get("username", "")
        password = request.data.get("password", "")
        user_agent_id = request.data.get("user_agent")

        # Parse the pipe-separated URLs
        urls = parse_failover_urls(server_url)

        if not urls:
            return Response(
                {"error": "No URLs provided to validate"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get user agent string
        user_agent_string = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        if user_agent_id:
            try:
                ua = UserAgent.objects.get(id=user_agent_id)
                user_agent_string = ua.user_agent
            except UserAgent.DoesNotExist:
                pass

        results = []

        for url in urls:
            result = {"url": url, "success": False, "error": None, "response_time_ms": None}
            start_time = time.time()

            try:
                if account_type == M3UAccount.Types.XC:
                    # For XC accounts, try to authenticate
                    from core.xtream_codes import Client as XCClient

                    # Normalize the URL like XCClient does
                    normalized_url = url.rstrip('/')
                    if '://' in normalized_url:
                        protocol, rest = normalized_url.split('://', 1)
                        domain = rest.split('/', 1)[0]
                        normalized_url = f"{protocol}://{domain}"

                    api_url = f"{normalized_url}/player_api.php"
                    params = {"username": username, "password": password}

                    response = requests.get(
                        api_url,
                        params=params,
                        headers={"User-Agent": user_agent_string},
                        timeout=(5, 5)  # 5s connect + 5s read = 10s max
                    )
                    response.raise_for_status()

                    # Check if response is valid JSON with user_info
                    data = response.json()
                    if data.get("user_info"):
                        result["success"] = True
                    else:
                        result["error"] = "Invalid response: no user_info"
                else:
                    # For M3U accounts, try a HEAD request or partial GET
                    response = requests.head(
                        url,
                        headers={"User-Agent": user_agent_string},
                        timeout=(5, 5),  # 5s connect + 5s read = 10s max
                        allow_redirects=True
                    )
                    # Accept 2xx and 3xx status codes
                    if response.status_code < 400:
                        result["success"] = True
                    else:
                        result["error"] = f"HTTP {response.status_code}"

            except requests.exceptions.Timeout:
                result["error"] = "Connection timed out"
            except requests.exceptions.ConnectionError as e:
                error_str = str(e)
                if "Name or service not known" in error_str or "getaddrinfo failed" in error_str:
                    result["error"] = "DNS resolution failed"
                elif "Connection refused" in error_str:
                    result["error"] = "Connection refused"
                else:
                    result["error"] = "Connection error"
            except requests.exceptions.JSONDecodeError:
                result["error"] = "Invalid JSON response"
            except Exception as e:
                result["error"] = str(e)[:100]

            result["response_time_ms"] = int((time.time() - start_time) * 1000)
            results.append(result)

        return Response({"results": results})

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
