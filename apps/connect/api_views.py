from rest_framework import viewsets, status
from rest_framework.pagination import PageNumberPagination
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.response import Response
from rest_framework.decorators import action
from django.utils import timezone
from .models import Integration, EventSubscription, DeliveryLog
from .serializers import (
    IntegrationSerializer,
    EventSubscriptionSerializer,
    DeliveryLogSerializer,
)
from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_action,
    IsAdmin,
)
from .handlers.webhook import WebhookHandler
from .handlers.script import ScriptHandler


class IntegrationViewSet(viewsets.ModelViewSet):
    queryset = Integration.objects.all()
    serializer_class = IntegrationSerializer

    def get_permissions(self):
        try:
            perms = permission_classes_by_action[self.action]
        except KeyError:
            # Respect view/action-specific permission_classes if provided; fallback to Authenticated
            perms = getattr(self, "permission_classes", [Authenticated])
        return [perm() for perm in perms]

    @action(detail=True, methods=["get"], url_path="subscriptions")
    def list_subscriptions(self, request, pk=None):
        qs = EventSubscription.objects.filter(integration_id=pk)
        serializer = EventSubscriptionSerializer(qs, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["put"], url_path=r"subscriptions/set")
    def set_subscriptions(self, request, pk=None):
        """
        Replace the integration's subscriptions with the provided list.
        Body format: [{"event": "channel_start", "enabled": true, "payload_template": "..."}, ...]
        Any existing subscriptions not in the list will be deleted; missing ones will be created/updated.
        """
        try:
            integration = Integration.objects.get(pk=pk)
        except Integration.DoesNotExist:
            return Response(
                {"detail": "Integration not found"}, status=status.HTTP_404_NOT_FOUND
            )

        data = request.data
        if not isinstance(data, list):
            return Response(
                {"detail": "Expected a list of subscriptions"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate incoming items using serializer (without integration field)
        # We'll attach the integration explicitly
        valid_events = set(evt for evt, _ in EventSubscription.EVENT_CHOICES)
        incoming = []
        for item in data:
            if not isinstance(item, dict):
                return Response(
                    {"detail": "Each subscription must be an object"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            event = item.get("event")
            if event not in valid_events:
                return Response(
                    {"detail": f"Invalid event: {event}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            incoming.append(
                {
                    "event": event,
                    "enabled": bool(item.get("enabled", True)),
                    "payload_template": item.get("payload_template"),
                }
            )

        incoming_events = {s["event"] for s in incoming}

        # Delete subscriptions that are no longer present
        EventSubscription.objects.filter(integration=integration).exclude(
            event__in=incoming_events
        ).delete()

        # Upsert incoming subscriptions
        updated = []
        for sub in incoming:
            obj, _created = EventSubscription.objects.update_or_create(
                integration=integration,
                event=sub["event"],
                defaults={
                    "enabled": sub["enabled"],
                    "payload_template": sub.get("payload_template"),
                },
            )
            updated.append(obj)

        serializer = EventSubscriptionSerializer(updated, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["post"], url_path="test", permission_classes=[IsAdmin])
    def test(self, request, pk=None):
        """
        Execute a saved integration (connect) with a dummy payload to verify configuration.
        """
        try:
            integration = Integration.objects.get(pk=pk)
        except Integration.DoesNotExist:
            return Response({"detail": "Integration not found"}, status=status.HTTP_404_NOT_FOUND)

        # Build a dummy payload similar to system events
        now = timezone.now().isoformat()
        dummy_payload = {
            "event": "test",
            "timestamp": now,
            "channel_name": "Test Channel",
            "stream_name": "Test Stream",
            "stream_url": "http://example.com/stream.m3u8",
            "channel_url": "http://example.com/stream.m3u8",
            "provider_name": "Test Provider",
            "profile_used": "Default",
            "test": True,
        }

        # Choose handler based on saved type
        if integration.type == "webhook":
            handler = WebhookHandler(integration, None, dummy_payload)
        elif integration.type == "script":
            handler = ScriptHandler(integration, None, dummy_payload)
        else:
            return Response(
                {"success": False, "error": f"Unsupported integration type: {integration.type}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = handler.execute()
            return Response(
                {
                    "success": bool(result.get("success")),
                    "type": integration.type,
                    "request_payload": dummy_payload,
                    "result": result,
                },
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response(
                {
                    "success": False,
                    "type": integration.type,
                    "request_payload": dummy_payload,
                    "error": str(e),
                },
                status=status.HTTP_502_BAD_GATEWAY,
            )


class EventSubscriptionViewSet(viewsets.ModelViewSet):
    queryset = EventSubscription.objects.all()
    serializer_class = EventSubscriptionSerializer


class DeliveryLogViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = DeliveryLog.objects.all().order_by("-created_at")
    serializer_class = DeliveryLogSerializer
    filter_backends = [DjangoFilterBackend]

    # Support server-side pagination with page_size query param
    class ConnectLogsPagination(PageNumberPagination):
        page_size = 50
        page_size_query_param = "page_size"
        max_page_size = 250

    pagination_class = ConnectLogsPagination

    def get_queryset(self):
        qs = super().get_queryset()

        # Optional filters: integration id and type
        integration_id = self.request.query_params.get("integration")
        if integration_id:
            qs = qs.filter(subscription__integration_id=integration_id)

        integration_type = self.request.query_params.get("type")
        if integration_type:
            qs = qs.filter(subscription__integration__type=integration_type)

        return qs
