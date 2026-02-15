# connect/handlers/webhook.py
import requests
from .base import IntegrationHandler

class WebhookHandler(IntegrationHandler):
    def execute(self):
        url = self.integration.config.get("url")
        headers = self.integration.config.get("headers", {})
        response = requests.post(url, json=self.payload, headers=headers, timeout=10)
        return {"status_code": response.status_code, "body": response.text, "success": response.ok}
