"""
Resource detection and adaptive parallelism for EPG processing.

This module implements smart resource detection to choose between sequential
and parallel EPG processing modes based on available system resources.

Designed to work safely on hardware ranging from Raspberry Pi to dedicated servers.
"""

import os
import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

# Minimum requirements for parallel processing
MIN_MEMORY_MB = 1024  # Don't go parallel below 1GB available
MIN_WORKERS = 2       # Need at least 2 workers for parallelism to help
MAX_PARALLEL_TASKS_PER_GB = 10  # Cap task fan-out based on memory


@lru_cache(maxsize=1)
def detect_system_resources():
    """
    Detect available system resources for EPG processing decisions.

    Returns:
        dict with:
            - memory_mb: Available memory in MB
            - cpu_count: Number of CPU cores
            - is_constrained: True if this looks like constrained hardware
    """
    resources = {
        'memory_mb': 2048,  # Safe default
        'cpu_count': 2,
        'is_constrained': False,
    }

    try:
        import psutil

        # Get available memory (not total - what's actually usable)
        mem = psutil.virtual_memory()
        resources['memory_mb'] = mem.available // (1024 * 1024)

        # CPU count (physical cores, not logical)
        resources['cpu_count'] = psutil.cpu_count(logical=False) or 2

        # Detect constrained hardware
        total_mem_mb = mem.total // (1024 * 1024)
        resources['is_constrained'] = (
            total_mem_mb < 2048 or  # Less than 2GB total RAM
            resources['cpu_count'] <= 2
        )

        logger.debug(
            f"System resources: {resources['memory_mb']}MB available, "
            f"{resources['cpu_count']} cores, constrained={resources['is_constrained']}"
        )
    except ImportError:
        logger.warning("psutil not available - using conservative defaults")
    except Exception as e:
        logger.warning(f"Error detecting resources: {e} - using conservative defaults")

    return resources


def get_celery_worker_count():
    """
    Get the number of active Celery workers.

    This is the real constraint for parallel processing -
    you can't parallelize beyond your worker count.

    Returns:
        int: Number of active Celery workers (minimum 1)
    """
    try:
        from dispatcharr.celery import app

        # Inspect active workers
        inspect = app.control.inspect()
        active = inspect.active()

        if active is None:
            logger.debug("No response from Celery inspect - assuming single worker")
            return 1

        # Count workers, not tasks
        worker_count = len(active)
        logger.debug(f"Detected {worker_count} active Celery workers")
        return max(1, worker_count)

    except Exception as e:
        logger.warning(f"Error detecting Celery workers: {e} - assuming single worker")
        return 1


def calculate_optimal_parallelism(channel_count):
    """
    Calculate optimal parallelism settings for EPG processing.

    This function implements adaptive resource detection with conservative defaults
    to ensure the system works safely on constrained hardware while taking advantage
    of available resources on more powerful systems.

    Args:
        channel_count: Number of channels to process

    Returns:
        dict with:
            - enabled: Whether to use parallel processing
            - max_concurrent: Maximum concurrent task chunks
            - chunk_size: Channels per task chunk
            - reason: Human-readable explanation of the decision
    """
    from core.models import CoreSettings

    result = {
        'enabled': False,
        'max_concurrent': 1,
        'chunk_size': 20,  # Match existing sequential batch size
        'reason': 'Sequential mode (default)'
    }

    # Check for manual override first - user knows best
    try:
        parallel_setting = CoreSettings.objects.filter(key='epg_parallel_enabled').first()
        if parallel_setting:
            if parallel_setting.value.lower() in ('false', '0', 'no', 'disabled'):
                result['reason'] = 'Parallel disabled by user setting'
                return result
            elif parallel_setting.value.lower() in ('true', '1', 'yes', 'enabled'):
                # User explicitly enabled - skip auto-detection but still apply limits
                result['enabled'] = True
                result['reason'] = 'Parallel enabled by user setting'
                # Fall through to calculate safe limits
    except Exception:
        pass

    # Check manual concurrency limit
    try:
        concurrency_setting = CoreSettings.objects.filter(key='epg_parallel_max_concurrent').first()
        if concurrency_setting:
            result['max_concurrent'] = max(1, int(concurrency_setting.value))
    except Exception:
        pass

    # If user didn't explicitly enable, auto-detect
    if not result['enabled']:
        resources = detect_system_resources()
        worker_count = get_celery_worker_count()

        # Decision matrix for auto-detection
        if resources['is_constrained']:
            result['reason'] = f"Constrained hardware detected ({resources['memory_mb']}MB RAM)"
            return result

        if resources['memory_mb'] < MIN_MEMORY_MB:
            result['reason'] = f"Insufficient available memory ({resources['memory_mb']}MB < {MIN_MEMORY_MB}MB)"
            return result

        if worker_count < MIN_WORKERS:
            result['reason'] = f"Insufficient Celery workers ({worker_count} < {MIN_WORKERS})"
            return result

        # Small channel counts don't benefit from parallelism
        if channel_count < 50:
            result['reason'] = f"Too few channels to benefit ({channel_count} < 50)"
            return result

        # All checks passed - enable with calculated limits
        result['enabled'] = True
        result['reason'] = f"Auto-enabled ({worker_count} workers, {resources['memory_mb']}MB RAM)"

    # Calculate safe concurrency limits
    if result['enabled'] and result['max_concurrent'] == 1:
        resources = detect_system_resources()
        worker_count = get_celery_worker_count()

        # Limit by workers (primary constraint)
        max_by_workers = worker_count

        # Limit by memory (secondary constraint)
        # Each parallel task might use 50-100MB during XML parsing
        max_by_memory = resources['memory_mb'] // 100

        # Limit by channel count (no point spawning more tasks than chunks)
        max_by_channels = min(channel_count // result['chunk_size'], 100)  # Cap at 100 concurrent

        result['max_concurrent'] = max(1, min(
            max_by_workers,
            max_by_memory,
            max_by_channels,
            MAX_PARALLEL_TASKS_PER_GB * (resources['memory_mb'] // 1024)
        ))

        # Calculate chunk size - group channels to reduce task overhead
        # Check for manual chunk size override
        try:
            chunk_setting = CoreSettings.objects.filter(key='epg_parallel_chunk_size').first()
            if chunk_setting and int(chunk_setting.value) > 0:
                result['chunk_size'] = int(chunk_setting.value)
            elif channel_count > result['max_concurrent'] * 5:
                # Auto-calculate: aim for 10-20 task groups, not one task per channel
                result['chunk_size'] = max(10, channel_count // (result['max_concurrent'] * 2))
        except Exception:
            pass  # Use default chunk size

    logger.info(
        f"EPG parallelism: enabled={result['enabled']}, "
        f"max_concurrent={result['max_concurrent']}, "
        f"chunk_size={result['chunk_size']}, "
        f"reason='{result['reason']}'"
    )

    return result
