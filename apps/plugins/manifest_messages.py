"""Trusted official plugin-registry manifest messages."""

from datetime import datetime, timezone as datetime_timezone
import re
import uuid
from urllib.parse import urlparse

from django.conf import settings
from django.utils import timezone

from version import __version__

from .models import PluginManifestMessageDismissal, PluginRepo


SEVERITIES = {"info", "success", "warning", "critical"}
TARGET_COMPARATOR = re.compile(r"^(<=|>=|<|>|=)(v?\d+\.\d+\.\d+)$")


def notification_key(message_id):
    return f"plugin-manifest-message-{message_id}"


def _parse_version(value):
    if not isinstance(value, str):
        return None
    value = value.removeprefix("v")
    parts = value.split(".")
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _matches_target(target):
    current = _parse_version(__version__)
    if current is None or not isinstance(target, str) or not target.strip():
        return False
    for comparator in target.split():
        match = TARGET_COMPARATOR.fullmatch(comparator)
        if not match:
            return False
        operator, version = match.groups()
        expected = _parse_version(version)
        if expected is None:
            return False
        if not {
            "<": current < expected,
            "<=": current <= expected,
            ">": current > expected,
            ">=": current >= expected,
            "=": current == expected,
        }[operator]:
            return False
    return True


def _parse_timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime_timezone.utc)
    except ValueError:
        return None


def validated_messages(manifest_data):
    """Return valid messages in source order, skipping malformed entries."""
    manifest = (manifest_data or {}).get("manifest", manifest_data or {})
    messages = manifest.get("messages", []) if isinstance(manifest, dict) else []
    if not isinstance(messages, list):
        return []

    valid = []
    for raw in messages:
        if not isinstance(raw, dict):
            continue
        try:
            message_id = uuid.UUID(raw.get("id", ""))
        except (ValueError, TypeError, AttributeError):
            continue
        if str(message_id) != raw.get("id") or message_id.version != 4:
            continue
        severity = raw.get("severity")
        if severity not in SEVERITIES or not isinstance(raw.get("body"), str):
            continue
        title = raw.get("title")
        if title is not None and not isinstance(title, str):
            continue
        link = raw.get("link")
        if link is not None:
            parsed = urlparse(link) if isinstance(link, str) else None
            if not parsed or parsed.scheme != "https" or not parsed.netloc:
                continue
        starts_at, expires_at = raw.get("starts_at"), raw.get("expires_at")
        if (starts_at is None) != (expires_at is None):
            continue
        start, expires = None, None
        if starts_at is not None:
            start, expires = _parse_timestamp(starts_at), _parse_timestamp(expires_at)
            if start is None or expires is None or start >= expires:
                continue
        target = raw.get("target")
        if target is not None and not _matches_target(target):
            # A syntactically valid non-matching target is retained so future
            # versions can evaluate it. Invalid targets are detected below.
            if not isinstance(target, str) or not target.split() or not all(TARGET_COMPARATOR.fullmatch(c) for c in target.split()):
                continue
        dev = raw.get("dev")
        if dev is not None and not isinstance(dev, bool):
            continue
        valid.append({
            "id": str(message_id), "severity": severity, "body": raw["body"],
            "title": title, "link": link, "starts_at": start, "expires_at": expires,
            "target": target, "dev": dev,
        })
    return valid


def is_eligible(message, now=None):
    now = now or timezone.now()
    if message["starts_at"] and now < message["starts_at"]:
        return False
    if message["expires_at"] and now >= message["expires_at"]:
        return False
    if message["target"] is not None and not _matches_target(message["target"]):
        return False
    return message["dev"] is None or message["dev"] == settings.DEBUG


def official_messages_for_user(user):
    messages = []
    for repo in PluginRepo.objects.filter(is_official=True, enabled=True):
        if repo.signature_verified is not True:
            continue
        manifest = (repo.cached_manifest or {}).get("manifest", repo.cached_manifest or {})
        source_repo = manifest.get("registry_name") or repo.name
        messages.extend(
            {
                **message,
                "source_repo": source_repo,
            }
            for message in validated_messages(repo.cached_manifest)
            if is_eligible(message)
        )
    dismissed = set(PluginManifestMessageDismissal.objects.filter(
        user=user, message_id__in=[message["id"] for message in messages]
    ).values_list("message_id", flat=True))
    return [
        {
            **{key: value for key, value in message.items() if key in {"id", "severity", "title", "body", "link"}},
            "source_repo": message["source_repo"],
        }
        for message in messages if uuid.UUID(message["id"]) not in dismissed
    ]


def dismiss_message(user, message_id):
    """Dismiss an ID only when it belongs to the currently trusted official manifest."""
    try:
        message_id = uuid.UUID(str(message_id))
    except (ValueError, TypeError, AttributeError):
        return False
    repo = PluginRepo.objects.filter(is_official=True).first()
    if not repo or repo.signature_verified is not True:
        return False
    message = next((m for m in validated_messages(repo.cached_manifest) if m["id"] == str(message_id)), None)
    if not message:
        return False
    PluginManifestMessageDismissal.objects.get_or_create(user=user, message_id=message_id)
    _dismiss_notification_for_user(user, message_id)
    return True


def _dismiss_notification_for_user(user, message_id):
    from core.models import NotificationDismissal, SystemNotification

    notification = SystemNotification.objects.filter(
        notification_key=notification_key(message_id),
        source=SystemNotification.Source.PLUGIN_MANIFEST,
    ).first()
    if notification:
        NotificationDismissal.objects.get_or_create(user=user, notification=notification)


def reconcile_official_messages(repo):
    """Sync active warning/critical notices from one freshly fetched repo."""
    from core.models import SystemNotification
    from core.utils import send_websocket_notification, send_websocket_update

    # Manifest notices are owned by the official registry. Refreshing an
    # unrelated repository must not retire its notices.
    if not repo.is_official:
        return

    active_ids = set()
    if repo.is_official and repo.enabled and repo.signature_verified is True:
        for message in validated_messages(repo.cached_manifest):
            if not is_eligible(message) or message["severity"] not in {"warning", "critical"}:
                continue
            key = notification_key(message["id"])
            active_ids.add(key)
            notification, created = SystemNotification.objects.update_or_create(
                notification_key=key,
                defaults={
                    "notification_type": SystemNotification.NotificationType.WARNING,
                    "priority": SystemNotification.Priority.CRITICAL if message["severity"] == "critical" else SystemNotification.Priority.HIGH,
                    "source": SystemNotification.Source.PLUGIN_MANIFEST,
                    "title": message["title"] or "Plugin registry notice",
                    "message": message["body"],
                    "action_data": {"manifest_message_id": message["id"], "link": message["link"], "severity": message["severity"]},
                    "is_active": True,
                    "admin_only": False,
                    "expires_at": message["expires_at"],
                },
            )
            if created:
                send_websocket_notification(notification)

    stale = SystemNotification.objects.filter(
        source=SystemNotification.Source.PLUGIN_MANIFEST, is_active=True
    ).exclude(notification_key__in=active_ids)
    if stale.update(is_active=False):
        send_websocket_update("updates", "update", {"type": "notifications_cleared"})
