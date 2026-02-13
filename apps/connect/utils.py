# connect/utils.py
import logging, json
from django.template import Template, Context
from .models import EventSubscription, DeliveryLog
from .handlers.webhook import WebhookHandler
from .handlers.script import ScriptHandler
from apps.plugins.loader import PluginManager

logger = logging.getLogger(__name__)

HANDLERS = {
    "webhook": WebhookHandler,
    "script": ScriptHandler,
}

SUPPORTED_EVENTS = {
    "channel_start": "Channel Started",
    "channel_stop": "Channel Stopped",
    "channel_reconnect": "Channel Reconnected",
    "channel_error": "Channel Error",
    "channel_failover": "Channel Failover",
    "stream_switch": "Stream Switch",
    "recording_start": "Recording Started",
    "recording_end": "Recording Ended",
    "epg_refresh": "EPG Refreshed",
    "m3u_refresh": "M3U Refreshed",
    "client_connect": "Client Connected",
    "client_disconnect": "Client Disconnected",
}


def trigger_event(event_name, payload):
    if event_name not in SUPPORTED_EVENTS:
        logger.debug(f"Unsupported event '{event_name}' - skipping")
        return

    logger.debug(
        f"Triggering connect event: {event_name} payload_keys={list((payload or {}).keys())}"
    )
    subscriptions = EventSubscription.objects.filter(
        event=event_name, enabled=True
    ).select_related("integration")

    count = subscriptions.count()
    logger.info(f"Found {count} connect subscription(s) for event '{event_name}'")

    # First, fetch all subscriptions and trigger
    for sub in subscriptions:
        integration = sub.integration
        if not integration.enabled:
            logger.debug(
                f"Skipping disabled integration id={integration.id} name={integration.name}"
            )
            continue

        # apply optional payload template
        final_payload = payload
        if sub.payload_template:
            try:
                template = Template(sub.payload_template)
                rendered = template.render(Context(payload))
                final_payload = {"message": rendered}
            except Exception as e:
                logger.error(
                    f"Payload template render failed for subscription id={sub.id}: {e}"
                )
                final_payload = payload

        handler_cls = HANDLERS.get(integration.type)
        if not handler_cls:
            DeliveryLog.objects.create(
                subscription=sub,
                status="failed",
                request_payload=final_payload,
                error_message=f"No handler for integration type '{integration.type}'",
            )
            logger.error(
                f"No handler for integration type '{integration.type}' (integration id={integration.id})"
            )
            continue

        handler = handler_cls(integration, sub, final_payload)
        logger.debug(
            f"Executing handler type={integration.type} integration_id={integration.id} subscription_id={sub.id}"
        )

        try:
            result = handler.execute()
            DeliveryLog.objects.create(
                subscription=sub,
                status="success" if result.get("success") else "failed",
                request_payload=final_payload,
                response_payload=result,
            )
            logger.info(
                f"Connect delivery succeeded for subscription id={sub.id} integration '{integration.name}'"
            )
        except Exception as e:
            DeliveryLog.objects.create(
                subscription=sub,
                status="failed",
                request_payload=final_payload,
                error_message=str(e),
            )
            logger.error(
                f"Connect delivery failed for subscription id={sub.id} integration '{integration.name}': {e}"
            )

    pm = PluginManager.get()
    pm.discover_plugins(sync_db=False, use_cache=True)
    plugins = pm.list_plugins()

    logger.debug(f"Checking {len(plugins)} plugins for event '{event_name}'")
    for plugin in plugins:
        if not plugin["enabled"]:
            logger.debug(f"Skipping disabled plugin id={plugin.key} name={plugin.name}")
            continue

        logger.debug(json.dumps(plugin))
        for action in plugin["actions"]:
            if "events" in action and event_name in action["events"]:
                key = plugin["key"]
                params = {"event": event_name, "payload": payload}
                action_name = action.get("label") or action.get("id")
                action_id = action.get("id")
                logger.debug(
                    f"Triggering plugin action for event '{event_name}' on plugin id={key} action={action_name}"
                )
                if action_id:
                    pm.run_action(key, action_id, params)
