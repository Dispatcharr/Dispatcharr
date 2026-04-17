import hashlib
import ipaddress
import logging
import io
import json
import re
import socket
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, serializers
from drf_spectacular.utils import extend_schema, inline_serializer
from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.http import FileResponse
from django.utils import timezone
import os
import zipfile
import shutil
import tempfile
import requests as http_requests
from urllib.parse import urlparse
from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_method,
)
from dispatcharr.utils import network_access_allowed

from .loader import PluginManager
from .models import PluginConfig, PluginRepo
from .serializers import PluginRepoSerializer

logger = logging.getLogger(__name__)


def _compare_versions(a, b):
    """Compare two semver-like version strings.
    Returns negative if a < b, 0 if equal, positive if a > b.

    If either version is a prerelease (any dot-segment contains non-digit
    characters), numeric ordering is meaningless. Falls back to exact string
    equality: 0 if identical, 1 otherwise.
    """
    if not a or not b:
        return 0
    na = a.lstrip("v")
    nb = b.lstrip("v")
    if any(not p.isdigit() for p in na.split(".")) or any(not p.isdigit() for p in nb.split(".")):
        return 0 if na == nb else 1
    pa = [int(x) for x in na.split(".")]
    pb = [int(x) for x in nb.split(".")]
    for i in range(max(len(pa), len(pb))):
        diff = (pa[i] if i < len(pa) else 0) - (pb[i] if i < len(pb) else 0)
        if diff != 0:
            return diff
    return 0


MAX_PLUGIN_IMPORT_FILES = getattr(settings, "DISPATCHARR_PLUGIN_IMPORT_MAX_FILES", 2000)
MAX_PLUGIN_IMPORT_BYTES = getattr(settings, "DISPATCHARR_PLUGIN_IMPORT_MAX_BYTES", 200 * 1024 * 1024)
MAX_PLUGIN_IMPORT_FILE_BYTES = getattr(settings, "DISPATCHARR_PLUGIN_IMPORT_MAX_FILE_BYTES", 200 * 1024 * 1024)


def _parse_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes", "y", "on"):
            return True
        if normalized in ("false", "0", "no", "n", "off"):
            return False
    return None


def _sanitize_plugin_key(value: str) -> str:
    base = os.path.basename(value or "")
    base = base.replace(" ", "_").replace("-", "_").lower()
    base = re.sub(r"[^a-z0-9_]", "_", base)
    base = base.strip("._ ")
    return base or "plugin"


def _validate_fetch_url(url):
    """Raise ValueError if the URL must not be fetched (SSRF prevention).

    Only http and https schemes are allowed. Hostnames that resolve to
    loopback, private, link-local, or otherwise non-routable addresses
    are rejected.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"URL scheme '{parsed.scheme}' is not allowed; only http and https are permitted."
        )
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL has no hostname.")
    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve hostname '{hostname}': {exc}") from exc
    for _family, _type, _proto, _canon, sockaddr in infos:
        addr_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(addr_str)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local or ip.is_private or ip.is_reserved or ip.is_unspecified:
            raise ValueError(
                f"URL resolves to a non-routable address ({addr_str}) and cannot be fetched."
            )


def _absolutize_logo_url(request, url: str | None) -> str | None:
    if not url or not request:
        return url
    parsed = urlparse(url)
    if parsed.scheme:
        return url
    return request.build_absolute_uri(url)


class PluginAuthMixin:
    """Mixin that routes permission resolution through permission_classes_by_method,
    falling back to Authenticated() for any method not explicitly listed."""

    def get_permissions(self):
        try:
            return [
                perm() for perm in permission_classes_by_method[self.request.method]
            ]
        except KeyError:
            return [Authenticated()]


class PluginsListAPIView(PluginAuthMixin, APIView):
    def get(self, request):
        pm = PluginManager.get()
        # Prefer cached registry; reload explicitly via the reload endpoint
        pm.discover_plugins(sync_db=False, use_cache=True)
        plugins = pm.list_plugins()
        for plugin in plugins:
            plugin["logo_url"] = _absolutize_logo_url(request, plugin.get("logo_url"))
        return Response({"plugins": plugins})


class PluginReloadAPIView(PluginAuthMixin, APIView):
    def post(self, request):
        pm = PluginManager.get()
        pm.stop_all_plugins(reason="reload")
        pm.discover_plugins(force_reload=True)
        return Response({"success": True, "count": len(pm._registry)})


def _install_plugin_from_zip(zip_file, plugins_dir, *, file_name="plugin.zip", allow_overwrite_key=None, allow_overwrite=False):
    """Extract and install a plugin from a zip file-like object.

    Args:
        zip_file: File-like object containing the zip.
        plugins_dir: Path to the plugins directory.
        file_name: Name hint for deriving plugin key when the zip has flat contents.
        allow_overwrite_key: If set, allow overwriting this specific plugin directory.
        allow_overwrite: If True, allow overwriting any existing plugin with the same key.

    Returns:
        dict with "success" bool, and either "plugin_key" on success or "error" on failure.
    """
    try:
        zf = zipfile.ZipFile(zip_file)
    except zipfile.BadZipFile:
        return {"success": False, "error": "Invalid zip file"}

    tmp_root = tempfile.mkdtemp(prefix="plugin_import_")
    try:
        file_members = [m for m in zf.infolist() if not m.is_dir()]
        if not file_members:
            return {"success": False, "error": "Archive is empty"}
        if len(file_members) > MAX_PLUGIN_IMPORT_FILES:
            return {"success": False, "error": "Archive has too many files"}

        total_size = 0
        for member in file_members:
            total_size += member.file_size
            if member.file_size > MAX_PLUGIN_IMPORT_FILE_BYTES:
                return {"success": False, "error": "Archive contains a file that is too large"}
        if total_size > MAX_PLUGIN_IMPORT_BYTES:
            return {"success": False, "error": "Archive is too large"}

        for member in file_members:
            name = member.filename
            if not name or name.endswith("/"):
                continue
            norm = os.path.normpath(name)
            if norm.startswith("..") or os.path.isabs(norm):
                return {"success": False, "error": "Unsafe path in archive"}
            dest_path = os.path.join(tmp_root, norm)
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)
            with zf.open(member, "r") as src, open(dest_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

        # Single walk: find candidate plugin dirs AND logo.png simultaneously
        candidates = []
        logo_candidates_raw = []
        for dirpath, dirnames, filenames in os.walk(tmp_root):
            depth = len(os.path.relpath(dirpath, tmp_root).split(os.sep))
            has_pluginpy = "plugin.py" in filenames
            has_init = "__init__.py" in filenames
            if has_pluginpy or has_init:
                candidates.append((0 if has_pluginpy else 1, depth, dirpath))
            for filename in filenames:
                if filename.lower() == "logo.png":
                    logo_candidates_raw.append((depth, os.path.join(dirpath, filename)))
        if not candidates:
            return {"success": False, "error": "Invalid plugin: missing plugin.py or package __init__.py"}

        candidates.sort()
        chosen = candidates[0][2]

        # Determine plugin key
        base_name = os.path.splitext(file_name)[0]
        plugin_key = os.path.basename(chosen.rstrip(os.sep))
        if chosen.rstrip(os.sep) == tmp_root.rstrip(os.sep):
            plugin_key = base_name
        plugin_key = _sanitize_plugin_key(plugin_key)
        if len(plugin_key) > 128:
            plugin_key = plugin_key[:128]

        # Extract logo (prefer one inside the chosen plugin dir, then shallowest)
        logo_bytes = None
        try:
            chosen_abs = os.path.abspath(chosen)
            logo_candidates = []
            for depth, full_path in logo_candidates_raw:
                full_abs = os.path.abspath(full_path)
                try:
                    in_chosen = os.path.commonpath([chosen_abs, full_abs]) == chosen_abs
                except Exception:
                    in_chosen = False
                logo_candidates.append((0 if in_chosen else 1, depth, full_path))
            if logo_candidates:
                logo_candidates.sort()
                with open(logo_candidates[0][2], "rb") as fh:
                    logo_bytes = fh.read()
        except Exception:
            logo_bytes = None

        final_dir = os.path.join(plugins_dir, plugin_key)
        should_overwrite = (allow_overwrite_key and plugin_key == allow_overwrite_key) or allow_overwrite
        if os.path.exists(final_dir):
            if should_overwrite:
                # Atomic swap: rename old to backup, move new in, delete backup
                backup_dir = final_dir + ".__backup__"
                try:
                    if os.path.exists(backup_dir):
                        shutil.rmtree(backup_dir)
                    os.rename(final_dir, backup_dir)
                except Exception as e:
                    return {"success": False, "error": f"Failed to back up existing plugin: {e}"}
                try:
                    if chosen.rstrip(os.sep) == tmp_root.rstrip(os.sep):
                        os.makedirs(final_dir, exist_ok=True)
                        for item in os.listdir(tmp_root):
                            shutil.move(os.path.join(tmp_root, item), os.path.join(final_dir, item))
                    else:
                        shutil.move(chosen, final_dir)
                    if logo_bytes:
                        try:
                            with open(os.path.join(final_dir, "logo.png"), "wb") as fh:
                                fh.write(logo_bytes)
                        except Exception:
                            pass
                    # Success - remove backup
                    shutil.rmtree(backup_dir, ignore_errors=True)
                    return {"success": True, "plugin_key": plugin_key}
                except Exception as e:
                    # Rollback: restore backup
                    logger.exception("Failed to install updated plugin; rolling back")
                    shutil.rmtree(final_dir, ignore_errors=True)
                    try:
                        os.rename(backup_dir, final_dir)
                    except Exception:
                        logger.exception("Failed to rollback plugin backup")
                    return {"success": False, "error": f"Failed to install updated plugin: {e}"}
            elif os.path.exists(os.path.join(final_dir, "plugin.py")) or os.path.exists(os.path.join(final_dir, "__init__.py")):
                return {"success": False, "error": f"Plugin '{plugin_key}' already exists"}
            else:
                try:
                    shutil.rmtree(final_dir)
                except Exception:
                    pass

        # Move plugin files into final location
        if chosen.rstrip(os.sep) == tmp_root.rstrip(os.sep):
            os.makedirs(final_dir, exist_ok=True)
            for item in os.listdir(tmp_root):
                shutil.move(os.path.join(tmp_root, item), os.path.join(final_dir, item))
        else:
            shutil.move(chosen, final_dir)

        if logo_bytes:
            try:
                with open(os.path.join(final_dir, "logo.png"), "wb") as fh:
                    fh.write(logo_bytes)
            except Exception:
                pass

        return {"success": True, "plugin_key": plugin_key}
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def _save_fetched_manifest_to_repo(repo, data, verified):
    """Validate and persist a freshly-fetched manifest onto a PluginRepo.

    Validates that 'registry_name' is present and not official-sounding (for
    non-official repos).  On success, updates repo fields and saves to DB.

    Returns an error string if validation fails, or None on success.
    Does *not* call _unmanage_dropped_slugs — caller does that when needed.
    """
    manifest_inner = data.get("manifest", data)
    registry_name = (manifest_inner.get("registry_name") or "").strip()
    if not registry_name:
        return "Manifest is missing a 'registry_name'. The repo maintainer must set this field."
    if not repo.is_official and _is_official_sounding(registry_name):
        return f"The registry name '{registry_name}' is not allowed because it may be confused with an official repo."
    repo.cached_manifest = data
    repo.last_fetched = timezone.now()
    repo.last_fetch_status = "200"
    repo.name = registry_name
    repo.signature_verified = verified
    repo.save(update_fields=["name", "cached_manifest", "signature_verified", "last_fetched", "last_fetch_status", "updated_at"])
    return None


def _unmanage_dropped_slugs(repo, new_manifest_data):
    """After a manifest refresh, clear source_repo on any installed plugins
    whose slug is no longer listed in the repo's manifest.  Also syncs the
    'deprecated' flag for all plugins that remain managed by this repo."""
    manifest = new_manifest_data.get("manifest", new_manifest_data)
    plugin_entries = {p["slug"]: p for p in manifest.get("plugins", []) if p.get("slug")}
    current_slugs = set(plugin_entries.keys())

    dropped = PluginConfig.objects.filter(source_repo=repo).exclude(slug__in=current_slugs)
    count = dropped.update(source_repo=None, slug="", deprecated=False)
    if count:
        logger.info(
            "Unmanaged %d plugin(s) removed from repo '%s' manifest",
            count, repo.name,
        )

    # Sync deprecated flag for retained managed plugins
    for cfg in PluginConfig.objects.filter(source_repo=repo, slug__in=current_slugs):
        new_deprecated = bool(plugin_entries.get(cfg.slug, {}).get("deprecated", False))
        if cfg.deprecated != new_deprecated:
            cfg.deprecated = new_deprecated
            cfg.save(update_fields=["deprecated", "updated_at"])


class PluginImportAPIView(PluginAuthMixin, APIView):
    def post(self, request):
        file: UploadedFile = request.FILES.get("file")
        if not file:
            return Response({"success": False, "error": "Missing 'file' upload"}, status=status.HTTP_400_BAD_REQUEST)

        # Manual imports default to non-overwrite; require explicit flag to replace existing plugins
        overwrite_flag = bool(request.data.get("overwrite"))

        pm = PluginManager.get()
        result = _install_plugin_from_zip(
            file, pm.plugins_dir,
            file_name=getattr(file, "name", "plugin.zip"),
            allow_overwrite=overwrite_flag,
        )
        if not result["success"]:
            return Response(
                {"success": False, "error": result["error"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        plugin_key = result["plugin_key"]

        # Ensure DB config exists (untrusted plugins are registered without loading)
        was_managed = False
        try:
            cfg, _ = PluginConfig.objects.get_or_create(
                key=plugin_key,
                defaults={
                    "name": plugin_key,
                    "version": "",
                    "description": "",
                    "settings": {},
                },
            )
            # Manual install always breaks the managed relationship
            if cfg and cfg.source_repo_id:
                was_managed = True
                cfg.source_repo = None
                cfg.slug = ""
                cfg.save(update_fields=["source_repo", "slug", "updated_at"])
                logger.info("Plugin '%s' manually replaced - cleared managed repo link", plugin_key)
        except Exception:
            cfg = None

        # Reload discovery to register the plugin (trusted plugins will load)
        pm.discover_plugins(force_reload=True)
        plugin_entry = None
        try:
            plugin_entry = next((p for p in pm.list_plugins() if p.get("key") == plugin_key), None)
        except Exception:
            plugin_entry = None

        if not plugin_entry:
            logo_path = os.path.join(pm.plugins_dir, plugin_key, "logo.png")
            logo_url = f"/api/plugins/plugins/{plugin_key}/logo/" if os.path.isfile(logo_path) else None
            legacy = not os.path.isfile(os.path.join(pm.plugins_dir, plugin_key, "plugin.json"))
            plugin_entry = {
                "key": plugin_key,
                "name": cfg.name if cfg else plugin_key,
                "version": cfg.version if cfg else "",
                "description": cfg.description if cfg else "",
                "enabled": cfg.enabled if cfg else False,
                "ever_enabled": getattr(cfg, "ever_enabled", False) if cfg else False,
                "fields": [],
                "actions": [],
                "trusted": bool(cfg and (cfg.ever_enabled or cfg.enabled)),
                "loaded": False,
                "missing": False,
                "legacy": legacy,
                "logo_url": logo_url,
            }

        plugin_entry["logo_url"] = _absolutize_logo_url(request, plugin_entry.get("logo_url"))
        return Response({"success": True, "plugin": plugin_entry, "was_managed": was_managed})


class PluginSettingsAPIView(PluginAuthMixin, APIView):
    def post(self, request, key):
        pm = PluginManager.get()
        data = request.data or {}
        settings = data.get("settings", {})
        try:
            updated = pm.update_settings(key, settings)
            return Response({"success": True, "settings": updated})
        except Exception as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class PluginRunAPIView(PluginAuthMixin, APIView):
    def post(self, request, key):
        pm = PluginManager.get()
        action = request.data.get("action")
        params = request.data.get("params", {})
        if not action:
            return Response({"success": False, "error": "Missing 'action'"}, status=status.HTTP_400_BAD_REQUEST)

        # Respect plugin enabled flag
        try:
            cfg = PluginConfig.objects.get(key=key)
            if not cfg.enabled:
                return Response({"success": False, "error": "Plugin is disabled"}, status=status.HTTP_403_FORBIDDEN)
        except PluginConfig.DoesNotExist:
            return Response({"success": False, "error": "Plugin not found"}, status=status.HTTP_404_NOT_FOUND)

        try:
            result = pm.run_action(key, action, params)
            return Response({"success": True, "result": result})
        except PermissionError as e:
            return Response({"success": False, "error": str(e)}, status=status.HTTP_403_FORBIDDEN)
        except Exception as e:
            logger.exception("Plugin action failed")
            return Response({"success": False, "error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PluginEnabledAPIView(PluginAuthMixin, APIView):
    def post(self, request, key):
        enabled_raw = request.data.get("enabled")
        if enabled_raw is None:
            return Response({"success": False, "error": "Missing 'enabled' boolean"}, status=status.HTTP_400_BAD_REQUEST)
        enabled = _parse_bool(enabled_raw)
        if enabled is None:
            return Response({"success": False, "error": "Invalid 'enabled' boolean"}, status=status.HTTP_400_BAD_REQUEST)
        try:
            cfg = PluginConfig.objects.get(key=key)
            pm = PluginManager.get()
            if not enabled and cfg.enabled:
                try:
                    pm.stop_plugin(key, reason="disable")
                except Exception:
                    logger.exception("Failed to stop plugin '%s' on disable", key)
            cfg.enabled = enabled
            # Mark that this plugin has been enabled at least once
            if cfg.enabled and not cfg.ever_enabled:
                cfg.ever_enabled = True
            cfg.save(update_fields=["enabled", "ever_enabled", "updated_at"])
            pm.discover_plugins(force_reload=True)
            plugin_entry = None
            try:
                plugin_entry = next((p for p in pm.list_plugins() if p.get("key") == key), None)
            except Exception:
                plugin_entry = None
            response = {"success": True, "enabled": cfg.enabled, "ever_enabled": cfg.ever_enabled}
            if plugin_entry:
                plugin_entry["logo_url"] = _absolutize_logo_url(request, plugin_entry.get("logo_url"))
                response["plugin"] = plugin_entry
            return Response(response)
        except PluginConfig.DoesNotExist:
            return Response({"success": False, "error": "Plugin not found"}, status=status.HTTP_404_NOT_FOUND)


class PluginLogoAPIView(APIView):
    def get_permissions(self):
        return []

    def get(self, request, key):
        if not network_access_allowed(request, "UI"):
            return Response({"success": False, "error": "Network access denied"}, status=status.HTTP_403_FORBIDDEN)
        pm = PluginManager.get()
        pm.discover_plugins(use_cache=True)
        plugins_dir = pm.plugins_dir
        logo_path = os.path.join(plugins_dir, key, "logo.png")
        lp = pm.get_plugin(key)
        if lp and getattr(lp, "path", None):
            logo_path = os.path.join(lp.path, "logo.png")
        abs_plugins = os.path.abspath(plugins_dir) + os.sep
        abs_target = os.path.abspath(logo_path)
        if not abs_target.startswith(abs_plugins):
            return Response({"success": False, "error": "Invalid plugin path"}, status=status.HTTP_400_BAD_REQUEST)
        if not os.path.isfile(logo_path):
            return Response({"success": False, "error": "Logo not found"}, status=status.HTTP_404_NOT_FOUND)
        return FileResponse(open(logo_path, "rb"), content_type="image/png")


class PluginDeleteAPIView(PluginAuthMixin, APIView):
    def delete(self, request, key):
        pm = PluginManager.get()
        try:
            pm.stop_plugin(key, reason="delete")
        except Exception:
            logger.exception("Failed to stop plugin '%s' before delete", key)
        plugins_dir = pm.plugins_dir
        target_dir = os.path.join(plugins_dir, key)
        # Safety: ensure path inside plugins_dir
        abs_plugins = os.path.abspath(plugins_dir) + os.sep
        abs_target = os.path.abspath(target_dir)
        if not abs_target.startswith(abs_plugins):
            return Response({"success": False, "error": "Invalid plugin path"}, status=status.HTTP_400_BAD_REQUEST)

        # Remove files
        if os.path.isdir(target_dir):
            try:
                shutil.rmtree(target_dir)
            except Exception as e:
                return Response({"success": False, "error": f"Failed to delete plugin files: {e}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Remove DB record
        try:
            PluginConfig.objects.filter(key=key).delete()
        except Exception:
            pass

        # Reload registry
        pm.discover_plugins(force_reload=True)
        return Response({"success": True})


# ---------------------------------------------------------------------------
# Plugin Repo (Hub / Store) views
# ---------------------------------------------------------------------------

MANIFEST_FETCH_TIMEOUT = 15

OFFICIAL_KEY_PATH = os.path.join(
    os.path.dirname(__file__), "keys", "dispatcharr-plugins.pub"
)


def _normalize_pgp_key(text):
    """Ensure PGP public key text has armor header/footer."""
    if not text or not text.strip():
        return text
    text = text.strip()
    if "-----BEGIN PGP PUBLIC KEY BLOCK-----" not in text:
        text = "-----BEGIN PGP PUBLIC KEY BLOCK-----\n\n" + text
    if "-----END PGP PUBLIC KEY BLOCK-----" not in text:
        text = text + "\n-----END PGP PUBLIC KEY BLOCK-----"
    return text


def _verify_manifest_signature(manifest_obj, signature_armored, public_key_text=None):
    """Verify a detached GPG signature over the canonical manifest JSON.

    *signature_armored* is the PGP armored signature string from the manifest.
    *public_key_text* is an armored PGP public-key string (for third-party
    repos).  When *None* the bundled official key is used instead.

    Returns True if valid, False if invalid/error, None if verification
    could not be attempted (no signature, no key, gnupg missing, etc.).
    """
    if not signature_armored:
        return None

    # Determine which key material to use
    key_text = None
    if public_key_text:
        key_text = _normalize_pgp_key(public_key_text)
    elif os.path.isfile(OFFICIAL_KEY_PATH):
        with open(OFFICIAL_KEY_PATH, "r") as fh:
            key_text = fh.read()

    if not key_text:
        logger.debug("No GPG public key available; skipping verification")
        return None

    try:
        import gnupg
    except ImportError:
        logger.debug("python-gnupg not installed; skipping signature verification")
        return None

    tmp_home = tempfile.mkdtemp(prefix="gpg_verify_")
    try:
        gpg = gnupg.GPG(gnupghome=tmp_home)
        import_result = gpg.import_keys(key_text)
        if not import_result.fingerprints:
            logger.warning("Failed to import GPG public key")
            return None

        # Must match what the signing script produces: jq -c '.manifest'
        # which uses compact separators, preserves key order, and appends \n.
        manifest_bytes = (
            json.dumps(manifest_obj, separators=(",", ":")) + "\n"
        ).encode("utf-8")

        # Write the PGP armored signature directly to file
        sig_path = os.path.join(tmp_home, "manifest.sig")
        with open(sig_path, "w") as sf:
            sf.write(signature_armored)

        verified = gpg.verify_data(sig_path, manifest_bytes)
        return bool(verified)
    except Exception:
        logger.exception("GPG signature verification error")
        return False
    finally:
        shutil.rmtree(tmp_home, ignore_errors=True)


_OFFICIAL_NAME_PATTERNS = [
    "official",
    "official repo",
    "dispatcharr plugins",
    "dispatcharr repo",
    "dispatcharr official",
]


def _is_official_sounding(name):
    """Return True if the name could be mistaken for an official repo."""
    lower = (name or "").lower().strip()
    return any(pat in lower for pat in _OFFICIAL_NAME_PATTERNS)


def _fetch_manifest(url, public_key_text=None):
    """Fetch a remote manifest JSON, validate structure, return (data, verified)."""
    _validate_fetch_url(url)
    with http_requests.get(url, timeout=MANIFEST_FETCH_TIMEOUT, stream=True) as resp:
        resp.raise_for_status()
        body = b"".join(resp.iter_content(8192))
    data = json.loads(body)
    # Accept both top-level {manifest: {plugins: [...]}} and {plugins: [...]}
    if "manifest" in data and "plugins" in data["manifest"]:
        signature = data.get("signature")
        verified = _verify_manifest_signature(
            data["manifest"], signature, public_key_text
        )
        return data, verified
    if "plugins" in data:
        return {"manifest": data}, None
    raise ValueError("Manifest JSON missing 'manifest.plugins' list")


class PluginRepoListCreateAPIView(PluginAuthMixin, APIView):
    @extend_schema(
        description="List all plugin repositories.",
        responses={200: PluginRepoSerializer(many=True)},
    )
    def get(self, request):
        repos = PluginRepo.objects.all()
        return Response(PluginRepoSerializer(repos, many=True).data)

    @extend_schema(
        description="Add a new plugin repository by manifest URL. Fetches and validates the manifest immediately.",
        request=PluginRepoSerializer,
        responses={201: PluginRepoSerializer, 400: inline_serializer(name="RepoAddError", fields={"error": serializers.CharField()})},
    )
    def post(self, request):
        serializer = PluginRepoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        repo = serializer.save(name="")
        # Fetch manifest and validate + save
        try:
            key_text = repo.public_key if not repo.is_official else None
            data, verified = _fetch_manifest(repo.url, public_key_text=key_text)
        except Exception as e:
            logger.warning("Initial manifest fetch failed for %s: %s", repo.url, e)
            repo.delete()
            return Response(
                {"error": "Failed to fetch manifest. Check the URL and try again."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        err = _save_fetched_manifest_to_repo(repo, data, verified)
        if err:
            repo.delete()
            return Response({"error": err}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            PluginRepoSerializer(repo).data, status=status.HTTP_201_CREATED
        )


class PluginRepoPreviewAPIView(PluginAuthMixin, APIView):
    """Fetch and validate a manifest URL without saving anything."""

    @extend_schema(
        description="Preview a manifest URL: fetch and validate without saving. Returns validity, repo name, signature status, and plugin count.",
        request=inline_serializer(name="RepoPreviewRequest", fields={
            "url": serializers.URLField(),
            "public_key": serializers.CharField(required=False, allow_blank=True),
        }),
        responses={200: inline_serializer(name="RepoPreviewResponse", fields={
            "valid": serializers.BooleanField(),
            "registry_name": serializers.CharField(),
            "registry_url": serializers.CharField(),
            "signature_verified": serializers.BooleanField(allow_null=True),
            "plugin_count": serializers.IntegerField(),
            "errors": serializers.ListField(child=serializers.CharField()),
        })},
    )
    def post(self, request):
        url = (request.data.get("url") or "").strip()
        public_key = (request.data.get("public_key") or "").strip()
        if not url:
            return Response(
                {"error": "url is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            key_text = public_key or None
            data, verified = _fetch_manifest(url, public_key_text=key_text)
            manifest_inner = data.get("manifest", data)
            registry_name = (manifest_inner.get("registry_name") or "").strip()
            registry_url = (manifest_inner.get("registry_url") or "").strip()
            plugin_count = len(manifest_inner.get("plugins", []))
            errors = []
            if not registry_name:
                errors.append("Manifest is missing a 'registry_name'.")
            elif _is_official_sounding(registry_name):
                errors.append(f"The registry name '{registry_name}' is not allowed because it may be confused with an official repo.")
            if PluginRepo.objects.filter(url=url).exists():
                errors.append("This manifest URL has already been added.")
            return Response({
                "valid": len(errors) == 0,
                "registry_name": registry_name,
                "registry_url": registry_url,
                "signature_verified": verified,
                "plugin_count": plugin_count,
                "errors": errors,
            })
        except http_requests.exceptions.Timeout:
            return Response(
                {"valid": False, "errors": ["The request timed out. Check the URL and try again."]},
                status=status.HTTP_200_OK,
            )
        except http_requests.exceptions.ConnectionError:
            return Response(
                {"valid": False, "errors": ["Could not connect to the server. Check the URL and your network connection."]},
                status=status.HTTP_200_OK,
            )
        except http_requests.exceptions.HTTPError as e:
            code = e.response.status_code if e.response is not None else None
            if code == 404:
                msg = "Manifest not found (404). Check that the URL points to a valid manifest file."
            elif code == 403:
                msg = "Access denied (403). The server refused the request."
            elif code is not None:
                msg = f"The server returned an error ({code}). Check the URL and try again."
            else:
                msg = "The server returned an unexpected error. Check the URL and try again."
            return Response(
                {"valid": False, "errors": [msg]},
                status=status.HTTP_200_OK,
            )
        except (json.JSONDecodeError, ValueError) as e:
            msg = str(e)
            # Pass through messages from _validate_fetch_url and _fetch_manifest
            # as-is; only substitute the generic JSON message for actual parse errors.
            if "missing" in msg.lower() and "plugins" in msg.lower():
                friendly = msg
            elif any(kw in msg.lower() for kw in ("non-routable", "scheme", "hostname", "resolve")):
                friendly = msg
            else:
                friendly = "The URL did not return valid JSON. Make sure it points directly to a manifest .json file."
            return Response(
                {"valid": False, "errors": [friendly]},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            return Response(
                {"valid": False, "errors": ["An unexpected error occurred. Check the URL and try again."]},
                status=status.HTTP_200_OK,
            )


class PluginRepoDetailAPIView(PluginAuthMixin, APIView):
    @extend_schema(
        description="Update a plugin repository (e.g. public key).",
        request=PluginRepoSerializer,
        responses={200: PluginRepoSerializer, 404: inline_serializer(name="RepoNotFound", fields={"error": serializers.CharField()})},
    )
    def put(self, request, pk):
        try:
            repo = PluginRepo.objects.get(pk=pk)
        except PluginRepo.DoesNotExist:
            return Response(
                {"error": "Repo not found"}, status=status.HTTP_404_NOT_FOUND
            )
        # Only public_key and enabled are mutable after creation.
        # url, is_official, name, etc. must not be changed via the API.
        ALLOWED_FIELDS = {"public_key", "enabled"}
        update_data = {k: v for k, v in request.data.items() if k in ALLOWED_FIELDS}
        serializer = PluginRepoSerializer(repo, data=update_data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(PluginRepoSerializer(repo).data)

    @extend_schema(
        description="Remove a plugin repository.",
        responses={200: inline_serializer(name="RepoDeleteSuccess", fields={"success": serializers.BooleanField()}), 404: inline_serializer(name="RepoDeleteNotFound", fields={"error": serializers.CharField()})},
    )
    def delete(self, request, pk):
        try:
            repo = PluginRepo.objects.get(pk=pk)
        except PluginRepo.DoesNotExist:
            return Response(
                {"error": "Repo not found"}, status=status.HTTP_404_NOT_FOUND
            )
        if repo.is_official:
            return Response(
                {"error": "Cannot delete the official repository"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        repo.delete()
        return Response({"success": True})


class PluginRepoRefreshAPIView(PluginAuthMixin, APIView):
    @extend_schema(
        description="Re-fetch and update the cached manifest for a plugin repository.",
        request=None,
        responses={200: PluginRepoSerializer, 404: inline_serializer(name="RepoRefreshNotFound", fields={"error": serializers.CharField()}), 502: inline_serializer(name="RepoRefreshError", fields={"error": serializers.CharField()})},
    )
    def post(self, request, pk):
        try:
            repo = PluginRepo.objects.get(pk=pk)
        except PluginRepo.DoesNotExist:
            return Response(
                {"error": "Repo not found"}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            key_text = repo.public_key if not repo.is_official else None
            data, verified = _fetch_manifest(repo.url, public_key_text=key_text)
        except Exception as e:
            logger.exception("Manifest fetch failed for %s", repo.url)
            return Response(
                {"error": "Failed to fetch manifest. Check the URL and try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        err = _save_fetched_manifest_to_repo(repo, data, verified)
        if err:
            return Response({"error": err}, status=status.HTTP_400_BAD_REQUEST)
        _unmanage_dropped_slugs(repo, data)
        return Response(PluginRepoSerializer(repo).data)


class AvailablePluginsAPIView(PluginAuthMixin, APIView):
    """Aggregate plugins from all enabled repo manifests."""

    @extend_schema(
        description="Return the aggregated list of available plugins from all enabled repositories, annotated with installation status.",
        responses={200: inline_serializer(name="AvailablePluginsResponse", fields={
            "plugins": serializers.ListField(child=serializers.DictField()),
        })},
    )
    def get(self, request):
        repos = PluginRepo.objects.filter(enabled=True)
        configs = list(PluginConfig.objects.select_related("source_repo").all())
        # Build lookup: slug -> (version, repo_id, repo_name) for managed plugins,
        # plus key -> version for all plugins (legacy matching)
        installed_by_slug = {}
        installed_by_key = {}
        # Secondary dict keyed by dash-to-underscore-normalized key, for backward compat
        # with existing DB entries that were saved before normalization was enforced.
        installed_by_key_norm = {}
        for cfg in configs:
            installed_by_key[cfg.key] = cfg.version
            installed_by_key_norm[cfg.key.replace("-", "_")] = cfg.key
            if cfg.slug:
                installed_by_slug[cfg.slug] = {
                    "version": cfg.version,
                    "source_repo_id": cfg.source_repo_id,
                    "source_repo_name": cfg.source_repo.name if cfg.source_repo else None,
                    "is_prerelease": cfg.installed_version_is_prerelease,
                }
                # Also index by normalized slug so a dash-variant in the manifest still matches
                norm_slug = cfg.slug.replace("-", "_")
                if norm_slug not in installed_by_slug:
                    installed_by_slug[norm_slug] = installed_by_slug[cfg.slug]

        plugins = []
        for repo in repos:
            manifest_data = repo.cached_manifest or {}
            manifest = manifest_data.get("manifest", manifest_data)
            root_url = manifest.get("root_url", "").rstrip("/")
            registry_url = manifest.get("registry_url", "").rstrip("/")
            repo_plugins = manifest.get("plugins", [])
            for p in repo_plugins:
                slug = p.get("slug", "")
                plugin_data = {**p}
                # Resolve relative URLs against root_url; absolute URLs pass through
                if root_url:
                    for url_field in ("manifest_url", "latest_url", "icon_url"):
                        val = plugin_data.get(url_field, "")
                        if val and not val.startswith(("http://", "https://")):
                            plugin_data[url_field] = f"{root_url}/{val}"
                # Fallback icon_url from main branch when not provided
                if not plugin_data.get("icon_url") and registry_url:
                    # registry_url is e.g. https://github.com/Dispatcharr/Plugins
                    # Convert to raw.githubusercontent.com URL for the main branch
                    raw_base = registry_url.replace(
                        "https://github.com/", "https://raw.githubusercontent.com/"
                    )
                    plugin_data["icon_url"] = f"{raw_base}/refs/heads/main/plugins/{slug}/logo.png"
                # Determine install status
                managed = installed_by_slug.get(slug) or installed_by_slug.get(slug.replace("-", "_"))
                sanitized_slug = _sanitize_plugin_key(slug)
                key_match = sanitized_slug in installed_by_key or sanitized_slug in installed_by_key_norm
                if managed:
                    is_installed = True
                    installed_version = managed["version"]
                    latest = plugin_data.get("latest_version")
                    if managed["source_repo_id"] == repo.id:
                        if installed_version and latest and installed_version != latest and not managed.get("is_prerelease"):
                            install_status = "update_available"
                        else:
                            install_status = "installed"
                    else:
                        install_status = "different_repo"
                elif key_match:
                    is_installed = True
                    installed_version = installed_by_key.get(sanitized_slug) or installed_by_key.get(
                        installed_by_key_norm.get(sanitized_slug, sanitized_slug)
                    )
                    install_status = "unmanaged"
                else:
                    is_installed = False
                    installed_version = None
                    install_status = "not_installed"
                entry = {
                    **plugin_data,
                    "repo_id": repo.id,
                    "repo_name": repo.name,
                    "is_official_repo": repo.is_official,
                    "signature_verified": repo.signature_verified,
                    "installed": is_installed,
                    "installed_version": installed_version,
                    "installed_version_is_prerelease": managed.get("is_prerelease", False) if managed else False,
                    "install_status": install_status,
                    "key": _sanitize_plugin_key(slug),
                }
                if install_status == "different_repo":
                    entry["installed_source_repo_name"] = managed["source_repo_name"]
                plugins.append(entry)
        return Response({"plugins": plugins})


class PluginDetailManifestAPIView(PluginAuthMixin, APIView):
    """Fetch and verify a per-plugin manifest given repo_id and manifest_url."""

    @extend_schema(
        description="Fetch and GPG-verify a per-plugin manifest from a repo, resolving relative URLs against the repo root.",
        request=inline_serializer(name="PluginDetailManifestRequest", fields={
            "repo_id": serializers.IntegerField(),
            "manifest_url": serializers.URLField(),
        }),
        responses={200: inline_serializer(name="PluginDetailManifestResponse", fields={
            "manifest": serializers.DictField(),
            "signature_verified": serializers.BooleanField(allow_null=True),
        }), 502: inline_serializer(name="PluginDetailManifestError", fields={"error": serializers.CharField()})},
    )
    def post(self, request):
        repo_id = request.data.get("repo_id")
        manifest_url = request.data.get("manifest_url")
        if not repo_id or not manifest_url:
            return Response(
                {"error": "repo_id and manifest_url are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            repo = PluginRepo.objects.get(pk=repo_id)
        except PluginRepo.DoesNotExist:
            return Response(
                {"error": "Repo not found"}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            _validate_fetch_url(manifest_url)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            resp = http_requests.get(manifest_url, timeout=MANIFEST_FETCH_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()

            signature = data.get("signature")
            manifest_obj = data.get("manifest", data)
            verified = _verify_manifest_signature(
                manifest_obj, signature,
                repo.public_key if not repo.is_official else None
            )

            # Resolve relative URLs in versions
            repo_manifest = repo.cached_manifest or {}
            inner = repo_manifest.get("manifest", repo_manifest)
            root_url = inner.get("root_url", "").rstrip("/")

            if root_url and isinstance(manifest_obj.get("versions"), list):
                for v in manifest_obj["versions"]:
                    url_val = v.get("url", "")
                    if url_val and not url_val.startswith(("http://", "https://")):
                        v["url"] = f"{root_url}/{url_val}"
            if root_url and isinstance(manifest_obj.get("latest"), dict):
                for url_field in ("url", "latest_url"):
                    url_val = manifest_obj["latest"].get(url_field, "")
                    if url_val and not url_val.startswith(("http://", "https://")):
                        manifest_obj["latest"][url_field] = f"{root_url}/{url_val}"

            return Response({
                "manifest": manifest_obj,
                "signature_verified": verified,
            })
        except Exception as e:
            logger.exception("Failed to fetch plugin manifest from %s", manifest_url)
            return Response(
                {"error": f"Failed to fetch plugin manifest: {e}"},
                status=status.HTTP_502_BAD_GATEWAY,
            )


class PluginInstallFromRepoAPIView(PluginAuthMixin, APIView):
    """Install a plugin from a managed repo by downloading its release zip."""

    @extend_schema(
        description="Download and install a plugin release zip from a managed repository. Verifies SHA256 if provided.",
        request=inline_serializer(name="PluginInstallFromRepoRequest", fields={
            "repo_id": serializers.IntegerField(),
            "slug": serializers.CharField(),
            "version": serializers.CharField(),
            "download_url": serializers.URLField(),
            "sha256": serializers.CharField(required=False, allow_blank=True),
            "min_dispatcharr_version": serializers.CharField(required=False, allow_blank=True),
            "max_dispatcharr_version": serializers.CharField(required=False, allow_blank=True),
        }),
        responses={
            200: inline_serializer(name="PluginInstallFromRepoResponse", fields={"success": serializers.BooleanField(), "plugin": serializers.DictField()}),
            201: inline_serializer(name="PluginInstallFromRepoCreated", fields={"success": serializers.BooleanField(), "plugin": serializers.DictField()}),
            400: inline_serializer(name="PluginInstallFromRepoError", fields={"error": serializers.CharField()}),
        },
    )
    def post(self, request):
        repo_id = request.data.get("repo_id")
        slug = request.data.get("slug")
        version = request.data.get("version")
        download_url = request.data.get("download_url")

        if not all([repo_id, slug, version, download_url]):
            return Response(
                {"error": "repo_id, slug, version, and download_url are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            repo = PluginRepo.objects.get(pk=repo_id)
        except PluginRepo.DoesNotExist:
            return Response(
                {"error": "Repo not found"}, status=status.HTTP_404_NOT_FOUND
            )

        # Resolve the plugin key and look up any existing install
        plugin_key = _sanitize_plugin_key(slug)
        if len(plugin_key) > 128:
            plugin_key = plugin_key[:128]

        existing_cfg = PluginConfig.objects.filter(key=plugin_key).first()
        # Backward compat: if no match, also try with dashes (legacy entries saved before
        # normalization was enforced) so overwrite is still allowed on update.
        if not existing_cfg:
            dash_key = plugin_key.replace("_", "-")
            if dash_key != plugin_key:
                existing_cfg = PluginConfig.objects.filter(key=dash_key).first()

        # Version compatibility check against the running Dispatcharr version
        min_version = request.data.get("min_dispatcharr_version")
        max_version = request.data.get("max_dispatcharr_version")
        if min_version or max_version:
            from version import __version__ as app_version
            try:
                if min_version and _compare_versions(app_version, min_version) < 0:
                    return Response(
                        {"error": f"This plugin version requires Dispatcharr {min_version} or newer (you have {app_version})"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if max_version and _compare_versions(app_version, max_version) > 0:
                    return Response(
                        {"error": f"This plugin version requires Dispatcharr {max_version} or older (you have {app_version})"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            except (ValueError, TypeError):
                logger.warning("Failed to parse version constraints: min=%s, max=%s", min_version, max_version)

        # Download the zip
        try:
            _validate_fetch_url(download_url)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        try:
            resp = http_requests.get(download_url, timeout=60, stream=True)
            resp.raise_for_status()
        except Exception as e:
            logger.exception("Failed to download plugin from %s", download_url)
            return Response(
                {"error": "Failed to download plugin. Check the URL and try again."},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        # SHA256 integrity check (streamed)
        expected_sha256 = request.data.get("sha256", "").lower().strip()
        hasher = hashlib.sha256() if expected_sha256 else None

        # Stream the response to a temporary file to avoid buffering in memory
        with tempfile.NamedTemporaryFile(suffix=".zip") as tmp_file:
            total = 0
            for chunk in resp.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_PLUGIN_IMPORT_BYTES:
                    return Response(
                        {"error": "Download is too large"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if hasher is not None:
                    hasher.update(chunk)
                tmp_file.write(chunk)

            if expected_sha256:
                actual_sha256 = hasher.hexdigest()
                if actual_sha256 != expected_sha256:
                    logger.warning(
                        "SHA256 mismatch for plugin '%s' from %s: expected %s, got %s",
                        slug, download_url, expected_sha256, actual_sha256,
                    )
                    return Response(
                        {
                            "error": "SHA256 integrity check failed - download discarded. The file may be corrupted or tampered with."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            # Delegate to shared install logic (allow overwrite for managed updates)
            tmp_file.flush()
            tmp_file.seek(0)
            pm = PluginManager.get()
            result = _install_plugin_from_zip(
                tmp_file,
                pm.plugins_dir,
                file_name=f"{slug}.zip",
                allow_overwrite_key=plugin_key if existing_cfg else None,
            )
        if not result["success"]:
            return Response(
                {"success": False, "error": result["error"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        actual_key = result["plugin_key"]

        # Create/update PluginConfig with managed fields
        # Use defaults for creation only; explicitly update fields on existing records
        # to preserve settings, enabled, and ever_enabled
        is_prerelease = bool(request.data.get("prerelease", False))

        # Determine deprecated status from the repo's cached manifest
        is_deprecated = False
        manifest_data = repo.cached_manifest or {}
        manifest_inner = manifest_data.get("manifest", manifest_data)
        for rp in manifest_inner.get("plugins", []):
            if rp.get("slug") == slug:
                is_deprecated = bool(rp.get("deprecated", False))
                break

        cfg, created = PluginConfig.objects.get_or_create(
            key=actual_key,
            defaults={
                "name": slug,
                "version": version,
                "slug": slug,
                "source_repo": repo,
                "installed_version_is_prerelease": is_prerelease,
                "deprecated": is_deprecated,
            },
        )
        if not created:
            cfg.version = version
            cfg.slug = slug
            cfg.source_repo = repo
            cfg.installed_version_is_prerelease = is_prerelease
            cfg.deprecated = is_deprecated
            cfg.save(update_fields=["version", "slug", "source_repo", "installed_version_is_prerelease", "deprecated", "updated_at"])

        # Reload discovery
        pm.discover_plugins(force_reload=True)
        plugin_entry = None
        try:
            plugin_entry = next(
                (p for p in pm.list_plugins() if p.get("key") == actual_key),
                None,
            )
        except Exception:
            plugin_entry = None

        return Response(
            {
                "success": True,
                "plugin": plugin_entry or {"key": actual_key, "slug": slug, "version": version},
            },
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class PluginRepoSettingsAPIView(PluginAuthMixin, APIView):
    """Get/update plugin repo refresh settings (interval in hours, 0=disabled)."""

    @extend_schema(
        description="Get the plugin repository refresh interval setting.",
        responses={200: inline_serializer(name="PluginRepoSettingsResponse", fields={"refresh_interval_hours": serializers.IntegerField()})},
    )
    def get(self, request):
        from core.models import CoreSettings
        try:
            obj = CoreSettings.objects.get(key="plugin_repo_settings")
            return Response(obj.value)
        except CoreSettings.DoesNotExist:
            return Response({"refresh_interval_hours": 6})

    @extend_schema(
        description="Update the plugin repository refresh interval (hours). Set to 0 to disable automatic refresh.",
        request=inline_serializer(name="PluginRepoSettingsRequest", fields={"refresh_interval_hours": serializers.IntegerField()}),
        responses={200: inline_serializer(name="PluginRepoSettingsUpdated", fields={"refresh_interval_hours": serializers.IntegerField()})},
    )
    def put(self, request):
        from core.models import CoreSettings
        from core.scheduling import create_or_update_periodic_task, delete_periodic_task
        from .tasks import PLUGIN_REPO_REFRESH_TASK_NAME

        interval = request.data.get("refresh_interval_hours", 6)
        try:
            interval = int(interval)
            if interval < 0:
                interval = 0
        except (TypeError, ValueError):
            interval = 6

        obj, _ = CoreSettings.objects.update_or_create(
            key="plugin_repo_settings",
            defaults={
                "name": "Plugin Repo Settings",
                "value": {"refresh_interval_hours": interval},
            },
        )

        if interval == 0:
            delete_periodic_task(PLUGIN_REPO_REFRESH_TASK_NAME)
        else:
            create_or_update_periodic_task(
                task_name=PLUGIN_REPO_REFRESH_TASK_NAME,
                celery_task_path="apps.plugins.tasks.refresh_plugin_repos",
                interval_hours=interval,
                enabled=True,
            )

        return Response(obj.value)
