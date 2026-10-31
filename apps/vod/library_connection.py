"""Credential checks without exposing credentials or caching a stale verdict."""

import os

from django.db import transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac

from core.models import CoreSettings

from .tmdb import Client, TMDBAuthenticationError, TMDBError


def fingerprint(token):
    return salted_hmac("vod-library-tmdb-connection", token).hexdigest()


def connection_status(token, check=None):
    if not token:
        return {"status": "not_configured", "checked_at": None, "detail": ""}
    if not check or check.get("credential") != fingerprint(token):
        return {"status": "unchecked", "checked_at": None, "detail": ""}
    return {key: check.get(key) for key in ("status", "checked_at", "detail")}


def check_connection(token):
    result = {"checked_at": timezone.now().isoformat()}
    try:
        Client(token).validate()
    except (TMDBAuthenticationError, ValueError):
        result.update(status="error", detail="TMDB rejected the credential.")
    except TMDBError:
        result.update(
            status="error", detail="TMDB could not be reached. Try again later."
        )
    else:
        result.update(status="connected", detail="TMDB connection verified.")
    return result


@transaction.atomic
def remember_connection(token, result):
    from .library import SETTINGS_KEY, library_settings

    if library_settings(private=True)["api_token"] != token:
        return
    CoreSettings.objects.get_or_create(
        key=SETTINGS_KEY, defaults={"name": "VOD library", "value": {}}
    )
    row = CoreSettings.objects.select_for_update().get(key=SETTINGS_KEY)
    # A draft test must not change the saved credential's status. Recheck under
    # the settings-row lock so a concurrent rotation cannot retain an old verdict.
    current = (
        os.environ.get("TMDB_API_READ_ACCESS_TOKEN")
        or os.environ.get("TMDB_API_KEY")
        or (row.value or {}).get("api_token")
        or ""
    )
    if current != token:
        return
    row.value = {
        **(row.value or {}),
        "_credential_check": {"credential": fingerprint(token), **result},
    }
    row.save(update_fields=["value"])
