# connect/handlers/base.py
import abc

class IntegrationHandler(abc.ABC):
    def __init__(self, integration, subscription, payload):
        self.integration = integration
        self.subscription = subscription
        self.payload = payload

    @abc.abstractmethod
    def execute(self):
        pass
