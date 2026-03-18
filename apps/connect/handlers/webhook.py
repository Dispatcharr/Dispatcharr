# connect/handlers/webhook.py
import requests, json, logging
from .base import IntegrationHandler

logger = logging.getLogger(__name__)

class WebhookHandler(IntegrationHandler):
    def execute(self):
        url = self.integration.config.get("url")
        headers = self.integration.config.get("headers", {})
        logger.info(self.payload)

        try:
            parsed = json.loads(self.payload)
            headers["Content-Type"] = "application/json"
        except Exception:
            pass

        response = requests.post(url, data=self.payload, headers=headers, timeout=10)

        return {"status_code": response.status_code, "body": response.text, "success": response.ok}
