"""
Developer Notification Sync Service

Handles syncing developer-defined notifications from the JSON file to the database.
This ensures users receive important notifications from the development team
about recommended settings, security updates, and other announcements.

JSON Schema (see fixtures/developer_notifications.json):
    {
        "id": str,                      # REQUIRED - Unique identifier (notification_key)
        "title": str,                   # REQUIRED - Notification heading
        "message": str,                 # REQUIRED - Notification body text

        "notification_type": str,       # OPTIONAL - 'version_update', 'setting_recommendation', 'announcement', 'warning', 'info' (default: 'info')
        "priority": str,                # OPTIONAL - 'low', 'normal', 'high', 'critical' (default: 'normal')
        "min_version": str | null,      # OPTIONAL - Minimum version (inclusive), e.g., "0.17.0" (default: null)
        "max_version": str | null,      # OPTIONAL - Maximum version (inclusive), e.g., "0.18.1" (default: null)
        "created_at": str,              # OPTIONAL - ISO timestamp for tracking
        "expires_at": str | null,       # OPTIONAL - ISO timestamp when notification expires (default: null)
        "condition": list[str],         # OPTIONAL - List of condition check names, AND logic (default: [])
        "user_level": str,              # OPTIONAL - 'all' or 'admin' (default: 'all')
        "action_url": str | null,       # OPTIONAL - Internal navigation URL (e.g., "/settings#network-access")
        "action_text": str | null,      # OPTIONAL - Text for action button (required if action_url is set)
    }

Condition Checks:
    Conditions are function names from CONDITION_CHECKS registry that evaluate
    whether a notification should be shown. All conditions must pass (AND logic).

    Available conditions:
        - 'm3u_epg_network_insecure': M3U/EPG endpoint allows access from anywhere

    To add new conditions:
        1. Define a function: check_your_condition(user) -> bool
        2. Add to CONDITION_CHECKS registry
        3. Reference in JSON: "condition": ["your_condition"]

Sync Behavior:
    - Runs on startup (see apps.py)
    - Runs when relevant settings change (see signals.py)
    - Adds new notifications if in version range and not expired
    - Updates existing notifications with latest data
    - Removes notifications that are:
        * No longer in JSON file
        * Out of current version range
        * Past expiration date
    - Sends websocket event to refresh frontend
    - Cache invalidated when triggering settings change
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from django.conf import settings
from django.db import models
from django.utils import timezone
from packaging import version

from version import __version__

logger = logging.getLogger(__name__)

# Path to developer notifications JSON file
NOTIFICATIONS_FILE = Path(__file__).parent / 'fixtures' / 'developer_notifications.json'


# ─────────────────────────────
# Condition Checks
# ─────────────────────────────
# Each condition function receives (user) and returns True if the notification should show

def check_network_access_is_default(user, endpoint: str = 'M3U_EPG') -> bool:
    """
    Check if network access settings for a specific endpoint are insecure (allow all).

    Args:
        user: The user object (unused but required for condition check signature)
        endpoint: The endpoint to check (e.g., 'M3U_EPG', 'XC_API')

    Returns:
        True if the notification should show (insecure settings detected)
    """
    from core.models import CoreSettings, NETWORK_ACCESS_KEY

    try:
        network_settings = CoreSettings._get_group(NETWORK_ACCESS_KEY, {})

        # Empty settings are secure (defaults to local network only)
        if not network_settings:
            return False

        # Get the specific endpoint's allowed networks (stored as comma-separated string)
        allowed_networks_str = network_settings.get(endpoint, '')
        if not allowed_networks_str:
            return False

        # Parse comma-separated network addresses
        allowed_networks = [net.strip() for net in allowed_networks_str.split(',')]

        # Check if settings allow access from anywhere (insecure)
        if '0.0.0.0/0' in allowed_networks or '::/0' in allowed_networks:
            return True

        return False
    except Exception as e:
        logger.warning(f"Error checking network_access_is_default condition for {endpoint}: {e}")
        return False


# Registry of all available condition checks
CONDITION_CHECKS: dict[str, Callable] = {
    'm3u_epg_network_insecure': lambda user: check_network_access_is_default(user, 'M3U_EPG'),
    # Add more conditions here as needed
    # 'transcode_not_configured': check_transcode_not_configured,
    # 'no_backup_configured': check_no_backup_configured,
}


# ─────────────────────────────
# Version Utilities
# ─────────────────────────────

def parse_version(version_str: str | None) -> version.Version | None:
    """Parse a version string, returning None if invalid or empty."""
    if not version_str:
        return None
    try:
        return version.parse(version_str)
    except Exception:
        return None


def is_version_in_range(
    current_version: str,
    min_version: str | None,
    max_version: str | None
) -> bool:
    """Check if current version is within the specified range."""
    current = parse_version(current_version)
    if not current:
        return True  # If we can't parse version, show notification

    min_ver = parse_version(min_version)
    max_ver = parse_version(max_version)

    if min_ver and current < min_ver:
        return False
    if max_ver and current > max_ver:
        return False

    return True


# ─────────────────────────────
# Notification Evaluation
# ─────────────────────────────

def evaluate_conditions(conditions: list[str] | str | None, user) -> bool:
    """
    Evaluate notification conditions for a user.
    All conditions must pass (AND logic).
    """
    if not conditions:
        return True

    # Normalize to list
    if isinstance(conditions, str):
        conditions = [conditions]

    for condition in conditions:
        if condition not in CONDITION_CHECKS:
            logger.warning(f"Unknown condition: {condition}")
            continue

        try:
            if not CONDITION_CHECKS[condition](user):
                return False
        except Exception as e:
            logger.error(f"Error evaluating condition {condition}: {e}")
            # On error, skip this condition (fail open)
            continue

    return True


def should_show_notification(notification_data: dict, user) -> bool:
    """
    Determine if a notification should be shown to a specific user.
    Checks version range, user level, and conditions.
    """
    # Check version range
    if not is_version_in_range(
        __version__,
        notification_data.get('min_version'),
        notification_data.get('max_version')
    ):
        return False

    # Check user level
    user_level = notification_data.get('user_level', 'all')
    if user_level == 'admin' and not getattr(user, 'is_superuser', False):
        return False

    # Check conditions
    conditions = notification_data.get('condition', [])
    if not evaluate_conditions(conditions, user):
        return False

    return True


# ─────────────────────────────
# Sync Service
# ─────────────────────────────

def load_developer_notifications() -> list[dict]:
    """Load notifications from the JSON file."""
    if not NOTIFICATIONS_FILE.exists():
        logger.warning(f"Developer notifications file not found: {NOTIFICATIONS_FILE}")
        return []

    try:
        with open(NOTIFICATIONS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data.get('notifications', [])
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing developer notifications JSON: {e}")
        return []
    except Exception as e:
        logger.error(f"Error loading developer notifications: {e}")
        return []


def sync_developer_notifications() -> dict[str, int]:
    """
    Sync developer notifications from JSON file to database.

    - Adds new notifications that don't exist in the DB
    - Removes DB notifications that are no longer in the JSON file
    - Updates existing notifications if they've changed

    Returns a dict with counts of added, updated, and removed notifications.
    """
    from core.models import SystemNotification

    results = {'added': 0, 'updated': 0, 'removed': 0, 'skipped': 0}

    notifications = load_developer_notifications()
    json_notification_keys = set()
    notifications_to_remove = set()  # Track notifications to remove (out of range or expired)

    for notif_data in notifications:
        notification_id = notif_data.get('id')
        if not notification_id:
            logger.warning("Notification missing 'id' field, skipping")
            results['skipped'] += 1
            continue

        json_notification_keys.add(notification_id)

        # Check version constraints (only add if current version is in range)
        if not is_version_in_range(
            __version__,
            notif_data.get('min_version'),
            notif_data.get('max_version')
        ):
            logger.debug(f"Notification {notification_id} not in version range, marking for removal")
            results['skipped'] += 1
            notifications_to_remove.add(notification_id)
            continue

        # Parse expires_at if provided
        expires_at = None
        if notif_data.get('expires_at'):
            try:
                expires_at = datetime.fromisoformat(
                    notif_data['expires_at'].replace('Z', '+00:00')
                )
                # Skip if already expired and mark for removal
                if expires_at < timezone.now():
                    logger.debug(f"Notification {notification_id} has expired, marking for removal")
                    results['skipped'] += 1
                    notifications_to_remove.add(notification_id)
                    continue
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid expires_at for {notification_id}: {e}")

        # Map notification_type from JSON to model choices
        type_mapping = {
            'version_update': SystemNotification.NotificationType.VERSION_UPDATE,
            'setting_recommendation': SystemNotification.NotificationType.SETTING_RECOMMENDATION,
            'announcement': SystemNotification.NotificationType.ANNOUNCEMENT,
            'warning': SystemNotification.NotificationType.WARNING,
            'info': SystemNotification.NotificationType.INFO,
        }
        notification_type = type_mapping.get(
            notif_data.get('notification_type', 'info'),
            SystemNotification.NotificationType.INFO
        )

        # Map priority
        priority_mapping = {
            'low': SystemNotification.Priority.LOW,
            'normal': SystemNotification.Priority.NORMAL,
            'high': SystemNotification.Priority.HIGH,
            'critical': SystemNotification.Priority.CRITICAL,
        }
        priority = priority_mapping.get(
            notif_data.get('priority', 'normal'),
            SystemNotification.Priority.NORMAL
        )

        # Prepare action_data
        action_data = {
            'action_url': notif_data.get('action_url'),
            'action_text': notif_data.get('action_text'),
            'condition': notif_data.get('condition', []),
            'min_version': notif_data.get('min_version'),
            'max_version': notif_data.get('max_version'),
            'user_level': notif_data.get('user_level', 'all'),
        }

        # Determine if admin-only based on user_level
        admin_only = notif_data.get('user_level', 'all') == 'admin'

        # Create or update the notification
        notification, created = SystemNotification.objects.update_or_create(
            notification_key=notification_id,
            defaults={
                'notification_type': notification_type,
                'priority': priority,
                'source': SystemNotification.Source.DEVELOPER,
                'title': notif_data.get('title', 'Notification'),
                'message': notif_data.get('message', ''),
                'action_data': action_data,
                'is_active': True,
                'admin_only': admin_only,
                'expires_at': expires_at,
            }
        )

        if created:
            logger.info(f"Added developer notification: {notification_id}")
            results['added'] += 1
        else:
            logger.debug(f"Updated developer notification: {notification_id}")
            results['updated'] += 1

    # Remove developer notifications that are:
    # - No longer in the JSON file, OR
    # - Out of version range for the current version, OR
    # - Expired
    removed_count, _ = SystemNotification.objects.filter(
        source=SystemNotification.Source.DEVELOPER
    ).filter(
        models.Q(notification_key__in=notifications_to_remove) |
        ~models.Q(notification_key__in=json_notification_keys)
    ).delete()

    if removed_count:
        logger.info(f"Removed {removed_count} obsolete/expired/out-of-range developer notification(s)")
        results['removed'] = removed_count

    logger.info(
        f"Developer notification sync complete: "
        f"{results['added']} added, {results['updated']} updated, "
        f"{results['removed']} removed, {results['skipped']} skipped"
    )

    # Send websocket notification to frontend to refresh notifications
    try:
        from core.utils import send_websocket_update
        send_websocket_update('updates', 'update', {
            'type': 'notifications_cleared',
        })
        logger.debug("Sent websocket notification for notifications refresh")
    except Exception as e:
        logger.warning(f"Failed to send websocket update: {e}")

    return results


def get_user_developer_notifications(user) -> list:
    """
    Get all developer notifications that should be shown to a specific user.
    Evaluates conditions and user_level for each notification.
    """
    from core.models import SystemNotification

    # Get all active developer notifications
    notifications = SystemNotification.objects.filter(
        source=SystemNotification.Source.DEVELOPER,
        is_active=True
    )

    # Filter by admin_only based on user
    if not getattr(user, 'is_superuser', False):
        notifications = notifications.filter(admin_only=False)

    # Filter by conditions
    result = []
    for notification in notifications:
        action_data = notification.action_data or {}

        # Evaluate conditions
        conditions = action_data.get('condition', [])
        if evaluate_conditions(conditions, user):
            result.append(notification)

    return result
