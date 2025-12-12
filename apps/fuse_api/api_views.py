import json
from urllib.parse import unquote

from django.db.models import Prefetch
from django.http import JsonResponse, FileResponse, Http404
from django.conf import settings
import os
from django.urls import reverse
from rest_framework import status, viewsets
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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
from .serializers import FuseEntrySerializer, FuseSettingsSerializer


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


class FuseBrowseView(APIView):
    """
    Read-only filesystem-style browsing for Movies and TV.
    """

    permission_classes = [AllowAny]

    def get(self, request, mode):
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
            ).order_by("name")
            entries = [
                {
                    "name": cat.name,
                    "path": f"/{cat.name}",
                    "is_dir": True,
                    "content_type": "category",
                    "uuid": None,
                }
                for cat in categories
            ]
            return {"path": "/", "entries": FuseEntrySerializer(entries, many=True).data}

        # Category -> list movies
        category_name = parts[0]
        category = (
            VODCategory.objects.filter(
                name=category_name, category_type="movie"
            ).first()
        )
        if not category:
            return {"path": f"/{category_name}", "entries": []}

        movies = (
            Movie.objects.filter(
                m3u_relations__category=category,
                m3u_relations__m3u_account__is_active=True,
            )
            .distinct()
            .select_related("logo")
            .prefetch_related(
                Prefetch(
                    "m3u_relations",
                    queryset=M3UMovieRelation.objects.filter(
                        m3u_account__is_active=True
                    ).select_related("m3u_account"),
                )
            )
            .order_by("name")
        )

        entries = []
        for movie in movies:
            relation = _select_best_relation(getattr(movie, "m3u_relations", []))
            extension = getattr(relation, "container_extension", None) or "mp4"
            name = f"{movie.name} ({movie.year})" if movie.year else movie.name
            file_name = f"{name}.{extension}"
            stream_url = None
            if movie.uuid:
                stream_url = request.build_absolute_uri(
                    reverse(
                        "proxy:vod_proxy:vod_stream",
                        kwargs={"content_type": "movie", "content_id": movie.uuid},
                    )
                )

            entries.append(
                {
                    "name": file_name,
                    "path": f"/{category.name}/{file_name}",
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

        return {
            "path": f"/{category.name}",
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
                .order_by("name")
            )
            entries = [
                {
                    "name": serie.name,
                    "path": f"/{serie.name}",
                    "is_dir": True,
                    "content_type": "series",
                    "uuid": None,
                }
                for serie in series
            ]
            return {"path": "/", "entries": FuseEntrySerializer(entries, many=True).data}

        # Series -> list seasons
        series_name = parts[0]
        series_obj = Series.objects.filter(name=series_name).first()
        if not series_obj:
            return {"path": f"/{series_name}", "entries": []}

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
                        "path": f"/{series_name}/{label}",
                        "is_dir": True,
                        "content_type": "season",
                        "uuid": None,
                        "season": int(num),
                    }
                )
            return {
                "path": f"/{series_name}",
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
            .select_related("series")
            .prefetch_related(
                Prefetch(
                    "m3u_relations",
                    queryset=M3UEpisodeRelation.objects.filter(
                        m3u_account__is_active=True
                    ).select_related("m3u_account"),
                )
            )
            .order_by("episode_number")
        )

        entries = []
        for ep in episodes:
            relation = _select_best_relation(getattr(ep, "m3u_relations", []))
            extension = getattr(relation, "container_extension", None) or "mp4"
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
                    "path": f"/{series_name}/{season_label}/{file_name}",
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

        return {
            "path": f"/{series_name}/{season_label}",
            "entries": FuseEntrySerializer(entries, many=True).data,
        }


class FuseSettingsViewSet(viewsets.ViewSet):
    """
    Store FUSE client guidance in CoreSettings as JSON.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = FuseSettingsSerializer

    DEFAULTS = {
        "enable_fuse": False,
        "backend_base_url": "",
        "movies_mount_path": "/mnt/vod_movies",
        "tv_mount_path": "/mnt/vod_tv",
    }

    def _get_or_create(self):
        try:
            obj = CoreSettings.objects.get(key=FUSE_SETTINGS_KEY)
            data = json.loads(obj.value)
        except (CoreSettings.DoesNotExist, json.JSONDecodeError):
            data = self.DEFAULTS.copy()
            obj, _ = CoreSettings.objects.get_or_create(
                key=FUSE_SETTINGS_KEY,
                defaults={"name": "Fuse Settings", "value": json.dumps(data)},
            )
        return obj, data

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
        obj.value = json.dumps(serializer.validated_data)
        obj.save()
        return Response(serializer.validated_data)


class FuseStreamURLView(APIView):
    """
    Provide a stable stream URL for a given movie/episode UUID.
    """

    permission_classes = [AllowAny]

    def get(self, request, content_type, content_id):
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


class FuseClientDownloadView(APIView):
    """
    Serve the fuse_client.py script from the local server.
    """

    permission_classes = [AllowAny]

    def get(self, request):
        script_path = os.path.join(settings.BASE_DIR, "fuse_client", "fuse_client.py")
        if not os.path.exists(script_path):
            raise Http404("Fuse client script not found")

        return FileResponse(
            open(script_path, "rb"),
            as_attachment=True,
            filename="fuse_client.py",
            content_type="text/x-python",
        )
