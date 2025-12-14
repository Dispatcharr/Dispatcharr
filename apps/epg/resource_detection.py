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
MIN_CHANNELS_FOR_PARALLEL = 50  # Minimum channels to benefit from parallelism
DEFAULT_MAX_BATCHES = 6  # Default maximum concurrent task batches
ENV_MAX_BATCHES_KEY = 'EPG_MAX_CONCURRENT_BATCHES'  # Environment variable key
SETTING_MAX_BATCHES_KEY = 'epg_max_concurrent_batches'  # CoreSettings key


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


def celery_is_responsive():
    """
    Check if Celery broker is responsive.

    Returns:
        bool: True if broker is reachable, False otherwise
    """
    try:
        from dispatcharr.celery import app
        inspect = app.control.inspect(timeout=1.0)
        stats = inspect.stats()
        return stats is not None
    except Exception as e:
        logger.warning(f"Celery health check failed: {e}")
        return False


def get_celery_autoscale_max():
    """
    Detect Celery autoscale maximum from worker configuration.

    This checks worker stats for autoscaler settings rather than counting
    active workers. Works with both autoscale and fixed concurrency configs.

    Returns:
        int: Maximum worker capacity (from autoscale max or pool size)
    """
    try:
        from dispatcharr.celery import app

        inspect = app.control.inspect(timeout=1.0)
        stats = inspect.stats()

        if not stats:
            logger.debug("No Celery stats available, using default capacity")
            return DEFAULT_MAX_BATCHES

        # Get stats from first worker (all workers should have same config)
        worker_stats = next(iter(stats.values()))

        # Check autoscaler configuration first
        if 'autoscaler' in worker_stats and worker_stats['autoscaler']:
            autoscale_max = worker_stats['autoscaler'].get('max', 1)
            logger.debug(f"Detected Celery autoscale max: {autoscale_max}")
            return max(1, autoscale_max)

        # Fall back to pool max-concurrency for fixed worker pools
        if 'pool' in worker_stats and worker_stats['pool']:
            pool_max = worker_stats['pool'].get('max-concurrency', 1)
            logger.debug(f"Detected Celery pool max-concurrency: {pool_max}")
            return max(1, pool_max)

        logger.debug("Could not detect Celery capacity, using default")
        return DEFAULT_MAX_BATCHES

    except Exception as e:
        logger.warning(f"Error detecting Celery capacity: {e} - using default")
        return DEFAULT_MAX_BATCHES


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

        # Decision matrix for auto-detection (trust Celery autoscale!)

        # 1. Check Celery health (not worker count!)
        if not celery_is_responsive():
            result['reason'] = "Celery broker not responsive"
            return result

        # 2. Check constrained hardware
        if resources['is_constrained']:
            result['reason'] = f"Constrained hardware ({resources['memory_mb']}MB RAM)"
            return result

        # 3. Check available memory
        if resources['memory_mb'] < MIN_MEMORY_MB:
            result['reason'] = f"Low memory ({resources['memory_mb']}MB < {MIN_MEMORY_MB}MB)"
            return result

        # 4. Check channel count
        if channel_count < MIN_CHANNELS_FOR_PARALLEL:
            result['reason'] = f"Too few channels ({channel_count} < {MIN_CHANNELS_FOR_PARALLEL})"
            return result

        # All checks passed - enable parallel mode!
        # Celery autoscale will spawn workers as tasks queue up
        result['enabled'] = True
        result['reason'] = f"Auto-enabled ({channel_count} channels, {resources['memory_mb']}MB RAM)"

    # Calculate safe concurrency limits
    if result['enabled'] and result['max_concurrent'] == 1:
        import os
        resources = detect_system_resources()

        # Get max batches from Celery autoscale config (dynamically detected!)
        celery_max = get_celery_autoscale_max()

        # Check for environment variable override
        max_batches = celery_max
        env_max = os.environ.get(ENV_MAX_BATCHES_KEY)
        if env_max:
            try:
                max_batches = max(1, int(env_max))
                logger.debug(f"Using max batches from environment: {max_batches} (overriding detected {celery_max})")
            except ValueError:
                logger.warning(f"Invalid {ENV_MAX_BATCHES_KEY}={env_max}, using detected {celery_max}")

        # CoreSettings override takes precedence
        try:
            setting = CoreSettings.objects.filter(key=SETTING_MAX_BATCHES_KEY).first()
            if setting and setting.value:
                max_batches = max(1, int(setting.value))
                logger.debug(f"Using max batches from CoreSettings: {max_batches}")
        except Exception:
            pass

        # Limit by memory (50-100MB per task)
        max_by_memory = resources['memory_mb'] // 100

        # Calculate chunk size (manual override or default)
        chunk_size = result['chunk_size']
        try:
            chunk_setting = CoreSettings.objects.filter(key='epg_parallel_chunk_size').first()
            if chunk_setting and int(chunk_setting.value) > 0:
                chunk_size = int(chunk_setting.value)
        except Exception:
            pass

        # Limit by channels (don't create empty batches)
        max_by_channels = max(1, (channel_count + chunk_size - 1) // chunk_size)

        # Take minimum of all constraints
        result['max_concurrent'] = min(
            max_batches,        # Celery capacity (detected or configured)
            max_by_memory,      # Memory safety limit
            max_by_channels,    # Efficiency limit
            100                 # Absolute safety cap
        )
        result['chunk_size'] = chunk_size

    logger.info(
        f"EPG parallelism: enabled={result['enabled']}, "
        f"max_concurrent={result['max_concurrent']}, "
        f"chunk_size={result['chunk_size']}, "
        f"reason='{result['reason']}'"
    )

    return result
