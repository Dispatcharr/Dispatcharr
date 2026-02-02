from django.apps import AppConfig
from django.conf import settings
import os, logging

# Define TRACE level (5 is below DEBUG which is 10)
TRACE = 5
logging.addLevelName(TRACE, "TRACE")

# Add trace method to the Logger class
def trace(self, message, *args, **kwargs):
    """Log a message with TRACE level (more detailed than DEBUG)"""
    if self.isEnabledFor(TRACE):
        self._log(TRACE, message, args, **kwargs)

# Add the trace method to the Logger class
logging.Logger.trace = trace

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        # Import signals to ensure they get registered
        import core.signals

        # Validate event configuration at startup
        self._validate_event_configuration()

        # Emit system startup event (only in main process, not in autoreload)
        import sys
        if 'runserver' not in sys.argv or os.environ.get('RUN_MAIN') == 'true':
            self._emit_startup_event()
            self._register_shutdown_handler()

    def _validate_event_configuration(self):
        """Validate that all events are properly configured in level sets."""
        try:
            from core.events import validate_event_configuration
            validate_event_configuration()
        except ValueError as e:
            # Configuration error - log as error but don't crash the app
            logging.getLogger(__name__).error(f"Event configuration error: {e}")
        except Exception as e:
            # Unexpected error - log but continue
            logging.getLogger(__name__).debug(f"Could not validate event configuration: {e}")

    def _emit_startup_event(self):
        """Emit system.startup event when the application starts."""
        try:
            from core import events
            from version import VERSION
            events.emit('system.startup', None, version=VERSION)
        except Exception as e:
            # Don't let startup event failure break the app
            logging.getLogger(__name__).debug(f"Could not emit startup event: {e}")

    def _register_shutdown_handler(self):
        """Register a handler to emit system.shutdown on graceful shutdown."""
        import atexit

        def emit_shutdown():
            try:
                from core import events
                events.emit('system.shutdown', None)
            except Exception:
                pass  # Don't let shutdown event failure cause issues

        atexit.register(emit_shutdown)
