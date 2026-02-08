# connect/utils.py
import logging
from django.template import Template, Context
from .models import EventSubscription, DeliveryLog
from .handlers.webhook import WebhookHandler
from .handlers.script import ScriptHandler

logger = logging.getLogger(__name__)

HANDLERS = {
    "webhook": WebhookHandler,
    "script": ScriptHandler,
}


def trigger_event(event_name, payload):
    logger.debug(f"Triggering connect event: {event_name} payload_keys={list((payload or {}).keys())}")
    subscriptions = (
        EventSubscription.objects.filter(event=event_name, enabled=True)
        .select_related("integration")
    )

    count = subscriptions.count()
    logger.info(f"Found {count} connect subscription(s) for event '{event_name}'")

    for sub in subscriptions:
        integration = sub.integration
        if not integration.enabled:
            logger.debug(f"Skipping disabled integration id={integration.id} name={integration.name}")
            continue

        # apply optional payload template
        final_payload = payload
        if sub.payload_template:
            try:
                template = Template(sub.payload_template)
                rendered = template.render(Context(payload))
                final_payload = {"message": rendered}
            except Exception as e:
                logger.error(f"Payload template render failed for subscription id={sub.id}: {e}")
                final_payload = payload

        handler_cls = HANDLERS.get(integration.type)
        if not handler_cls:
            DeliveryLog.objects.create(
                subscription=sub,
                status="failed",
                request_payload=final_payload,
                error_message=f"No handler for integration type '{integration.type}'",
            )
            logger.error(f"No handler for integration type '{integration.type}' (integration id={integration.id})")
            continue

        handler = handler_cls(integration, sub, final_payload)
        logger.debug(f"Executing handler type={integration.type} integration_id={integration.id} subscription_id={sub.id}")

        try:
            result = handler.execute()
            DeliveryLog.objects.create(
                subscription=sub,
                status="success" if result.get("success") else "failed",
                request_payload=final_payload,
                response_payload=result,
            )
            logger.info(f"Connect delivery succeeded for subscription id={sub.id} integration '{integration.name}'")
        except Exception as e:
            DeliveryLog.objects.create(
                subscription=sub,
                status="failed",
                request_payload=final_payload,
                error_message=str(e),
            )
            logger.error(f"Connect delivery failed for subscription id={sub.id} integration '{integration.name}': {e}")
