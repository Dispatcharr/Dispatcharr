import json
from urllib.parse import unquote

from django.db.models import OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.http import JsonResponse, FileResponse, Http404
from django.conf import settings
import os
from django.urls import reverse
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin, IsStandardUser
from apps.vod.models import (
    VODCategory,
    Movie,
    Series,
    Episode,
    M3UMovieRelation,
    M3USeriesRelation,
    M3UEpisodeRelation,
)
from core.models import CoreSettings, FUSE_SETTINGS_KEY
from .serializers import (
    FuseEntrySerializer,
    FuseSettingsSerializer,
    FUSE_SETTINGS_DEFAULTS,
)
from .utils import is_fuse_client_request
from .client_presence import (
    touch_fuse_client_presence,
    list_fuse_clients,
    force_remove_fuse_client,
)
from .host_auth import (
    require_valid_fuse_host_token,
    has_registered_fuse_host_tokens,
    create_fuse_pairing_token,
    register_fuse_host_with_pairing_token,
)


def _track_fuse_presence_or_forbidden(request, endpoint: str):
    tracking = touch_fuse_client_presence(request=request, endpoint=endpoint)
    if tracking.get("blocked"):
        return Response(
            {
                "detail": (
                    "This FUSE client has been disconnected by an administrator. "
                    "Restart the mount service or wait for the block window to expire."
                )
            },
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


def _require_fuse_token_or_authenticated(
    request,
    *,
    strict: bool,
):
    user = getattr(request, "user", None)
    if user and getattr(user, "is_authenticated", False):
        return None

    if not strict:
        user_agent = str(request.META.get("HTTP_USER_AGENT", "")).strip()
        if not is_fuse_client_request(
            client_user_agent=user_agent,
            request_meta=request.META,
        ):
            return None

    # Backward compatibility: only enforce token auth after at least one host
    # has been paired. Fresh installs can still bootstrap pairing.
    if not has_registered_fuse_host_tokens():
        return None

    ok, detail, _metadata = require_valid_fuse_host_token(request)
    if not ok:
        return Response(
            {"detail": detail},
            status=status.HTTP_401_UNAUTHORIZED,
        )
    return None


def _get_request_ip(request) -> str:
    forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded_for:
        parts = [part.strip() for part in str(forwarded_for).split(",") if part.strip()]
        if parts:
            return parts[0]
    return str(request.META.get("REMOTE_ADDR", "")).strip() or "unknown"


def _select_best_relation(relations):
    """
    Pick the highest priority active relation.
    """
    if relations is None:
        return None
    try:
        iterable = list(relations.all()) if hasattr(relations, "all") else list(relations)
    except TypeError:
        iterable = []
    if not iterable:
        return None
    return sorted(
        iterable,
        key=lambda rel: (-getattr(rel.m3u_account, "priority", 0), rel.id),
    )[0]


def _build_logo_cache_url(request, logo_id):
    """Build absolute URL for cached VOD logo content."""
    if not logo_id:
        return None
    return request.build_absolute_uri(reverse("api:vod:vodlogo-cache", args=[logo_id]))


def _truncate_utf8(text, max_bytes=255):
    if text is None:
        return ""
    raw = str(text).encode("utf-8", errors="ignore")
    if len(raw) <= max_bytes:
        return str(text)
    raw = raw[:max_bytes]
    while raw:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            raw = raw[:-1]
    return ""


def _sanitize_raw_name(name):
    cleaned = []
    for ch in str(name or ""):
        code = ord(ch)
        if ch in ("/", "\x00") or code < 32:
            cleaned.append("_")
        else:
            cleaned.append(ch)
    return "".join(cleaned).strip()


def _normalize_fuse_name(name, fallback):
    value = _sanitize_raw_name(name)
    if value in ("", ".", ".."):
        value = fallback
    value = _truncate_utf8(value, 255)
    if value in ("", ".", ".."):
        value = _truncate_utf8(fallback, 255) or "item"
    return value


def _name_with_suffix(name, suffix, is_dir):
    if not is_dir:
        dot_index = name.rfind(".")
        if dot_index > 0:
            base = name[:dot_index]
            ext = name[dot_index:]
        else:
            base = name
            ext = ""
    else:
        base = name
        ext = ""

    suffix_bytes = len((suffix + ext).encode("utf-8", errors="ignore"))
    max_base_bytes = max(1, 255 - suffix_bytes)
    base = _truncate_utf8(base, max_base_bytes)
    candidate = _truncate_utf8(f"{base}{suffix}{ext}", 255)
    if candidate in ("", ".", ".."):
        candidate = _truncate_utf8(f"item{suffix}{ext}", 255) or "item"
    return candidate


def _ensure_unique_fuse_name(name, used_names, is_dir):
    candidate = name
    counter = 2
    while candidate in used_names:
        candidate = _name_with_suffix(name, f" ({counter})", is_dir=is_dir)
        counter += 1
    used_names.add(candidate)
    return candidate


def _sanitize_entries_for_directory(directory_path, entries):
    """
    Sanitize names for filesystem safety and keep entry.path consistent with
    the emitted name so subsequent getattr/lookups resolve correctly.
    """
    prefix = "/" if not directory_path or directory_path == "/" else f"/{directory_path.strip('/')}"
    used_names = set()
    sanitized = []

    for idx, entry in enumerate(entries, start=1):
        item = dict(entry)
        is_dir = bool(item.get("is_dir"))
        fallback = f"{'dir' if is_dir else 'file'}-{idx}"
        normalized = _normalize_fuse_name(item.get("name"), fallback=fallback)
        unique_name = _ensure_unique_fuse_name(normalized, used_names, is_dir=is_dir)

        item["name"] = unique_name
        item["path"] = f"/{unique_name}" if prefix == "/" else f"{prefix}/{unique_name}"
        sanitized.append(item)

    return sanitized


def _build_segment_map(items, name_getter, fallback_prefix):
    """
    Deterministically map sanitized path segments to DB objects.
    Used for root directory listings and reverse lookup of incoming segments.
    """
    used_names = set()
    mapping = {}

    for item in items:
        fallback = f"{fallback_prefix}-{getattr(item, 'id', 'x')}"
        normalized = _normalize_fuse_name(name_getter(item), fallback=fallback)
        unique_name = _ensure_unique_fuse_name(normalized, used_names, is_dir=True)
        mapping[unique_name] = item

    return mapping


class FuseBrowseView(APIView):
    """
    Read-only filesystem-style browsing for Movies and TV.
    """

    permission_classes = [AllowAny]

    def get(self, request, mode):
        unauthorized = _require_fuse_token_or_authenticated(request, strict=True)
        if unauthorized is not None:
            return unauthorized

        denied_response = _track_fuse_presence_or_forbidden(
            request=request,
            endpoint=f"browse:{mode}",
        )
        if denied_response is not None:
            return denied_response

        path = request.query_params.get("path", "/")
        path = unquote(path)
        # Normalize
        trimmed = path.strip("/")
        parts = [p for p in trimmed.split("/") if p] if trimmed else []

        if mode not in ("movies", "tv"):
            return Response({"detail": "Invalid mode"}, status=status.HTTP_400_BAD_REQUEST)

        if mode == "movies":
            return Response(self._browse_movies(parts, request))
        return Response(self._browse_tv(parts, request))

    def _browse_movies(self, parts, request):
        # Root -> list categories
        if len(parts) == 0:
            category_ids = (
                M3UMovieRelation.objects.filter(
                    m3u_account__is_active=True, category__isnull=False
                )
                .values_list("category_id", flat=True)
                .distinct()
            )
            categories = VODCategory.objects.filter(
                category_type="movie", id__in=category_ids
            ).order_by("name", "id")

            segment_map = _build_segment_map(
                categories,
                name_getter=lambda cat: cat.name,
                fallback_prefix="category",
            )
            entries = [
                {
                    "name": segment,
                    "path": f"/{segment}",
                    "is_dir": True,
                    "content_type": "category",
                    "uuid": None,
                }
                for segment in segment_map.keys()
            ]
            return {"path": "/", "entries": FuseEntrySerializer(entries, many=True).data}

        # Category -> list movies
        category_segment = parts[0]
        category = (
            VODCategory.objects.filter(
                name=category_segment, category_type="movie"
            ).first()
        )
        if not category:
            category_ids = (
                M3UMovieRelation.objects.filter(
                    m3u_account__is_active=True, category__isnull=False
                )
                .values_list("category_id", flat=True)
                .distinct()
            )
            categories = VODCategory.objects.filter(
                category_type="movie", id__in=category_ids
            ).order_by("name", "id")
            segment_map = _build_segment_map(
                categories,
                name_getter=lambda cat: cat.name,
                fallback_prefix="category",
            )
            category = segment_map.get(category_segment)
        if not category:
            return {"path": f"/{category_segment}", "entries": []}

        movies = (
            Movie.objects.filter(
                m3u_relations__category=category,
                m3u_relations__m3u_account__is_active=True,
            )
            .distinct()
            .annotate(
                best_extension=Coalesce(
                    Subquery(
                        M3UMovieRelation.objects.filter(
                            m3u_account__is_active=True,
                            category=category,
                            movie_id=OuterRef("pk"),
                        )
                        .order_by("-m3u_account__priority", "id")
                        .values("container_extension")[:1]
                    ),
                    Value("mp4"),
                )
            )
            .only("id", "uuid", "name", "year", "logo_id")
            .order_by("name")
        )

        entries = []
        for movie in movies:
            extension = getattr(movie, "best_extension", None) or "mp4"
            name = f"{movie.name} ({movie.year})" if movie.year else movie.name
            file_name = f"{name}.{extension}"
            poster_file_name = f"{name}.jpg"

            entries.append(
                {
                    "name": file_name,
                    "path": f"/{category_segment}/{file_name}",
                    "is_dir": False,
                    "content_type": "movie",
                    "uuid": movie.uuid,
                    "extension": extension,
                    "category": category.name,
                    # Report zero so clients don't prefetch/consume provider slots until a real read.
                    "size": 0,
                    # Omit stream_url to force clients to fetch it only when they actually read.
                    "stream_url": None,
                }
            )

            # Add sidecar poster art so Plex-like scanners can consume lightweight metadata assets
            # without touching upstream provider streams.
            if movie.logo_id:
                entries.append(
                    {
                        "name": poster_file_name,
                        "path": f"/{category_segment}/{poster_file_name}",
                        "is_dir": False,
                        "content_type": "image",
                        "uuid": None,
                        "extension": "jpg",
                        "category": category.name,
                        "size": 0,
                        "stream_url": _build_logo_cache_url(request, movie.logo_id),
                    }
                )

        entries = _sanitize_entries_for_directory(f"/{category_segment}", entries)
        return {
            "path": f"/{category_segment}",
            "entries": FuseEntrySerializer(entries, many=True).data,
        }

    def _browse_tv(self, parts, request):
        # Root -> list series
        if len(parts) == 0:
            series = (
                Series.objects.filter(
                    m3u_relations__m3u_account__is_active=True,
                )
                .distinct()
                .order_by("name", "id")
            )
            segment_map = _build_segment_map(
                series,
                name_getter=lambda serie: serie.name,
                fallback_prefix="series",
            )
            entries = [
                {
                    "name": segment,
                    "path": f"/{segment}",
                    "is_dir": True,
                    "content_type": "series",
                    "uuid": None,
                }
                for segment in segment_map.keys()
            ]
            return {"path": "/", "entries": FuseEntrySerializer(entries, many=True).data}

        # Series -> list seasons
        series_segment = parts[0]
        series_obj = Series.objects.filter(name=series_segment).first()
        if not series_obj:
            series = (
                Series.objects.filter(
                    m3u_relations__m3u_account__is_active=True,
                )
                .distinct()
                .order_by("name", "id")
            )
            segment_map = _build_segment_map(
                series,
                name_getter=lambda serie: serie.name,
                fallback_prefix="series",
            )
            series_obj = segment_map.get(series_segment)
        if not series_obj:
            return {"path": f"/{series_segment}", "entries": []}

        if len(parts) == 1:
            seasons = (
                Episode.objects.filter(series=series_obj)
                .exclude(season_number__isnull=True)
                .values_list("season_number", flat=True)
                .distinct()
            )
            season_numbers = sorted(set(seasons)) or [0]
            entries = []
            for num in season_numbers:
                label = f"Season {int(num):02d}"
                entries.append(
                    {
                        "name": label,
                        "path": f"/{series_segment}/{label}",
                        "is_dir": True,
                        "content_type": "season",
                        "uuid": None,
                        "season": int(num),
                    }
                )

            # Plex local-assets convention for show-level artwork.
            if series_obj.logo_id:
                entries.append(
                    {
                        "name": "poster.jpg",
                        "path": f"/{series_segment}/poster.jpg",
                        "is_dir": False,
                        "content_type": "image",
                        "uuid": None,
                        "extension": "jpg",
                        "size": 0,
                        "stream_url": _build_logo_cache_url(request, series_obj.logo_id),
                    }
                )

            entries = _sanitize_entries_for_directory(f"/{series_segment}", entries)
            return {
                "path": f"/{series_segment}",
                "entries": FuseEntrySerializer(entries, many=True).data,
            }

        # Season -> list episodes
        season_label = parts[1]
        try:
            season_number = int(season_label.replace("Season", "").strip())
        except Exception:
            season_number = None

        episodes = (
            Episode.objects.filter(
                series=series_obj,
                season_number=season_number,
            )
            .filter(m3u_relations__m3u_account__is_active=True)
            .distinct()
            .annotate(
                best_extension=Coalesce(
                    Subquery(
                        M3UEpisodeRelation.objects.filter(
                            m3u_account__is_active=True,
                            episode_id=OuterRef("pk"),
                        )
                        .order_by("-m3u_account__priority", "id")
                        .values("container_extension")[:1]
                    ),
                    Value("mp4"),
                )
            )
            .only("id", "uuid", "name", "series_id", "season_number", "episode_number")
            .order_by("episode_number")
        )

        entries = []
        for ep in episodes:
            extension = getattr(ep, "best_extension", None) or "mp4"
            ep_num = ep.episode_number or 0
            season_num = ep.season_number or 0
            name = f"S{season_num:02d}E{ep_num:02d} - {ep.name}"
            file_name = f"{name}.{extension}"
            stream_url = None
            if ep.uuid:
                stream_url = request.build_absolute_uri(
                    reverse(
                        "proxy:vod_proxy:vod_stream",
                        kwargs={"content_type": "episode", "content_id": ep.uuid},
                    )
                )
            entries.append(
                {
                    "name": file_name,
                    "path": f"/{series_segment}/{season_label}/{file_name}",
                    "is_dir": False,
                    "content_type": "episode",
                    "uuid": ep.uuid,
                    "extension": extension,
                    "season": season_num,
                    "episode_number": ep_num,
                    "size": 0,
                    "stream_url": None,
                }
            )

        entries = _sanitize_entries_for_directory(f"/{series_segment}/{season_label}", entries)
        return {
            "path": f"/{series_segment}/{season_label}",
            "entries": FuseEntrySerializer(entries, many=True).data,
        }


class FuseSettingsViewSet(viewsets.ViewSet):
    """
    Store FUSE client guidance in CoreSettings as JSON.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = FuseSettingsSerializer

    DEFAULTS = FUSE_SETTINGS_DEFAULTS.copy()

    def get_permissions(self):
        # Host-side scripts need anonymous read access to tuning values.
        if self.action in ("list", "retrieve"):
            return [AllowAny()]
        return [IsAuthenticated()]

    def _normalize_settings_value(self, raw_value):
        if isinstance(raw_value, dict):
            return raw_value
        if isinstance(raw_value, str):
            try:
                parsed = json.loads(raw_value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                return {}
        return {}

    def _get_or_create(self):
        try:
            obj = CoreSettings.objects.get(key=FUSE_SETTINGS_KEY)
            data = self._normalize_settings_value(obj.value)
        except CoreSettings.DoesNotExist:
            data = self.DEFAULTS.copy()
            obj, _ = CoreSettings.objects.get_or_create(
                key=FUSE_SETTINGS_KEY,
                defaults={"name": "Fuse Settings", "value": data},
            )
        merged = self.DEFAULTS.copy()
        merged.update(data or {})
        return obj, merged

    def list(self, request):
        obj, data = self._get_or_create()
        serializer = FuseSettingsSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        return self.list(request)

    def update(self, request, pk=None):
        obj, current = self._get_or_create()
        serializer = FuseSettingsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        obj.value = serializer.validated_data
        obj.save()
        return Response(serializer.validated_data)


class FusePublicSettingsView(APIView):
    """
    Public read-only endpoint for host-side FUSE scripts to fetch tuning defaults.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        unauthorized = _require_fuse_token_or_authenticated(request, strict=False)
        if unauthorized is not None:
            return unauthorized

        denied_response = _track_fuse_presence_or_forbidden(
            request=request,
            endpoint="settings:public",
        )
        if denied_response is not None:
            return denied_response

        try:
            obj = CoreSettings.objects.get(key=FUSE_SETTINGS_KEY)
            raw_value = obj.value
        except CoreSettings.DoesNotExist:
            raw_value = {}

        if isinstance(raw_value, str):
            try:
                raw_value = json.loads(raw_value)
            except json.JSONDecodeError:
                raw_value = {}
        if not isinstance(raw_value, dict):
            raw_value = {}

        merged = FUSE_SETTINGS_DEFAULTS.copy()
        merged.update(raw_value)
        serializer = FuseSettingsSerializer(data=merged)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.validated_data)


class FuseStreamURLView(APIView):
    """
    Provide a stable stream URL for a given movie/episode UUID.
    """

    permission_classes = [AllowAny]

    def get(self, request, content_type, content_id):
        unauthorized = _require_fuse_token_or_authenticated(request, strict=True)
        if unauthorized is not None:
            return unauthorized

        denied_response = _track_fuse_presence_or_forbidden(
            request=request,
            endpoint=f"stream-url:{content_type}",
        )
        if denied_response is not None:
            return denied_response

        if content_type not in ("movie", "episode"):
            return Response({"detail": "Invalid content type"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            model = Movie if content_type == "movie" else Episode
            if not model.objects.filter(uuid=content_id).exists():
                return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
            stream_url = request.build_absolute_uri(
                reverse(
                    "proxy:vod_proxy:vod_stream",
                    kwargs={"content_type": content_type, "content_id": content_id},
                )
            )
            return JsonResponse({"stream_url": stream_url})
        except Exception:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)


class FuseConnectedClientsView(APIView):
    """
    List and force-remove host machines connected via the Dispatcharr FUSE client.
    """

    def get_permissions(self):
        if self.request.method.upper() == "POST":
            return [IsAdmin()]
        return [IsStandardUser()]

    def get(self, request):
        include_inactive = str(request.query_params.get("include_inactive", "")).strip().lower()
        payload = list_fuse_clients(
            include_inactive=include_inactive in {"1", "true", "yes", "on"}
        )
        return Response(payload)

    def post(self, request):
        client_id = str(request.data.get("client_id", "")).strip()
        if not client_id:
            return Response(
                {"detail": "client_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        block_seconds = request.data.get("block_seconds")
        try:
            block_seconds = int(block_seconds) if block_seconds is not None else None
        except (TypeError, ValueError):
            return Response(
                {"detail": "block_seconds must be an integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        removed_by = getattr(request.user, "username", "") if getattr(request, "user", None) else ""
        try:
            result = force_remove_fuse_client(
                client_id=client_id,
                block_seconds=block_seconds,
                removed_by=removed_by,
            )
        except ValueError:
            return Response(
                {"detail": "Invalid client_id"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            return Response(
                {"detail": "Unable to force-remove this FUSE client right now"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                "success": True,
                "message": "FUSE client force-removed",
                **result,
            }
        )


class FusePairingTokenView(APIView):
    """
    Create a short-lived one-time pairing token for Linux host install scripts.
    """

    permission_classes = [IsStandardUser]

    def post(self, request):
        ttl_seconds = request.data.get("ttl_seconds")
        try:
            ttl_seconds = int(ttl_seconds) if ttl_seconds is not None else None
        except (TypeError, ValueError):
            return Response(
                {"detail": "ttl_seconds must be an integer"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_by = getattr(request.user, "username", "") if getattr(request, "user", None) else ""
        try:
            payload = create_fuse_pairing_token(
                created_by=created_by,
                ttl_seconds=ttl_seconds,
            )
        except RuntimeError:
            return Response(
                {"detail": "Pairing service unavailable right now"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(payload, status=status.HTTP_201_CREATED)


class FuseRegisterHostView(APIView):
    """
    Exchange a one-time pairing token for a host-scoped FUSE auth token.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        pairing_token = str(request.data.get("pairing_token", "")).strip()
        hostname = str(request.data.get("hostname", "")).strip() or "unknown"
        client_id_hint = str(request.data.get("client_id", "")).strip()
        mountpoint_hint = str(request.data.get("mountpoint", "")).strip()
        request_ip = _get_request_ip(request)

        if not pairing_token:
            return Response(
                {"detail": "pairing_token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            payload = register_fuse_host_with_pairing_token(
                pairing_token=pairing_token,
                hostname=hostname,
                request_ip=request_ip,
                client_id_hint=client_id_hint,
                mountpoint_hint=mountpoint_hint,
            )
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except RuntimeError:
            return Response(
                {"detail": "Pairing service unavailable right now"},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(payload, status=status.HTTP_201_CREATED)


class FuseClientDownloadView(APIView):
    """
    Serve host-side FUSE setup scripts from the local server.
    """

    permission_classes = [AllowAny]

    SCRIPT_MAP = {
        "python": ("fuse_client.py", "fuse_client.py", "text/x-python"),
        "linux": ("mount_linux.sh", "mount_linux.sh", "text/x-shellscript"),
        "linux-systemd": ("install_systemd_mounts.sh", "install_systemd_mounts.sh", "text/x-shellscript"),
    }

    TARGET_ALIASES = {
        "py": "python",
        "systemd": "linux-systemd",
    }

    def get(self, request, target="python"):
        normalized_target = (target or "python").strip().lower()
        normalized_target = self.TARGET_ALIASES.get(normalized_target, normalized_target)

        if normalized_target not in self.SCRIPT_MAP:
            return Response(
                {
                    "detail": (
                        "Invalid target. Supported values: "
                        + ", ".join(sorted(self.SCRIPT_MAP.keys()))
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_name, download_name, content_type = self.SCRIPT_MAP[normalized_target]
        script_path = os.path.join(settings.BASE_DIR, "apps", "fuse", "fuse_client", file_name)
        if not os.path.exists(script_path):
            raise Http404(f"Script not found: {file_name}")

        return FileResponse(
            open(script_path, "rb"),
            as_attachment=True,
            filename=download_name,
            content_type=content_type,
        )
