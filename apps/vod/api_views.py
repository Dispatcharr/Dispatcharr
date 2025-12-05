from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from django.shortcuts import get_object_or_404
from django.http import StreamingHttpResponse, HttpResponse, FileResponse
from django.db.models import Q
import django_filters
import logging
import os
import requests
from apps.accounts.permissions import (
    Authenticated,
    permission_classes_by_action,
)
from .models import (
    Series, VODCategory, Movie, Episode, VODLogo,
    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation, M3UVODCategoryRelation
)
from .serializers import (
    MovieSerializer,
    EpisodeSerializer,
    SeriesSerializer,
    VODCategorySerializer,
    VODLogoSerializer,
    M3UMovieRelationSerializer,
    M3USeriesRelationSerializer,
    M3UEpisodeRelationSerializer
)
from .tasks import refresh_series_episodes, refresh_movie_advanced_data
from django.utils import timezone
from datetime import timedelta

logger = logging.getLogger(__name__)


class VODPagination(PageNumberPagination):
    page_size = 20  # Default page size to match frontend default
    page_size_query_param = "page_size"  # Allow clients to specify page size
    max_page_size = 100  # Prevent excessive page sizes for VOD content


class MovieFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    m3u_account = django_filters.NumberFilter(field_name="m3u_relations__m3u_account__id")
    category = django_filters.CharFilter(method='filter_category')
    year = django_filters.NumberFilter()
    year_gte = django_filters.NumberFilter(field_name="year", lookup_expr="gte")
    year_lte = django_filters.NumberFilter(field_name="year", lookup_expr="lte")

    class Meta:
        model = Movie
        fields = ['name', 'm3u_account', 'category', 'year']

    def filter_category(self, queryset, name, value):
        """Custom category filter that handles 'name|type' format"""
        if not value:
            return queryset

        # Handle the format 'category_name|category_type'
        if '|' in value:
            category_name, category_type = value.split('|', 1)
            return queryset.filter(
                m3u_relations__category__name=category_name,
                m3u_relations__category__category_type=category_type
            )
        else:
            # Fallback: treat as category name only
            return queryset.filter(m3u_relations__category__name=value)


class MovieViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Movie content"""
    queryset = Movie.objects.all()
    serializer_class = MovieSerializer
    pagination_class = VODPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = MovieFilter
    search_fields = ['name', 'description', 'genre']
    ordering_fields = ['name', 'year', 'created_at']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        # Only return movies that have active M3U relations
        return Movie.objects.filter(
            m3u_relations__m3u_account__is_active=True
        ).distinct().select_related('logo').prefetch_related('m3u_relations__m3u_account')

    @action(detail=True, methods=['get'], url_path='providers')
    def get_providers(self, request, pk=None):
        """Get all providers (M3U accounts) that have this movie"""
        movie = self.get_object()
        relations = M3UMovieRelation.objects.filter(
            movie=movie,
            m3u_account__is_active=True
        ).select_related('m3u_account', 'category')

        serializer = M3UMovieRelationSerializer(relations, many=True)
        return Response(serializer.data)


    @action(detail=True, methods=['get'], url_path='provider-info')
    def provider_info(self, request, pk=None):
        """Get detailed movie information from the original provider, throttled to 24h."""
        movie = self.get_object()

        # Get the highest priority active relation
        relation = M3UMovieRelation.objects.filter(
            movie=movie,
            m3u_account__is_active=True
        ).select_related('m3u_account').order_by('-m3u_account__priority', 'id').first()

        if not relation:
            return Response(
                {'error': 'No active M3U account associated with this movie'},
                status=status.HTTP_400_BAD_REQUEST
            )

        force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
        now = timezone.now()
        needs_refresh = (
            force_refresh or
            not relation.last_advanced_refresh or
            (now - relation.last_advanced_refresh).total_seconds() > 86400
        )

        if needs_refresh:
            # Trigger advanced data refresh
            logger.debug(f"Refreshing advanced data for movie {movie.id} (relation ID: {relation.id})")
            refresh_movie_advanced_data(relation.id, force_refresh=force_refresh)

            # Refresh objects from database after task completion
            movie.refresh_from_db()
            relation.refresh_from_db()

        # Use refreshed data from database
        custom_props = relation.custom_properties or {}
        info = custom_props.get('detailed_info', {})
        movie_data = custom_props.get('movie_data', {})

        # Build response with available data
        response_data = {
            'id': movie.id,
            'uuid': movie.uuid,
            'stream_id': relation.stream_id,
            'name': info.get('name', movie.name),
            'o_name': info.get('o_name', ''),
            'description': info.get('description', info.get('plot', movie.description)),
            'plot': info.get('plot', info.get('description', movie.description)),
            'year': movie.year or info.get('year'),
            'release_date': (movie.custom_properties or {}).get('release_date') or info.get('release_date') or info.get('releasedate', ''),
            'genre': movie.genre or info.get('genre', ''),
            'director': (movie.custom_properties or {}).get('director') or info.get('director', ''),
            'actors': (movie.custom_properties or {}).get('actors') or info.get('actors', ''),
            'country': (movie.custom_properties or {}).get('country') or info.get('country', ''),
            'rating': movie.rating or info.get('rating', movie.rating or 0),
            'tmdb_id': movie.tmdb_id or info.get('tmdb_id', ''),
            'imdb_id': movie.imdb_id or info.get('imdb_id', ''),
            'youtube_trailer': (movie.custom_properties or {}).get('youtube_trailer') or info.get('youtube_trailer') or info.get('trailer', ''),
            'duration_secs': movie.duration_secs or info.get('duration_secs'),
            'age': info.get('age', ''),
            'backdrop_path': (movie.custom_properties or {}).get('backdrop_path') or info.get('backdrop_path', []),
            'cover': info.get('cover_big', ''),
            'cover_big': info.get('cover_big', ''),
            'movie_image': movie.logo.url if movie.logo else info.get('movie_image', ''),
            'bitrate': info.get('bitrate', 0),
            'video': info.get('video', {}),
            'audio': info.get('audio', {}),
            'container_extension': movie_data.get('container_extension', 'mp4'),
            'direct_source': movie_data.get('direct_source', ''),
            'category_id': movie_data.get('category_id', ''),
            'added': movie_data.get('added', ''),
            'm3u_account': {
                'id': relation.m3u_account.id,
                'name': relation.m3u_account.name,
                'account_type': relation.m3u_account.account_type
            }
        }
        return Response(response_data)

class EpisodeFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    series = django_filters.NumberFilter(field_name="series__id")
    m3u_account = django_filters.NumberFilter(field_name="m3u_account__id")
    season_number = django_filters.NumberFilter()
    episode_number = django_filters.NumberFilter()

    class Meta:
        model = Episode
        fields = ['name', 'series', 'm3u_account', 'season_number', 'episode_number']


class SeriesFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    m3u_account = django_filters.NumberFilter(field_name="m3u_relations__m3u_account__id")
    category = django_filters.CharFilter(method='filter_category')
    year = django_filters.NumberFilter()
    year_gte = django_filters.NumberFilter(field_name="year", lookup_expr="gte")
    year_lte = django_filters.NumberFilter(field_name="year", lookup_expr="lte")

    class Meta:
        model = Series
        fields = ['name', 'm3u_account', 'category', 'year']

    def filter_category(self, queryset, name, value):
        """Custom category filter that handles 'name|type' format"""
        if not value:
            return queryset

        # Handle the format 'category_name|category_type'
        if '|' in value:
            category_name, category_type = value.split('|', 1)
            return queryset.filter(
                m3u_relations__category__name=category_name,
                m3u_relations__category__category_type=category_type
            )
        else:
            # Fallback: treat as category name only
            return queryset.filter(m3u_relations__category__name=value)


class EpisodeViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Episode content"""
    queryset = Episode.objects.all()
    serializer_class = EpisodeSerializer
    pagination_class = VODPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = EpisodeFilter
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'season_number', 'episode_number', 'created_at']
    ordering = ['series__name', 'season_number', 'episode_number']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        return Episode.objects.select_related(
            'series', 'm3u_account'
        ).filter(m3u_account__is_active=True)


class SeriesViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for Series management"""
    queryset = Series.objects.all()
    serializer_class = SeriesSerializer
    pagination_class = VODPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = SeriesFilter
    search_fields = ['name', 'description', 'genre']
    ordering_fields = ['name', 'year', 'created_at']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def get_queryset(self):
        # Only return series that have active M3U relations
        return Series.objects.filter(
            m3u_relations__m3u_account__is_active=True
        ).distinct().select_related('logo').prefetch_related('episodes', 'm3u_relations__m3u_account')

    @action(detail=True, methods=['get'], url_path='providers')
    def get_providers(self, request, pk=None):
        """Get all providers (M3U accounts) that have this series"""
        series = self.get_object()
        relations = M3USeriesRelation.objects.filter(
            series=series,
            m3u_account__is_active=True
        ).select_related('m3u_account', 'category')

        serializer = M3USeriesRelationSerializer(relations, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'], url_path='episodes')
    def get_episodes(self, request, pk=None):
        """Get episodes for this series with provider information"""
        series = self.get_object()
        episodes = Episode.objects.filter(series=series).prefetch_related(
            'm3u_relations__m3u_account'
        ).order_by('season_number', 'episode_number')

        episodes_data = []
        for episode in episodes:
            episode_serializer = EpisodeSerializer(episode)
            episode_data = episode_serializer.data

            # Add provider information
            relations = M3UEpisodeRelation.objects.filter(
                episode=episode,
                m3u_account__is_active=True
            ).select_related('m3u_account')

            episode_data['providers'] = M3UEpisodeRelationSerializer(relations, many=True).data
            episodes_data.append(episode_data)

        return Response(episodes_data)

    @action(detail=True, methods=['get'], url_path='provider-info')
    def series_info(self, request, pk=None):
        """Get detailed series information, refreshing from provider if needed"""
        logger.debug(f"SeriesViewSet.series_info called for series ID: {pk}")
        series = self.get_object()
        logger.debug(f"Retrieved series: {series.name} (ID: {series.id})")

        # Get the highest priority active relation
        relation = M3USeriesRelation.objects.filter(
            series=series,
            m3u_account__is_active=True
        ).select_related('m3u_account').order_by('-m3u_account__priority', 'id').first()

        if not relation:
            return Response(
                {'error': 'No active M3U account associated with this series'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Check if we should refresh data (optional force refresh parameter)
            force_refresh = request.query_params.get('force_refresh', 'false').lower() == 'true'
            refresh_interval_hours = int(request.query_params.get("refresh_interval", 24))  # Default to 24 hours

            now = timezone.now()
            last_refreshed = relation.last_episode_refresh

            # Check if detailed data has been fetched
            custom_props = relation.custom_properties or {}
            episodes_fetched = custom_props.get('episodes_fetched', False)
            detailed_fetched = custom_props.get('detailed_fetched', False)

            # Force refresh if episodes have never been fetched or if forced
            if not episodes_fetched or not detailed_fetched or force_refresh:
                force_refresh = True
                logger.debug(f"Series {series.id} needs detailed/episode refresh, forcing refresh")
            elif last_refreshed is None or (now - last_refreshed) > timedelta(hours=refresh_interval_hours):
                force_refresh = True
                logger.debug(f"Series {series.id} refresh interval exceeded or never refreshed, forcing refresh")

            if force_refresh:
                logger.debug(f"Refreshing series {series.id} data from provider")
                # Use existing refresh logic with external_series_id
                from .tasks import refresh_series_episodes
                account = relation.m3u_account
                if account and account.is_active:
                    refresh_series_episodes(account, series, relation.external_series_id)
                    series.refresh_from_db()  # Reload from database after refresh
                    relation.refresh_from_db()  # Reload relation too

            # Return the database data (which should now be fresh)
            custom_props = relation.custom_properties or {}
            response_data = {
                'id': series.id,
                'series_id': relation.external_series_id,
                'name': series.name,
                'description': series.description,
                'year': series.year,
                'genre': series.genre,
                'rating': series.rating,
                'tmdb_id': series.tmdb_id,
                'imdb_id': series.imdb_id,
                'category_id': relation.category.id if relation.category else None,
                'category_name': relation.category.name if relation.category else None,
                'cover': {
                    'id': series.logo.id,
                    'url': series.logo.url,
                    'name': series.logo.name,
                } if series.logo else None,
                'last_refreshed': series.updated_at,
                'custom_properties': series.custom_properties,
                'm3u_account': {
                    'id': relation.m3u_account.id,
                    'name': relation.m3u_account.name,
                    'account_type': relation.m3u_account.account_type
                },
                'episodes_fetched': custom_props.get('episodes_fetched', False),
                'detailed_fetched': custom_props.get('detailed_fetched', False)
            }

            # Always include episodes for series info if they've been fetched
            include_episodes = request.query_params.get('include_episodes', 'true').lower() == 'true'
            if include_episodes and custom_props.get('episodes_fetched', False):
                logger.debug(f"Including episodes for series {series.id}")
                episodes_by_season = {}
                for episode in series.episodes.all().order_by('season_number', 'episode_number'):
                    season_key = str(episode.season_number or 0)
                    if season_key not in episodes_by_season:
                        episodes_by_season[season_key] = []

                    # Get episode relation for additional data
                    episode_relation = M3UEpisodeRelation.objects.filter(
                        episode=episode,
                        m3u_account=relation.m3u_account
                    ).first()

                    episode_data = {
                        'id': episode.id,
                        'uuid': episode.uuid,
                        'name': episode.name,
                        'title': episode.name,
                        'episode_number': episode.episode_number,
                        'season_number': episode.season_number,
                        'description': episode.description,
                        'air_date': episode.air_date,
                        'plot': episode.description,
                        'duration_secs': episode.duration_secs,
                        'rating': episode.rating,
                        'tmdb_id': episode.tmdb_id,
                        'imdb_id': episode.imdb_id,
                        'movie_image': episode.custom_properties.get('movie_image', '') if episode.custom_properties else '',
                        'container_extension': episode_relation.container_extension if episode_relation else 'mp4',
                        'type': 'episode',
                        'series': {
                            'id': series.id,
                            'name': series.name
                        }
                    }
                    episodes_by_season[season_key].append(episode_data)

                response_data['episodes'] = episodes_by_season
                logger.debug(f"Added {len(episodes_by_season)} seasons of episodes to response")
            elif include_episodes:
                # Episodes not yet fetched, include empty episodes list
                response_data['episodes'] = {}

            logger.debug(f"Returning series info response for series {series.id}")
            return Response(response_data)

        except Exception as e:
            logger.error(f"Error fetching series info for series {pk}: {str(e)}")
            return Response(
                {'error': f'Failed to fetch series information: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class VODCategoryFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(lookup_expr="icontains")
    category_type = django_filters.ChoiceFilter(choices=VODCategory.CATEGORY_TYPE_CHOICES)
    m3u_account = django_filters.NumberFilter(field_name="m3u_account__id")

    class Meta:
        model = VODCategory
        fields = ['name', 'category_type', 'm3u_account']


class VODCategoryViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for VOD Categories"""
    queryset = VODCategory.objects.all()
    serializer_class = VODCategorySerializer

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = VODCategoryFilter
    search_fields = ['name']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def list(self, request, *args, **kwargs):
        """Override list to ensure Uncategorized categories and relations exist for all XC accounts with VOD enabled"""
        from apps.m3u.models import M3UAccount

        # Ensure Uncategorized categories exist
        movie_category, _ = VODCategory.objects.get_or_create(
            name="Uncategorized",
            category_type="movie",
            defaults={}
        )

        series_category, _ = VODCategory.objects.get_or_create(
            name="Uncategorized",
            category_type="series",
            defaults={}
        )

        # Get all active XC accounts with VOD enabled
        xc_accounts = M3UAccount.objects.filter(
            account_type=M3UAccount.Types.XC,
            is_active=True
        )

        for account in xc_accounts:
            if account.custom_properties:
                custom_props = account.custom_properties or {}
                vod_enabled = custom_props.get("enable_vod", False)

                if vod_enabled:
                    # Ensure relations exist for this account
                    auto_enable_new = custom_props.get("auto_enable_new_groups_vod", True)

                    M3UVODCategoryRelation.objects.get_or_create(
                        category=movie_category,
                        m3u_account=account,
                        defaults={
                            'enabled': auto_enable_new,
                            'custom_properties': {}
                        }
                    )

                    M3UVODCategoryRelation.objects.get_or_create(
                        category=series_category,
                        m3u_account=account,
                        defaults={
                            'enabled': auto_enable_new,
                            'custom_properties': {}
                        }
                    )

        # Now proceed with normal list operation
        return super().list(request, *args, **kwargs)


class UnifiedContentViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet that combines Movies and Series for unified 'All' view"""
    queryset = Movie.objects.none()  # Empty queryset, we override list method
    serializer_class = MovieSerializer  # Default serializer, overridden in list
    pagination_class = VODPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    search_fields = ['name', 'description', 'genre']
    ordering_fields = ['name', 'year', 'created_at']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            return [Authenticated()]

    def list(self, request, *args, **kwargs):
        """Override list to handle unified content properly - database-level approach"""
        import logging
        from django.db import connection

        logger = logging.getLogger(__name__)
        logger.error("=== UnifiedContentViewSet.list() called ===")

        try:
            # Get pagination parameters
            page_size = int(request.query_params.get('page_size', 24))
            page_number = int(request.query_params.get('page', 1))

            logger.error(f"Page {page_number}, page_size {page_size}")

            # Calculate offset for unified pagination
            offset = (page_number - 1) * page_size

            # For high page numbers, use raw SQL for efficiency
            # This avoids loading and sorting massive amounts of data in Python

            search = request.query_params.get('search', '')
            category = request.query_params.get('category', '')

            # Build WHERE clauses
            where_conditions = [
                # Only active content
                "movies.id IN (SELECT DISTINCT movie_id FROM vod_m3umovierelation mmr JOIN m3u_m3uaccount ma ON mmr.m3u_account_id = ma.id WHERE ma.is_active = true)",
                "series.id IN (SELECT DISTINCT series_id FROM vod_m3useriesrelation msr JOIN m3u_m3uaccount ma ON msr.m3u_account_id = ma.id WHERE ma.is_active = true)"
            ]

            params = []

            if search:
                where_conditions[0] += " AND LOWER(movies.name) LIKE %s"
                where_conditions[1] += " AND LOWER(series.name) LIKE %s"
                search_param = f"%{search.lower()}%"
                params.extend([search_param, search_param])

            if category:
                if '|' in category:
                    cat_name, cat_type = category.split('|', 1)
                    if cat_type == 'movie':
                        where_conditions[0] += " AND movies.id IN (SELECT movie_id FROM vod_m3umovierelation mmr JOIN vod_vodcategory c ON mmr.category_id = c.id WHERE c.name = %s)"
                        where_conditions[1] = "1=0"  # Exclude series
                        params.append(cat_name)
                    elif cat_type == 'series':
                        where_conditions[1] += " AND series.id IN (SELECT series_id FROM vod_m3useriesrelation msr JOIN vod_vodcategory c ON msr.category_id = c.id WHERE c.name = %s)"
                        where_conditions[0] = "1=0"  # Exclude movies
                        params.append(cat_name)
                else:
                    where_conditions[0] += " AND movies.id IN (SELECT movie_id FROM vod_m3umovierelation mmr JOIN vod_vodcategory c ON mmr.category_id = c.id WHERE c.name = %s)"
                    where_conditions[1] += " AND series.id IN (SELECT series_id FROM vod_m3useriesrelation msr JOIN vod_vodcategory c ON msr.category_id = c.id WHERE c.name = %s)"
                    params.extend([category, category])

            # Use UNION ALL with ORDER BY and LIMIT/OFFSET for true unified pagination
            # This is much more efficient than Python sorting
            sql = f"""
            WITH unified_content AS (
                SELECT
                    movies.id,
                    movies.uuid,
                    movies.name,
                    movies.description,
                    movies.year,
                    movies.rating,
                    movies.genre,
                    movies.duration_secs as duration,
                    movies.created_at,
                    movies.updated_at,
                    movies.custom_properties,
                    movies.logo_id,
                    logo.name as logo_name,
                    logo.url as logo_url,
                    'movie' as content_type
                FROM vod_movie movies
                LEFT JOIN vod_vodlogo logo ON movies.logo_id = logo.id
                WHERE {where_conditions[0]}

                UNION ALL

                SELECT
                    series.id,
                    series.uuid,
                    series.name,
                    series.description,
                    series.year,
                    series.rating,
                    series.genre,
                    NULL as duration,
                    series.created_at,
                    series.updated_at,
                    series.custom_properties,
                    series.logo_id,
                    logo.name as logo_name,
                    logo.url as logo_url,
                    'series' as content_type
                FROM vod_series series
                LEFT JOIN vod_vodlogo logo ON series.logo_id = logo.id
                WHERE {where_conditions[1]}
            )
            SELECT * FROM unified_content
            ORDER BY LOWER(name), id
            LIMIT %s OFFSET %s
            """

            params.extend([page_size, offset])

            logger.error(f"Executing SQL with LIMIT {page_size} OFFSET {offset}")

            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                columns = [col[0] for col in cursor.description]
                results = []

                for row in cursor.fetchall():
                    item_dict = dict(zip(columns, row))

                    # Build logo object in the format expected by frontend
                    logo_data = None
                    if item_dict['logo_id']:
                        logo_data = {
                            'id': item_dict['logo_id'],
                            'name': item_dict['logo_name'],
                            'url': item_dict['logo_url'],
                            'cache_url': f"/api/vod/vodlogos/{item_dict['logo_id']}/cache/",
                            'movie_count': 0,  # We don't calculate this in raw SQL
                            'series_count': 0,  # We don't calculate this in raw SQL
                            'is_used': True
                        }

                    # Convert to the format expected by frontend
                    formatted_item = {
                        'id': item_dict['id'],
                        'uuid': str(item_dict['uuid']),
                        'name': item_dict['name'],
                        'description': item_dict['description'] or '',
                        'year': item_dict['year'],
                        'rating': float(item_dict['rating']) if item_dict['rating'] else 0.0,
                        'genre': item_dict['genre'] or '',
                        'duration': item_dict['duration'],
                        'created_at': item_dict['created_at'].isoformat() if item_dict['created_at'] else None,
                        'updated_at': item_dict['updated_at'].isoformat() if item_dict['updated_at'] else None,
                        'custom_properties': item_dict['custom_properties'] or {},
                        'logo': logo_data,
                        'content_type': item_dict['content_type']
                    }
                    results.append(formatted_item)

            logger.error(f"Retrieved {len(results)} results via SQL")

            # Get total count estimate (for pagination info)
            # Use a separate efficient count query
            count_sql = f"""
            SELECT COUNT(*) FROM (
                SELECT 1 FROM vod_movie movies WHERE {where_conditions[0]}
                UNION ALL
                SELECT 1 FROM vod_series series WHERE {where_conditions[1]}
            ) as total_count
            """

            count_params = params[:-2]  # Remove LIMIT and OFFSET params

            with connection.cursor() as cursor:
                cursor.execute(count_sql, count_params)
                total_count = cursor.fetchone()[0]

            response_data = {
                'count': total_count,
                'next': offset + page_size < total_count,
                'previous': page_number > 1,
                'results': results
            }

            return Response(response_data)

        except Exception as e:
            logger.error(f"Error in UnifiedContentViewSet.list(): {e}")
            import traceback
            logger.error(traceback.format_exc())
            return Response({'error': str(e)}, status=500)


class VODLogoPagination(PageNumberPagination):
    page_size = 100
    page_size_query_param = "page_size"
    max_page_size = 1000


class VODLogoViewSet(viewsets.ModelViewSet):
    """ViewSet for VOD Logo management"""
    queryset = VODLogo.objects.all()
    serializer_class = VODLogoSerializer
    pagination_class = VODLogoPagination
    filter_backends = [SearchFilter, OrderingFilter]
    search_fields = ['name', 'url']
    ordering_fields = ['name', 'id']
    ordering = ['name']

    def get_permissions(self):
        try:
            return [perm() for perm in permission_classes_by_action[self.action]]
        except KeyError:
            if self.action == 'cache':
                return [AllowAny()]
            return [Authenticated()]

    def get_queryset(self):
        """Optimize queryset with prefetch and add filtering"""
        queryset = VODLogo.objects.prefetch_related('movie', 'series').order_by('name')

        # Filter by specific IDs
        ids = self.request.query_params.getlist('ids')
        if ids:
            try:
                id_list = [int(id_str) for id_str in ids if id_str.isdigit()]
                if id_list:
                    queryset = queryset.filter(id__in=id_list)
            except (ValueError, TypeError):
                queryset = VODLogo.objects.none()

        # Filter by usage
        used_filter = self.request.query_params.get('used', None)
        if used_filter == 'true':
            # Return logos that are used by movies OR series
            queryset = queryset.filter(
                Q(movie__isnull=False) | Q(series__isnull=False)
            ).distinct()
        elif used_filter == 'false':
            # Return logos that are NOT used by either
            queryset = queryset.filter(
                movie__isnull=True,
                series__isnull=True
            )
        elif used_filter == 'movies':
            # Return logos that are used by movies (may also be used by series)
            queryset = queryset.filter(movie__isnull=False).distinct()
        elif used_filter == 'series':
            # Return logos that are used by series (may also be used by movies)
            queryset = queryset.filter(series__isnull=False).distinct()


        # Filter by name
        name_query = self.request.query_params.get('name', None)
        if name_query:
            queryset = queryset.filter(name__icontains=name_query)

        # No pagination mode
        if self.request.query_params.get('no_pagination', 'false').lower() == 'true':
            self.pagination_class = None

        return queryset

    @action(detail=True, methods=["get"], permission_classes=[AllowAny])
    def cache(self, request, pk=None):
        """Streams the VOD logo file, whether it's local or remote."""
        logo = self.get_object()

        if not logo.url:
            return HttpResponse(status=404)

        # Check if this is a local file path
        if logo.url.startswith('/data/'):
            # It's a local file
            file_path = logo.url
            if not os.path.exists(file_path):
                logger.error(f"VOD logo file not found: {file_path}")
                return HttpResponse(status=404)

            try:
                return FileResponse(open(file_path, 'rb'), content_type='image/png')
            except Exception as e:
                logger.error(f"Error serving VOD logo file {file_path}: {str(e)}")
                return HttpResponse(status=500)
        else:
            # It's a remote URL - proxy it
            try:
                response = requests.get(logo.url, stream=True, timeout=10)
                response.raise_for_status()

                content_type = response.headers.get('Content-Type', 'image/png')

                return StreamingHttpResponse(
                    response.iter_content(chunk_size=8192),
                    content_type=content_type
                )
            except requests.exceptions.RequestException as e:
                logger.error(f"Error fetching remote VOD logo {logo.url}: {str(e)}")
                return HttpResponse(status=404)

    @action(detail=False, methods=["delete"], url_path="bulk-delete")
    def bulk_delete(self, request):
        """Delete multiple VOD logos at once"""
        logo_ids = request.data.get('logo_ids', [])

        if not logo_ids:
            return Response(
                {"error": "No logo IDs provided"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Get logos to delete
            logos = VODLogo.objects.filter(id__in=logo_ids)
            deleted_count = logos.count()

            # Delete them
            logos.delete()

            return Response({
                "deleted_count": deleted_count,
                "message": f"Successfully deleted {deleted_count} VOD logo(s)"
            })
        except Exception as e:
            logger.error(f"Error during bulk VOD logo deletion: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    @action(detail=False, methods=["post"])
    def cleanup(self, request):
        """Delete all VOD logos that are not used by any movies or series"""
        try:
            # Find unused logos
            unused_logos = VODLogo.objects.filter(
                movie__isnull=True,
                series__isnull=True
            )

            deleted_count = unused_logos.count()
            logo_names = list(unused_logos.values_list('name', flat=True))

            # Delete them
            unused_logos.delete()

            logger.info(f"Cleaned up {deleted_count} unused VOD logos: {logo_names}")

            return Response({
                "deleted_count": deleted_count,
                "deleted_logos": logo_names,
                "message": f"Successfully deleted {deleted_count} unused VOD logo(s)"
            })
        except Exception as e:
            logger.error(f"Error during VOD logo cleanup: {str(e)}")
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

