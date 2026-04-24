from django.contrib import admin
from .models import (
    Series, VODCategory, Movie, Episode,
    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation
)


@admin.register(VODCategory)
class VODCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'category_type', 'created_at']
    list_filter = ['category_type', 'created_at']
    search_fields = ['name']


@admin.register(Series)
class SeriesAdmin(admin.ModelAdmin):
    list_display = ['name', 'year', 'genre', 'created_at']
    list_filter = ['year', 'created_at']
    search_fields = ['name', 'description', 'tmdb_id', 'imdb_id']
    readonly_fields = ['uuid', 'created_at', 'updated_at']


@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['name', 'year', 'genre', 'duration_secs', 'created_at']
    list_filter = ['year', 'created_at']
    search_fields = ['name', 'description', 'tmdb_id', 'imdb_id']
    readonly_fields = ['uuid', 'created_at', 'updated_at']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('logo')


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ['name', 'series', 'season_number', 'episode_number', 'duration_secs', 'created_at']
    list_filter = ['series', 'season_number', 'created_at']
    search_fields = ['name', 'description', 'series__name']
    readonly_fields = ['uuid', 'created_at', 'updated_at']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('series')


@admin.register(M3UMovieRelation)
class M3UMovieRelationAdmin(admin.ModelAdmin):
    list_display = ['movie', 'm3u_account', 'category', 'stream_id', 'created_at']
    list_filter = ['m3u_account', 'category', 'created_at']
    search_fields = ['movie__name', 'm3u_account__name', 'stream_id']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(M3USeriesRelation)
class M3USeriesRelationAdmin(admin.ModelAdmin):
    list_display = ['series', 'm3u_account', 'category', 'external_series_id', 'created_at']
    list_filter = ['m3u_account', 'category', 'created_at']
    search_fields = ['series__name', 'm3u_account__name', 'external_series_id']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(M3UEpisodeRelation)
class M3UEpisodeRelationAdmin(admin.ModelAdmin):
    list_display = ['episode', 'm3u_account', 'series_relation', 'stream_id', 'created_at']
    list_filter = ['m3u_account', 'created_at']
    search_fields = ['episode__name', 'episode__series__name', 'm3u_account__name', 'stream_id']
    readonly_fields = ['created_at', 'updated_at']

