# dispatcharr/celery.py
import os
from celery import Celery
import logging
from celery.signals import task_postrun  # Add import for signals

# Initialize with defaults before Django settings are loaded
DEFAULT_LOG_LEVEL = 'DEBUG'

# Try multiple sources for log level in order of preference
def get_effective_log_level():
    # 1. Direct environment variable
    env_level = os.environ.get('DISPATCHARR_LOG_LEVEL', '').upper()
    if env_level and not env_level.startswith('$(') and not env_level.startswith('%('):
        return env_level

    # 2. Check temp file that may have been created by settings.py
    try:
        if os.path.exists('/tmp/dispatcharr_log_level'):
            with open('/tmp/dispatcharr_log_level', 'r') as f:
                file_level = f.read().strip().upper()
                if file_level:
                    return file_level
    except:
        pass

    # 3. Fallback to default
    return DEFAULT_LOG_LEVEL

# Get effective log level before Django loads
effective_log_level = get_effective_log_level()
print(f"Celery using effective log level: {effective_log_level}")

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'dispatcharr.settings')
app = Celery("dispatcharr")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Use environment variable for log level with fallback to INFO
CELERY_LOG_LEVEL = os.environ.get('DISPATCHARR_LOG_LEVEL', 'INFO').upper()
print(f"Celery using log level from environment: {CELERY_LOG_LEVEL}")

# Configure Celery logging
app.conf.update(
    worker_log_level=effective_log_level,
    worker_log_format='%(asctime)s %(levelname)s %(name)s: %(message)s',
    beat_log_level=effective_log_level,
    worker_hijack_root_logger=False,
    worker_task_log_format='%(asctime)s %(levelname)s %(task_name)s: %(message)s',
)

# Add memory cleanup after task completion
@task_postrun.connect  # Use the imported signal
def cleanup_task_memory(**kwargs):
    """Clean up memory and database connections after each task completes"""
    from django.db import connection
    
    # Get task name from kwargs
    task_name = kwargs.get('task').name if kwargs.get('task') else ''

    # Close database connection for this Celery worker process
    try:
        connection.close()
    except Exception:
        pass

    # Only run memory cleanup for memory-intensive tasks
    memory_intensive_tasks = [
        'apps.m3u.tasks.refresh_single_m3u_account',
        'apps.m3u.tasks.refresh_m3u_accounts',
        'apps.m3u.tasks.process_m3u_batch',
        'apps.m3u.tasks.process_xc_category',
        'apps.m3u.tasks.sync_auto_channels',
        'apps.epg.tasks.refresh_epg_data',
        'apps.epg.tasks.refresh_all_epg_data',
        'apps.epg.tasks.parse_programs_for_source',
        'apps.epg.tasks.parse_programs_for_tvg_id',
        'apps.channels.tasks.match_epg_channels',
        'core.tasks.rehash_streams'
    ]

    # Check if this is a memory-intensive task
    if task_name in memory_intensive_tasks:
        # Import cleanup_memory function
        from core.utils import cleanup_memory

        # Use the comprehensive cleanup function
        cleanup_memory(log_usage=True, force_collection=True)

        # Log memory usage if psutil is installed
        try:
            import psutil
            process = psutil.Process()
            if hasattr(process, 'memory_info'):
                mem = process.memory_info().rss / (1024 * 1024)
                print(f"Memory usage after {task_name}: {mem:.2f} MB")
        except (ImportError, Exception):
            pass
    else:
        # For non-intensive tasks, just log but don't force cleanup
        try:
            import psutil
            process = psutil.Process()
            if hasattr(process, 'memory_info'):
                mem = process.memory_info().rss / (1024 * 1024)
                if mem > 500:  # Only log if using more than 500MB
                    print(f"High memory usage detected in {task_name}: {mem:.2f} MB")
        except (ImportError, Exception):
            pass

@app.on_after_configure.connect
def setup_celery_logging(**kwargs):
    # Use our directly determined log level
    log_level = effective_log_level
    print(f"Celery configuring loggers with level: {log_level}")

    # Get the specific loggers that output potentially noisy messages
    for logger_name in ['celery.app.trace', 'celery.beat', 'celery.worker.strategy', 'celery.beat.Scheduler', 'celery.pool']:
        logger = logging.getLogger(logger_name)

        # Remove any existing filters first (in case this runs multiple times)
        for filter in logger.filters[:]:
            if hasattr(filter, '__class__') and filter.__class__.__name__ == 'SuppressFilter':
                logger.removeFilter(filter)

        # Add filtering for both INFO and DEBUG levels - only TRACE will show full logging
        if log_level not in ['TRACE']:
            # Add a custom filter to completely filter out the repetitive messages
            class SuppressFilter(logging.Filter):
                def filter(self, record):
                    # Return False to completely suppress these specific patterns
                    if (
                        "succeeded in" in getattr(record, 'msg', '') or
                        "Scheduler: Sending due task" in getattr(record, 'msg', '') or
                        "received" in getattr(record, 'msg', '') or
                        (logger_name == 'celery.pool' and "Apply" in getattr(record, 'msg', ''))
                    ):
                        return False  # Don't log these messages at all
                    return True  # Log all other messages

            # Add the filter to each logger
            logger.addFilter(SuppressFilter())

        # Set all Celery loggers to the configured level
        # This ensures they respect TRACE/DEBUG when set
        try:
            numeric_level = getattr(logging, log_level)
            logger.setLevel(numeric_level)
        except (AttributeError, TypeError):
            # If the log level string is invalid, default to DEBUG
            logger.setLevel(logging.DEBUG)
