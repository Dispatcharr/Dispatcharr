from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from queue import Queue
from celery import shared_task, current_app, group
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.db.models import Exists, F, OuterRef, Q, Subquery, TextField, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce, Lower
from apps.m3u.models import M3UAccount
from apps.m3u.utils import parse_is_adult
from core.xtream_codes import Client as XtreamCodesClient
from core.utils import (
    TaskLockRenewer,
    acquire_task_lock,
    release_task_lock,
    truncate_with_warning,
)
from apps.m3u.stalker import StalkerClient, StalkerError, StalkerRecoverableError
from .models import (
    VODCategory, Series, Movie, Episode, VODLogo,
    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation, M3UVODCategoryRelation
)
from .utils import category_language
from datetime import datetime
import logging
import base64
import json
import re
import threading
import time

logger = logging.getLogger(__name__)

DEFAULT_STALKER_CATALOG_WORKERS = 4
DEFAULT_STALKER_CATALOG_PAGE_WORKERS = 2
# Seconds to wait before each retry of a failed Stalker catalog page; one
# entry per retry, so the page gets len() + 1 attempts in total.
STALKER_CATALOG_RETRY_DELAYS = (2, 5)
_stalker_catalog_auth_lock = threading.Lock()
# Failure marker for an unfiltered catalog request (no category, or "*").
STALKER_ALL_CATEGORIES = "*"


@dataclass
class StalkerCatalogFetchReport:
    """Which Stalker category fetches of one content type failed after retries."""

    requested_count: int = 0
    failed_provider_category_ids: set = field(default_factory=set)
    last_error: Exception = None

    @property
    def all_failed(self):
        return bool(self.requested_count) and (
            len(self.failed_provider_category_ids) >= self.requested_count
        )


def supports_parallel_stalker_catalog(client):
    return isinstance(client, StalkerClient) or callable(
        getattr(type(client), "clone_for_parallel_catalog", None)
    )


def _empty_categories_should_abort(categories_data, account, category_type):
    """True when an empty provider response would wipe existing group selections."""
    if categories_data:
        return False
    return M3UVODCategoryRelation.objects.filter(
        m3u_account=account,
        category__category_type=category_type,
    ).exclude(category__name='Uncategorized').exists()


def _existing_vod_row(key, existing):
    """Exact (identity, language) row, otherwise the untagged row for that identity.

    A new stream in a tagged category joins the untagged movie or series when
    one already exists, so the batch does not mint a second id. Reconcile
    renames or splits that row afterwards.
    """
    row = existing.get(key)
    if row is not None:
        return row
    if key[-1] != '':
        return existing.get(key[:-1] + ('',))
    return None


def _name_year_keys_including_untagged(name_year_language_keys):
    """Include the untagged (name, year, '') key so the fallback above can see it."""
    keys = list(name_year_language_keys)
    for name, year, language in name_year_language_keys:
        if language:
            keys.append((name, year, ''))
    return keys


def _match_existing_vod_row(row, by_tmdb, by_imdb, by_name_year):
    """DB row this unsaved movie/series should attach to, or None to insert it."""
    existing = None
    if row.tmdb_id and (str(row.tmdb_id), row.language) in by_tmdb:
        existing = by_tmdb[(str(row.tmdb_id), row.language)]
    elif row.imdb_id and (str(row.imdb_id), row.language) in by_imdb:
        existing = by_imdb[(str(row.imdb_id), row.language)]
    elif not row.tmdb_id and not row.imdb_id:
        existing = by_name_year.get((row.name, row.year, row.language))
    if existing is not None or not row.language:
        return existing
    if row.tmdb_id:
        return by_tmdb.get((str(row.tmdb_id), ''))
    if row.imdb_id:
        return by_imdb.get((str(row.imdb_id), ''))
    return by_name_year.get((row.name, row.year, ''))


def lookup_by_name_year(model, name_year_language_keys):
    """Return {(name, year, language): row} for rows without TMDB/IMDB IDs.

    Scoped to the names in this batch instead of scanning the full table.
    """
    if not name_year_language_keys:
        return {}
    wanted = set(name_year_language_keys)
    names = {name for name, _, _ in wanted}
    found = {}
    for row in model.objects.filter(
        tmdb_id__isnull=True,
        imdb_id__isnull=True,
        name__in=names,
    ):
        key = (row.name, row.year, row.language)
        if key in wanted:
            found[key] = row
    return found


def remove_account_vod_relations(account_id):
    """Remove all VOD relations for one account, then prune newly orphaned rows."""
    logger.info("Removing VOD relations for account %s", account_id)

    deleted_movie_relations, _ = M3UMovieRelation.objects.filter(
        m3u_account_id=account_id
    ).delete()
    deleted_episode_relations, _ = M3UEpisodeRelation.objects.filter(
        m3u_account_id=account_id
    ).delete()
    deleted_series_relations, _ = M3USeriesRelation.objects.filter(
        m3u_account_id=account_id
    ).delete()

    cleanup_result = cleanup_orphaned_vod_content(
        account_id=account_id,
        scan_start_time=timezone.now(),
    )

    return (
        f"Removed {deleted_movie_relations} movie relations and "
        f"{deleted_episode_relations} episode relations and "
        f"{deleted_series_relations} series relations. {cleanup_result}"
    )


def _abort_vod_refresh_without_categories(account):
    """Report an aborted VOD refresh when the provider returned no categories."""
    from apps.m3u.tasks import send_m3u_update

    message = (
        f"Provider returned no VOD categories for account {account.name}; "
        "aborting VOD refresh to preserve existing category selections"
    )
    logger.warning(message)
    send_m3u_update(
        account.id,
        "vod_refresh",
        100,
        status="error",
        message=f"VOD refresh failed: {message}",
    )
    return f"VOD refresh failed: {message}"


@shared_task
def refresh_vod_content(account_id):
    """Refresh VOD content for an M3U account with batch processing for improved performance"""
    # Import here to avoid circular import
    from apps.m3u.tasks import send_m3u_update

    if not acquire_task_lock("refresh_vod_content", account_id):
        message = f"VOD refresh already running for account {account_id}"
        logger.info(message)
        try:
            send_m3u_update(
                account_id,
                "vod_refresh",
                100,
                status="warning",
                message=message,
            )
        except Exception:
            logger.debug(
                "Failed to send duplicate VOD refresh warning for account %s",
                account_id,
            )
        return message

    try:
        with TaskLockRenewer("refresh_vod_content", account_id):
            account = M3UAccount.objects.select_related("user_agent").get(
                id=account_id, is_active=True
            )

            def send_vod_progress(progress, message=None, **extra):
                send_m3u_update(
                    account_id,
                    "vod_refresh",
                    int(max(0, min(100, progress))),
                    status="processing",
                    message=message,
                    **extra,
                )

            if account.account_type not in (
                M3UAccount.Types.XC,
                M3UAccount.Types.STALKER,
            ):
                logger.warning(f"VOD refresh called for unsupported account {account_id}")
                return "VOD refresh only available for XtreamCodes and Stalker accounts"

            logger.info(f"Starting batch VOD refresh for account {account.name}")
            start_time = timezone.now()
            movie_report = series_report = StalkerCatalogFetchReport()

            # Send start notification
            send_vod_progress(0, "VOD content refresh starting...")

            if account.account_type == M3UAccount.Types.XC:
                with XtreamCodesClient(
                    account.server_url,
                    account.username,
                    account.password,
                    account.get_user_agent_string()
                ) as client:
                    send_vod_progress(5, "Loading VOD categories...")

                    category_maps = refresh_categories(account.id, client)
                    if category_maps is None:
                        return _abort_vod_refresh_without_categories(account)

                    movie_categories, series_categories = category_maps

                    logger.debug("Fetching relations for filtering category filtering")
                    relations = { rel.category_id: rel for rel in M3UVODCategoryRelation.objects
                        .filter(m3u_account=account)
                        .select_related("category", "m3u_account")
                    }

                    # Refresh movies with batch processing (pass scan start time)
                    send_vod_progress(25, "Importing movie catalog...")
                    refresh_movies(client, account, movie_categories, relations, scan_start_time=start_time)

                    # Refresh series with batch processing (pass scan start time)
                    send_vod_progress(55, "Importing TV show catalog...")
                    refresh_series(
                        client,
                        account,
                        series_categories,
                        relations,
                        scan_start_time=start_time,
                    )
            else:
                client = StalkerClient(
                    server_url=account.server_url,
                    mac=(account.custom_properties or {}).get("mac", ""),
                    username=account.username or "",
                    password=account.password or "",
                    user_agent=getattr(account.user_agent, "user_agent", None),
                    custom_properties=account.custom_properties or {},
                )
                send_vod_progress(5, "Loading VOD categories...")
                category_maps = refresh_categories(account.id, client=client)
                if category_maps is None:
                    return _abort_vod_refresh_without_categories(account)

                movie_categories, series_categories = category_maps

                logger.debug("Fetching relations for Stalker VOD category filtering")
                relations = {
                    rel.category_id: rel
                    for rel in M3UVODCategoryRelation.objects.filter(m3u_account=account)
                    .select_related("category", "m3u_account")
                }

                send_vod_progress(20, "Importing movie catalog...")
                movie_report = refresh_movies(
                    client,
                    account,
                    movie_categories,
                    relations,
                    scan_start_time=start_time,
                )
                send_vod_progress(40, "Importing TV show catalog...")
                series_report = refresh_series(
                    client,
                    account,
                    series_categories,
                    relations,
                    scan_start_time=start_time,
                    progress_callback=lambda completed, total: send_vod_progress(
                        40 + round((completed / max(total, 1)) * 50),
                        (
                            f"Fetching TV show details and episodes... ({completed}/{total})"
                            if total
                            else "Fetching TV show details and episodes..."
                        ),
                        items_processed=completed,
                        items_total=total,
                    ),
                )
                raise_if_every_stalker_category_failed(movie_report, series_report)

            # Reconcile language once per account refresh, not per batch. Relations
            # stay pinned during the batch (see process_movie_batch /
            # process_series_batch). Must run before cleanup_orphaned_vod_content
            # so cleanup's orphan-deletion stays a backstop, not the primary mechanism.
            send_vod_progress(92, "Reconciling VOD language identity...")
            logger.info(f"Reconciling VOD language identity for account {account.name}")
            movie_summary = reconcile_movie_language_identity(account, scan_start_time=start_time)
            series_summary = reconcile_series_language_identity(account, scan_start_time=start_time)
            skip_note = _language_skip_note(movie_summary, series_summary)

            end_time = timezone.now()
            duration = (end_time - start_time).total_seconds()

            logger.info(
                f"Batch VOD refresh completed for account {account.name} "
                f"in {duration:.2f} seconds{skip_note}"
            )

            if account.account_type in (
                M3UAccount.Types.XC,
                M3UAccount.Types.STALKER,
            ):
                # Cleanup orphaned VOD content after refresh (scoped to this account only)
                send_vod_progress(95, "Finalizing VOD refresh...")
                logger.info(f"Starting cleanup of orphaned VOD content for account {account.name}")
                cleanup_result = cleanup_orphaned_vod_content(
                    account_id=account_id,
                    scan_start_time=start_time,
                    keep_movie_relations=build_stalker_failed_category_filter(
                        movie_report, movie_categories,
                    ),
                    keep_series_relations=build_stalker_failed_category_filter(
                        series_report, series_categories,
                    ),
                )
                logger.info(f"VOD cleanup completed: {cleanup_result}")

            # Send completion notification
            completion_status = "success"
            if account.account_type == M3UAccount.Types.STALKER:
                movie_count = len(movie_categories)
                series_count = len(series_categories)
                completion_message = (
                    f"Stalker VOD refresh completed in {duration:.2f} seconds "
                    f"({movie_count} movie categories, {series_count} series categories)"
                    f"{skip_note}"
                )
                failed_names = sorted(
                    get_stalker_failed_category_names(movie_report, movie_categories)
                    + get_stalker_failed_category_names(series_report, series_categories)
                )
                if failed_names:
                    completion_status = "warning"
                    completion_message += (
                        "; kept existing content for categories that failed "
                        f"to load: {', '.join(failed_names)}"
                    )
                    logger.warning(completion_message)
            else:
                completion_message = f"VOD refresh completed in {duration:.2f} seconds{skip_note}"

            send_m3u_update(account_id, "vod_refresh", 100, status=completion_status,
                           message=completion_message)

            return completion_message

    except Exception as e:
        import traceback
        logger.error(f"Error refreshing VOD for account {account_id}: {str(e)}")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")

        # Send error notification
        send_m3u_update(account_id, "vod_refresh", 100, status="error",
                       message=f"VOD refresh failed: {str(e)}")

        return f"VOD refresh failed: {str(e)}"
    finally:
        try:
            release_task_lock("refresh_vod_content", account_id)
        except Exception:
            logger.debug(
                "Failed to release VOD refresh lock for account %s",
                account_id,
            )

def refresh_categories(account_id, client=None):
    account = M3UAccount.objects.select_related("user_agent").get(id=account_id, is_active=True)

    if not client:
        if account.account_type == M3UAccount.Types.XC:
            client = XtreamCodesClient(
                account.server_url,
                account.username,
                account.password,
                account.get_user_agent_string()
            )
        elif account.account_type == M3UAccount.Types.STALKER:
            client = StalkerClient(
                server_url=account.server_url,
                mac=(account.custom_properties or {}).get("mac", ""),
                username=account.username or "",
                password=account.password or "",
                user_agent=getattr(account.user_agent, "user_agent", None),
                custom_properties=account.custom_properties or {},
            )
        else:
            raise ValueError(
                f"Unsupported VOD category refresh account type: {account.account_type}"
            )
    logger.info(f"Refreshing movie categories for account {account.name}")

    # First, get the category list to properly map category IDs and names
    logger.info("Fetching movie categories from provider...")
    if account.account_type == M3UAccount.Types.STALKER:
        discovery = client.discover_vod_categories()
        if discovery.token:
            client.token = discovery.token
        client.vod_portal_url = discovery.normalized_portal_url
        categories_data = discovery.movie_categories
        persist_stalker_runtime_state(
            account,
            client,
            portal_url=discovery.normalized_portal_url,
        )
    else:
        categories_data = client.get_vod_categories()

    if _empty_categories_should_abort(categories_data, account, 'movie'):
        logger.warning(
            f"Provider returned no movie categories for account {account.id} "
            f"({account.name}); aborting VOD refresh to preserve existing category selections"
        )
        return None

    category_map = batch_create_categories(categories_data, 'movie', account)

    # Create a mapping from provider category IDs to our category objects
    movies_category_id_map = {}
    for cat_data in categories_data:
        cat_name = extract_category_name(cat_data, account.account_type)
        provider_cat_id = extract_provider_category_id(cat_data, account.account_type)
        our_category = category_map.get(cat_name)
        if provider_cat_id and our_category:
            movies_category_id_map[str(provider_cat_id)] = our_category

    # Get the category list to properly map category IDs and names
    logger.info("Fetching series categories from provider...")
    if account.account_type == M3UAccount.Types.STALKER:
        categories_data = discovery.series_categories
    else:
        categories_data = client.get_series_categories()

    if _empty_categories_should_abort(categories_data, account, 'series'):
        logger.warning(
            f"Provider returned no series categories for account {account.id} "
            f"({account.name}); aborting VOD refresh to preserve existing category selections"
        )
        return None
    category_map = batch_create_categories(categories_data, 'series', account)

    # Create a mapping from provider category IDs to our category objects
    series_category_id_map = {}
    for cat_data in categories_data:
        cat_name = extract_category_name(cat_data, account.account_type)
        provider_cat_id = extract_provider_category_id(cat_data, account.account_type)
        our_category = category_map.get(cat_name)
        if provider_cat_id and our_category:
            series_category_id_map[str(provider_cat_id)] = our_category

    return movies_category_id_map, series_category_id_map

def refresh_movies(client, account, categories_by_provider, relations, scan_start_time=None):
    """Refresh movie content using single API call for all movies.

    Returns a StalkerCatalogFetchReport; it is empty for XC accounts.
    """
    logger.info(f"Refreshing movies for account {account.name}")
    seen_movie_keys = set()

    # Ensure "Uncategorized" category exists for movies without a category
    uncategorized_category, created = VODCategory.objects.get_or_create(
        name="Uncategorized",
        category_type="movie",
        defaults={}
    )

    # Ensure there's a relation for the Uncategorized category
    account_custom_props = account.custom_properties or {}
    auto_enable_new = account_custom_props.get("auto_enable_new_groups_vod", True)

    uncategorized_relation, rel_created = M3UVODCategoryRelation.objects.get_or_create(
        category=uncategorized_category,
        m3u_account=account,
        defaults={
            'enabled': auto_enable_new,
            'custom_properties': {}
        }
    )

    if created:
        logger.info(f"Created 'Uncategorized' category for movies")
    if rel_created:
        logger.info(f"Created relation for 'Uncategorized' category (enabled={auto_enable_new})")

    # Add uncategorized category to relations dict for easy access
    relations[uncategorized_category.id] = uncategorized_relation

    # Add to categories_by_provider with a special key for items without category
    categories_by_provider['__uncategorized__'] = uncategorized_category

    if account.account_type == M3UAccount.Types.STALKER:
        logger.info("Fetching Stalker movies from provider...")
        total_movies = 0
        total_chunks = 0
        report = StalkerCatalogFetchReport()

        for chunk in iter_stalker_catalog_batches(
            client,
            account,
            categories_by_provider,
            relations,
            content_type="movie",
            report=report,
        ):
            total_chunks += 1
            total_movies += len(chunk)
            logger.info(
                "Processing Stalker movie chunk %s (%s movies)",
                total_chunks,
                len(chunk),
            )
            process_movie_batch(
                account,
                chunk,
                categories_by_provider,
                relations,
                scan_start_time,
                seen_movie_keys=seen_movie_keys,
            )

        logger.info(
            "Completed processing all %s Stalker movies in %s chunks",
            total_movies,
            total_chunks,
        )
        return report
    else:
        # Get all movies in a single API call
        logger.info("Fetching all movies from provider...")
        all_movies_data = client.get_vod_streams()  # No category_id = get all movies

    # Process movies in chunks using the simple approach
    chunk_size = 1000
    total_movies = len(all_movies_data)
    total_chunks = (total_movies + chunk_size - 1) // chunk_size if total_movies > 0 else 0

    for i in range(0, total_movies, chunk_size):
        chunk = all_movies_data[i:i + chunk_size]
        chunk_num = (i // chunk_size) + 1

        logger.info(f"Processing movie chunk {chunk_num}/{total_chunks} ({len(chunk)} movies)")
        process_movie_batch(
            account,
            chunk,
            categories_by_provider,
            relations,
            scan_start_time,
            seen_movie_keys=seen_movie_keys,
        )

    del all_movies_data
    logger.info(f"Completed processing all {total_movies} movies in {total_chunks} chunks")
    return StalkerCatalogFetchReport()


def refresh_series(
    client,
    account,
    categories_by_provider,
    relations,
    scan_start_time=None,
    progress_callback=None,
):
    """Refresh series content using single API call for all series.

    Returns a StalkerCatalogFetchReport; it is empty for XC accounts.
    """
    logger.info(f"Refreshing series for account {account.name}")
    seen_series_keys = set()
    stalker_series_relation_ids = set()

    # Ensure "Uncategorized" category exists for series without a category
    uncategorized_category, created = VODCategory.objects.get_or_create(
        name="Uncategorized",
        category_type="series",
        defaults={}
    )

    # Ensure there's a relation for the Uncategorized category
    account_custom_props = account.custom_properties or {}
    auto_enable_new = account_custom_props.get("auto_enable_new_groups_series", True)

    uncategorized_relation, rel_created = M3UVODCategoryRelation.objects.get_or_create(
        category=uncategorized_category,
        m3u_account=account,
        defaults={
            'enabled': auto_enable_new,
            'custom_properties': {}
        }
    )

    if created:
        logger.info(f"Created 'Uncategorized' category for series")
    if rel_created:
        logger.info(f"Created relation for 'Uncategorized' category (enabled={auto_enable_new})")

    # Add uncategorized category to relations dict for easy access
    relations[uncategorized_category.id] = uncategorized_relation

    # Add to categories_by_provider with a special key for items without category
    categories_by_provider['__uncategorized__'] = uncategorized_category

    if account.account_type == M3UAccount.Types.STALKER:
        logger.info("Fetching Stalker series from provider...")
        total_series = 0
        total_chunks = 0
        report = StalkerCatalogFetchReport()

        for chunk in iter_stalker_catalog_batches(
            client,
            account,
            categories_by_provider,
            relations,
            content_type="series",
            report=report,
        ):
            total_chunks += 1
            total_series += len(chunk)
            logger.info(
                "Processing Stalker series chunk %s (%s series)",
                total_chunks,
                len(chunk),
            )
            process_series_batch(
                account,
                chunk,
                categories_by_provider,
                relations,
                scan_start_time,
                seen_series_keys=seen_series_keys,
            )
            stalker_series_relation_ids.update(
                str(extract_stalker_relation_id(item) or "").strip()
                for item in chunk
                if extract_stalker_relation_id(item)
            )

        logger.info(
            "Completed processing all %s Stalker series in %s chunks",
            total_series,
            total_chunks,
        )
        refresh_stalker_series_catalog_relations(
            account,
            stalker_series_relation_ids,
            progress_callback=progress_callback,
        )
        return report
    else:
        # Get all series in a single API call
        logger.info("Fetching all series from provider...")
        all_series_data = client.get_series()  # No category_id = get all series

    # Process series in chunks using the simple approach
    chunk_size = 1000
    total_series = len(all_series_data)
    total_chunks = (total_series + chunk_size - 1) // chunk_size if total_series > 0 else 0

    for i in range(0, total_series, chunk_size):
        chunk = all_series_data[i:i + chunk_size]
        chunk_num = (i // chunk_size) + 1

        logger.info(f"Processing series chunk {chunk_num}/{total_chunks} ({len(chunk)} series)")
        process_series_batch(
            account,
            chunk,
            categories_by_provider,
            relations,
            scan_start_time,
            seen_series_keys=seen_series_keys,
        )

    del all_series_data
    logger.info(f"Completed processing all {total_series} series in {total_chunks} chunks")
    return StalkerCatalogFetchReport()


def raise_if_every_stalker_category_failed(*reports):
    """Fail the refresh only when no requested category could be fetched."""
    requested = sum(report.requested_count for report in reports)
    failed = sum(len(report.failed_provider_category_ids) for report in reports)
    if requested and failed >= requested:
        errors = [report.last_error for report in reports if report.last_error]
        raise errors[-1]


def build_stalker_failed_category_filter(report, categories_by_provider):
    """Match relations that belong to a category whose fetch failed.

    Matches the current category row and the provider category id saved on
    each item, so content survives even when a renamed provider category
    moved to a new VODCategory row during this refresh.
    """
    provider_ids = sorted(report.failed_provider_category_ids)
    if not provider_ids:
        return None
    if STALKER_ALL_CATEGORIES in provider_ids:
        # The unfiltered catalog failed, so no relation of this type was seen.
        return Q()
    category_ids = [
        categories_by_provider[provider_id].id
        for provider_id in provider_ids
        if provider_id in categories_by_provider
    ]
    return Q(category_id__in=category_ids) | Q(
        custom_properties__basic_data___requested_category_id__in=provider_ids
    )


def get_stalker_failed_category_names(report, categories_by_provider):
    return [
        getattr(categories_by_provider.get(provider_id), "name", None) or provider_id
        for provider_id in report.failed_provider_category_ids
    ]


def batch_create_categories(categories_data, category_type, account):
    """Create categories in batch and return a mapping"""
    normalized_categories = normalize_category_batch(
        categories_data,
        category_type,
        account.account_type,
    )
    category_names = list(normalized_categories.keys())

    # Get existing categories
    logger.debug(f"Starting VOD {category_type} category refresh")
    existing_categories = {
        cat.name: cat for cat in VODCategory.objects.filter(
            name__in=category_names,
            category_type=category_type
        )
    }

    logger.debug(f"Found {len(existing_categories)} existing categories")

    # Check if we should auto-enable new categories based on account settings
    account_custom_props = account.custom_properties or {}
    if category_type == 'movie':
        auto_enable_new = account_custom_props.get("auto_enable_new_groups_vod", True)
    else:  # series
        auto_enable_new = account_custom_props.get("auto_enable_new_groups_series", True)

    existing_relations = {
        rel.category.name: rel
        for rel in M3UVODCategoryRelation.objects.filter(
            m3u_account=account,
            category__category_type=category_type,
        ).select_related("category")
    }

    # Create missing categories in batch
    new_categories = []

    for name in category_names:
        if name not in existing_categories:
            # Always create new categories
            new_categories.append(VODCategory(name=name, category_type=category_type))

    logger.debug(f"{len(new_categories)} new categories found")

    if new_categories:
        logger.debug("Creating new categories...")
        created_categories = list(VODCategory.bulk_create_and_fetch(new_categories, ignore_conflicts=True))

        # Convert to dictionary for easy lookup
        newly_created = {cat.name: cat for cat in created_categories}
        existing_categories.update(newly_created)

    relations_to_upsert = []
    for name, metadata in normalized_categories.items():
        category = existing_categories[name]
        existing_relation = existing_relations.get(name)
        relation_custom_properties = dict(existing_relation.custom_properties or {}) if existing_relation else {}
        relation_custom_properties.update(metadata["relation_custom_properties"])

        if not existing_relation and not auto_enable_new:
            logger.info(
                f"New {category_type} category '{category.name}' created but DISABLED - "
                f"auto_enable_new_groups is disabled for account {account.id}"
            )

        relations_to_upsert.append(
            M3UVODCategoryRelation(
                category=category,
                m3u_account=account,
                custom_properties=relation_custom_properties,
                enabled=existing_relation.enabled if existing_relation else auto_enable_new,
            )
        )

    # Create missing relations and refresh provider metadata on existing ones
    logger.debug("Updating category account relations...")
    if relations_to_upsert:
        M3UVODCategoryRelation.objects.bulk_create(
            relations_to_upsert,
            update_conflicts=True,
            unique_fields=["m3u_account", "category"],
            update_fields=["custom_properties"],
        )

    # Delete orphaned category relationships (categories no longer in the M3U source)
    # Exclude "Uncategorized" from cleanup as it's a special category we manage
    current_category_ids = set(existing_categories[name].id for name in category_names)
    existing_relations = M3UVODCategoryRelation.objects.filter(
        m3u_account=account,
        category__category_type=category_type
    ).select_related('category')

    relations_to_delete = [
        rel for rel in existing_relations
        if rel.category_id not in current_category_ids and rel.category.name != "Uncategorized"
    ]

    if relations_to_delete:
        M3UVODCategoryRelation.objects.filter(
            id__in=[rel.id for rel in relations_to_delete]
        ).delete()
        logger.info(f"Deleted {len(relations_to_delete)} orphaned {category_type} category relationships for account {account.id}: {[rel.category.name for rel in relations_to_delete]}")

        # Check if any of the deleted relationships left categories with no remaining associations
        orphaned_category_ids = []
        for rel in relations_to_delete:
            category = rel.category

            # Check if this category has any remaining M3U account relationships
            remaining_relationships = M3UVODCategoryRelation.objects.filter(
                category=category
            ).exists()

            # If no relationships remain, it's safe to delete the category
            if not remaining_relationships:
                orphaned_category_ids.append(category.id)
                logger.debug(f"Category '{category.name}' has no remaining associations and will be deleted")

        # Delete orphaned categories
        if orphaned_category_ids:
            VODCategory.objects.filter(id__in=orphaned_category_ids).delete()
            logger.info(f"Deleted {len(orphaned_category_ids)} orphaned {category_type} categories with no remaining associations")

    # 🔑 Fetch all relations for this account, for all categories
    # relations = { rel.id: rel for rel in M3UVODCategoryRelation.objects
    #     .filter(category__in=existing_categories.values(), m3u_account=account)
    #     .select_related("category", "m3u_account")
    # }

    # Attach relations to category objects
    # for rel in relations:
    #     existing_categories[rel.category.name]['relation'] = {
    #         "relation_id": rel.id,
    #         "category_id": rel.category_id,
    #         "account_id": rel.m3u_account_id,
    #     }


    return existing_categories


def extract_category_name(category_data, account_type):
    if account_type == M3UAccount.Types.STALKER:
        return (
            category_data.get("title")
            or category_data.get("name")
            or category_data.get("alias")
            or "Unknown"
        )

    return (
        category_data.get("category_name")
        or category_data.get("name")
        or category_data.get("title")
        or "Unknown"
    )


def extract_provider_category_id(category_data, account_type):
    if account_type == M3UAccount.Types.STALKER:
        provider_id = category_data.get("id") or category_data.get("category_id")
    else:
        provider_id = category_data.get("category_id") or category_data.get("id")

    if provider_id in (None, ""):
        return None

    return str(provider_id)


def normalize_category_batch(categories_data, category_type, account_type):
    normalized = {}

    for category_data in categories_data:
        name = str(extract_category_name(category_data, account_type)).strip() or "Unknown"
        relation_custom_properties = {}

        if account_type == M3UAccount.Types.STALKER:
            provider_id = extract_provider_category_id(category_data, account_type)
            relation_custom_properties["stalker_category_type"] = category_type
            if provider_id:
                relation_custom_properties["stalker_category_id"] = provider_id

        normalized[name] = {
            "relation_custom_properties": relation_custom_properties,
        }

    return normalized


def extract_display_name(item, fallback="Unknown"):
    if not isinstance(item, dict):
        return fallback

    for key in ("name", "title"):
        value = item.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text

    return fallback


def extract_stalker_relation_id(item):
    if not isinstance(item, dict):
        return None

    for key in ("_stalker_relation_id", "id", "movie_id", "series_id"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)

    return None


def extract_stalker_season_relation_id(item):
    if not isinstance(item, dict):
        return None

    for key in ("_stalker_relation_id", "id", "season_id", "movie_id"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)

    return None


def extract_stalker_episode_relation_id(item):
    if not isinstance(item, dict):
        return None

    for key in ("_stalker_relation_id", "id", "episode_id"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)

    return None


def extract_stalker_category_context_id(item):
    if not isinstance(item, dict):
        return None

    for key in ("category_id", "_requested_category_id", "_provider_category_id"):
        value = item.get(key)
        if value not in (None, ""):
            return str(value)

    return None


def extract_stalker_logo_url(item):
    if not isinstance(item, dict):
        return ""

    for key in ("screenshot_uri", "cover", "logo", "stream_icon"):
        value = extract_string_from_array_or_string(item.get(key))
        if value:
            return value

    return ""


def get_stalker_vod_portal_url(client, account):
    portal_url = getattr(client, "vod_portal_url", None)
    if portal_url:
        return portal_url

    account_properties = dict(getattr(account, "custom_properties", None) or {})
    portal_url = (
        str(account_properties.get("stalker_vod_portal_url") or "").strip()
        or str(account_properties.get("stalker_portal_url") or "").strip()
    )
    if portal_url:
        client.vod_portal_url = portal_url
        return portal_url

    if str(account.server_url or "").rstrip("/").endswith(("/server/load.php", "/portal.php")):
        client.vod_portal_url = account.server_url
        return account.server_url

    discovery = client.discover_vod_categories()
    client.vod_portal_url = discovery.normalized_portal_url
    persist_stalker_runtime_state(
        account,
        client,
        portal_url=discovery.normalized_portal_url,
    )
    return discovery.normalized_portal_url


def persist_stalker_runtime_state(account, client, portal_url=None):
    updated_props = dict(account.custom_properties or {})
    changed = False

    normalized_portal_url = str(portal_url or "").strip()
    if (
        normalized_portal_url
        and updated_props.get("stalker_vod_portal_url") != normalized_portal_url
    ):
        updated_props["stalker_vod_portal_url"] = normalized_portal_url
        changed = True

    if getattr(client, "token", None) and updated_props.get("token") != client.token:
        updated_props["token"] = client.token
        changed = True

    if (
        getattr(client, "last_auth_mode", None)
        and updated_props.get("stalker_auth_mode") != client.last_auth_mode
    ):
        updated_props["stalker_auth_mode"] = client.last_auth_mode
        changed = True

    if changed:
        account.custom_properties = updated_props
        account.save(update_fields=["custom_properties"])


def build_stalker_page_signature(items, relation_id_extractor=extract_stalker_relation_id):
    if not isinstance(items, list):
        return ()

    return tuple(
        (
            relation_id_extractor(item) or "",
            extract_display_name(item, ""),
        )
        for item in items
        if isinstance(item, dict)
    )


def get_stalker_category_requests(categories_by_provider, relations=None):
    provider_category_ids = []
    has_provider_categories = False

    for category_id, category in categories_by_provider.items():
        if category_id == "__uncategorized__":
            continue

        has_provider_categories = True
        if relations is not None and category is not None:
            relation = relations.get(category.id)
            if relation is not None and not relation.enabled:
                continue

        provider_category_ids.append(str(category_id))

    concrete_category_ids = [
        category_id for category_id in provider_category_ids if category_id != "*"
    ]

    # Some portals expose an "All" pseudo-category using "*", but it can omit
    # rows that only appear in the concrete category buckets. Prefer the
    # concrete category IDs whenever they exist so category imports stay
    # complete.
    if concrete_category_ids:
        return concrete_category_ids

    if "*" in provider_category_ids:
        return ["*"]

    if not provider_category_ids:
        if has_provider_categories:
            return []
        return [None]

    return provider_category_ids


def get_stalker_catalog_worker_count(account, request_count, client):
    if request_count <= 1:
        return 1

    if not supports_parallel_stalker_catalog(client):
        return 1

    configured_workers = (
        (account.custom_properties or {}).get("stalker_vod_catalog_workers")
        or DEFAULT_STALKER_CATALOG_WORKERS
    )
    try:
        configured_workers = int(configured_workers)
    except (TypeError, ValueError):
        configured_workers = DEFAULT_STALKER_CATALOG_WORKERS

    return max(1, min(configured_workers, request_count))


def get_stalker_catalog_page_worker_count(account, client):
    if not supports_parallel_stalker_catalog(client):
        return 1

    configured_workers = (
        (account.custom_properties or {}).get("stalker_vod_catalog_page_workers")
        or DEFAULT_STALKER_CATALOG_PAGE_WORKERS
    )
    try:
        configured_workers = int(configured_workers)
    except (TypeError, ValueError):
        configured_workers = DEFAULT_STALKER_CATALOG_PAGE_WORKERS

    return max(1, min(configured_workers, 8))


def clone_stalker_catalog_client(client, account):
    if callable(getattr(type(client), "clone_for_parallel_catalog", None)):
        cloned_client = client.clone_for_parallel_catalog()
    elif isinstance(client, StalkerClient):
        custom_properties = dict(account.custom_properties or {})
        if getattr(client, "token", None):
            custom_properties["token"] = client.token
        cloned_client = StalkerClient(
            server_url=account.server_url,
            mac=(account.custom_properties or {}).get("mac", ""),
            username=account.username or "",
            password=account.password or "",
            user_agent=getattr(account.user_agent, "user_agent", None),
            custom_properties=custom_properties,
            timeout=getattr(client, "timeout", 15),
        )
    else:
        return client

    vod_portal_url = getattr(client, "vod_portal_url", None)
    if vod_portal_url:
        cloned_client.vod_portal_url = vod_portal_url
    return cloned_client


def reauthenticate_stalker_catalog_client(client, worker_client, portal_url, stale_token):
    """Get a fresh portal token after an auth failure and share it with ``client``.

    Parallel workers can hit the same expired token at once. Only the first
    one re-authenticates, and the others reuse the token it published.
    """
    prepare_session = getattr(worker_client, "prepare_authenticated_session", None)
    if not callable(prepare_session):
        return

    with _stalker_catalog_auth_lock:
        if getattr(client, "token", None) != stale_token:
            return
        prepare_session(portal_url, force=True)
        if worker_client is not client:
            client.token = worker_client.token


def fetch_stalker_catalog_page_with_retry(client, account, portal_url, fetch, context_label):
    """Run one Stalker catalog request, retrying transient portal failures.

    Long scans can outlive the portal token, so an auth failure gets a new
    token before the next attempt instead of failing the whole refresh.
    """
    attempts = len(STALKER_CATALOG_RETRY_DELAYS) + 1
    for attempt in range(1, attempts + 1):
        stale_token = getattr(client, "token", None)
        worker_client = clone_stalker_catalog_client(client, account)
        try:
            return fetch(worker_client)
        except StalkerError as exc:
            if attempt == attempts:
                raise
            logger.warning(
                "Stalker %s failed (attempt %s/%s), retrying: %s",
                context_label,
                attempt,
                attempts,
                exc,
            )
            time.sleep(STALKER_CATALOG_RETRY_DELAYS[attempt - 1])
            if isinstance(exc, StalkerRecoverableError):
                try:
                    reauthenticate_stalker_catalog_client(
                        client, worker_client, portal_url, stale_token,
                    )
                except StalkerError as auth_exc:
                    logger.warning(
                        "Stalker re-authentication failed for %s: %s",
                        context_label,
                        auth_exc,
                    )


def fetch_stalker_category_page(
    client,
    account,
    portal_url,
    requested_category_id,
    content_type,
    page,
):
    def fetch(worker_client):
        fetch_page = (
            worker_client.get_vod_movies
            if content_type == "movie"
            else worker_client.get_vod_series
        )
        return fetch_page(portal_url, category_id=requested_category_id, page=page)

    return fetch_stalker_catalog_page_with_retry(
        client,
        account,
        portal_url,
        fetch,
        f"{content_type} category {requested_category_id} page {page}",
    )


def fetch_stalker_series_season_page(client, account, portal_url, external_series_id, page):
    return fetch_stalker_catalog_page_with_retry(
        client,
        account,
        portal_url,
        lambda worker_client: worker_client.get_series_seasons(
            portal_url,
            external_series_id,
            page=page,
        ),
        f"series {external_series_id} seasons page {page}",
    )


def fetch_stalker_series_episode_page(
    client,
    account,
    portal_url,
    external_series_id,
    season_query_id,
    page,
):
    return fetch_stalker_catalog_page_with_retry(
        client,
        account,
        portal_url,
        lambda worker_client: worker_client.get_series_episodes(
            portal_url,
            external_series_id,
            season_query_id,
            page=page,
        ),
        f"series {external_series_id} season {season_query_id} episodes page {page}",
    )


def iter_stalker_category_batches(
    client,
    account,
    portal_url,
    requested_category_id,
    content_type,
):
    previous_signature = None
    seen_relation_ids = set()
    page_workers = get_stalker_catalog_page_worker_count(account, client)
    next_page = 1
    stop_pagination = False

    while next_page <= 500 and not stop_pagination:
        page_numbers = list(
            range(next_page, min(next_page + page_workers, 501))
        )
        page_results = {}

        if len(page_numbers) == 1:
            page = page_numbers[0]
            page_results[page] = fetch_stalker_category_page(
                client,
                account,
                portal_url,
                requested_category_id,
                content_type,
                page,
            )
        else:
            with ThreadPoolExecutor(max_workers=len(page_numbers)) as executor:
                future_to_page = {
                    executor.submit(
                        fetch_stalker_category_page,
                        client,
                        account,
                        portal_url,
                        requested_category_id,
                        content_type,
                        page,
                    ): page
                    for page in page_numbers
                }
                for future in as_completed(future_to_page):
                    page_results[future_to_page[future]] = future.result()

        for page in page_numbers:
            items = page_results.get(page, [])
            if not items:
                stop_pagination = True
                break

            page_signature = build_stalker_page_signature(items)
            if page > 1 and page_signature and page_signature == previous_signature:
                logger.warning(
                    "Stopping Stalker %s pagination for category %s at page %s because the provider repeated the previous page",
                    content_type,
                    requested_category_id,
                    page,
                )
                stop_pagination = True
                break

            previous_signature = page_signature
            page_batch = []

            for item in items:
                if not isinstance(item, dict):
                    continue

                normalized_item = dict(item)
                if requested_category_id not in (None, ""):
                    normalized_item.setdefault(
                        "_requested_category_id",
                        str(requested_category_id),
                    )

                relation_id = extract_stalker_relation_id(normalized_item)
                if not relation_id:
                    logger.debug(
                        "Skipping Stalker %s item without a stable relation id: %s",
                        content_type,
                        normalized_item,
                    )
                    continue

                if relation_id in seen_relation_ids:
                    continue

                normalized_item["_stalker_relation_id"] = relation_id
                seen_relation_ids.add(relation_id)
                page_batch.append(normalized_item)

            if not page_batch:
                logger.debug(
                    "Stopping Stalker %s pagination for category %s at page %s because no new items were discovered",
                    content_type,
                    requested_category_id,
                    page,
                )
                stop_pagination = True
                break

            yield page_batch

        next_page = page_numbers[-1] + 1


def produce_stalker_category_batches(
    client,
    account,
    portal_url,
    requested_category_id,
    content_type,
    out_queue,
):
    try:
        for batch in iter_stalker_category_batches(
            client,
            account,
            portal_url,
            requested_category_id,
            content_type,
        ):
            out_queue.put(("batch", batch))
    except Exception as exc:
        out_queue.put(("error", exc))
    finally:
        out_queue.put(("done", None))


def iter_stalker_catalog_batches(
    client,
    account,
    categories_by_provider,
    relations,
    content_type,
    report=None,
):
    """Yield deduplicated Stalker catalog pages across the enabled categories.

    A category that still fails after page retries is skipped and recorded in
    ``report``, so the caller can keep that category's existing content and
    decide whether the refresh failed as a whole.
    """
    if report is None:
        report = StalkerCatalogFetchReport()
    portal_url = get_stalker_vod_portal_url(client, account)
    provider_category_ids = get_stalker_category_requests(
        categories_by_provider,
        relations=relations,
    )
    seen_relation_ids = set()
    report.requested_count = len(provider_category_ids)

    logger.info(
        "Fetching Stalker %s across %s category contexts",
        content_type,
        len(provider_category_ids),
    )

    if not provider_category_ids:
        logger.info(
            "Skipping Stalker %s fetch because no VOD categories are enabled for account %s",
            content_type,
            account.id,
        )
        return

    max_workers = get_stalker_catalog_worker_count(
        account,
        len(provider_category_ids),
        client,
    )
    logger.info(
        "Using %s worker(s) for Stalker %s catalog fetch",
        max_workers,
        content_type,
    )

    def record_category_failure(requested_category_id, exc):
        report.last_error = exc
        report.failed_provider_category_ids.add(
            STALKER_ALL_CATEGORIES
            if requested_category_id in (None, "", STALKER_ALL_CATEGORIES)
            else str(requested_category_id)
        )
        logger.error(
            "Stalker %s fetch failed for category %s on account %s; keeping its existing content: %s",
            content_type,
            requested_category_id,
            account.id,
            exc,
        )

    def dedupe_batch(raw_batch):
        page_batch = []
        for item in raw_batch:
            relation_id = item.get("_stalker_relation_id") or extract_stalker_relation_id(item)
            if not relation_id or relation_id in seen_relation_ids:
                continue

            item["_stalker_relation_id"] = relation_id
            seen_relation_ids.add(relation_id)
            page_batch.append(item)
        return page_batch

    if max_workers == 1:
        for requested_category_id in provider_category_ids:
            try:
                for raw_batch in iter_stalker_category_batches(
                    client,
                    account,
                    portal_url,
                    requested_category_id,
                    content_type,
                ):
                    page_batch = dedupe_batch(raw_batch)
                    if page_batch:
                        yield page_batch
            except Exception as exc:
                record_category_failure(requested_category_id, exc)
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            queues = []
            for requested_category_id in provider_category_ids:
                out_queue = Queue(maxsize=4)
                queues.append((requested_category_id, out_queue))
                executor.submit(
                    produce_stalker_category_batches,
                    client,
                    account,
                    portal_url,
                    requested_category_id,
                    content_type,
                    out_queue,
                )

            for requested_category_id, out_queue in queues:
                while True:
                    event_type, payload = out_queue.get()
                    if event_type == "batch":
                        page_batch = dedupe_batch(payload)
                        if page_batch:
                            yield page_batch
                    elif event_type == "error":
                        record_category_failure(requested_category_id, payload)
                    elif event_type == "done":
                        break


def collect_stalker_paginated_items(
    fetch_page,
    relation_id_extractor,
    content_label,
    context_label,
    page_workers=1,
):
    previous_signature = None
    seen_relation_ids = set()
    collected_items = []

    next_page = 1
    stop_pagination = False

    while next_page <= 500 and not stop_pagination:
        page_numbers = list(range(next_page, min(next_page + max(1, page_workers), 501)))
        page_results = {}

        if len(page_numbers) == 1:
            page = page_numbers[0]
            page_results[page] = fetch_page(page)
        else:
            with ThreadPoolExecutor(max_workers=len(page_numbers)) as executor:
                future_to_page = {
                    executor.submit(fetch_page, page): page
                    for page in page_numbers
                }
                for future in as_completed(future_to_page):
                    page_results[future_to_page[future]] = future.result()

        for page in page_numbers:
            items = page_results.get(page, [])
            if not items:
                stop_pagination = True
                break

            page_signature = build_stalker_page_signature(
                items,
                relation_id_extractor=relation_id_extractor,
            )
            if page > 1 and page_signature and page_signature == previous_signature:
                logger.warning(
                    "Stopping Stalker %s pagination for %s at page %s because the provider repeated the previous page",
                    content_label,
                    context_label,
                    page,
                )
                stop_pagination = True
                break

            previous_signature = page_signature
            page_added = 0

            for item in items:
                if not isinstance(item, dict):
                    continue

                relation_id = relation_id_extractor(item)
                if not relation_id:
                    logger.debug(
                        "Skipping Stalker %s item without a stable relation id: %s",
                        content_label,
                        item,
                    )
                    continue

                if relation_id in seen_relation_ids:
                    continue

                normalized_item = dict(item)
                normalized_item["_stalker_relation_id"] = relation_id
                seen_relation_ids.add(relation_id)
                collected_items.append(normalized_item)
                page_added += 1

            if not page_added:
                logger.debug(
                    "Stopping Stalker %s pagination for %s at page %s because no new items were discovered",
                    content_label,
                    context_label,
                    page,
                )
                stop_pagination = True
                break

        next_page = page_numbers[-1] + 1

    return collected_items


def should_parallelize_stalker_series_detail(client):
    for attr_name in ("get_series_seasons", "get_series_episodes"):
        attr = getattr(type(client), attr_name, None)
        if attr is not None and type(attr).__module__ == "unittest.mock":
            return False
    return supports_parallel_stalker_catalog(client)


def get_stalker_series_detail_worker_count(account, request_count, client):
    if request_count <= 1 or not should_parallelize_stalker_series_detail(client):
        return 1

    configured_workers = (
        (account.custom_properties or {}).get("stalker_series_detail_workers")
        or (account.custom_properties or {}).get("stalker_vod_catalog_workers")
        or DEFAULT_STALKER_CATALOG_WORKERS
    )
    try:
        configured_workers = int(configured_workers)
    except (TypeError, ValueError):
        configured_workers = DEFAULT_STALKER_CATALOG_WORKERS

    return max(1, min(configured_workers, request_count))


def get_stalker_series_detail_page_worker_count(account, client):
    if not should_parallelize_stalker_series_detail(client):
        return 1

    configured_workers = (
        (account.custom_properties or {}).get("stalker_series_detail_page_workers")
        or (account.custom_properties or {}).get("stalker_vod_catalog_page_workers")
        or DEFAULT_STALKER_CATALOG_PAGE_WORKERS
    )
    try:
        configured_workers = int(configured_workers)
    except (TypeError, ValueError):
        configured_workers = DEFAULT_STALKER_CATALOG_PAGE_WORKERS

    return max(1, min(configured_workers, 8))


def build_series_relation_custom_properties(existing_props, series_data):
    relation_custom_properties = dict(existing_props or {})
    relation_custom_properties["basic_data"] = series_data
    relation_custom_properties["detailed_fetched"] = bool(
        relation_custom_properties.get("detailed_fetched")
    )
    relation_custom_properties["episodes_fetched"] = bool(
        relation_custom_properties.get("episodes_fetched")
    )
    return relation_custom_properties


def refresh_stalker_series_catalog_relations(
    account,
    external_series_ids,
    progress_callback=None,
):
    relation_ids = {
        str(series_id).strip()
        for series_id in (external_series_ids or [])
        if str(series_id).strip()
    }
    if not relation_ids:
        return

    relations = get_enabled_series_relations_queryset(
        M3USeriesRelation.objects.filter(
            m3u_account=account,
            external_series_id__in=relation_ids,
        )
    ).select_related("series")

    relation_count = relations.count()
    logger.info(
        "Refreshing Stalker seasons and episodes for %s catalog series on account %s",
        relation_count,
        account.id,
    )

    for completed_count, relation in enumerate(relations.iterator(), start=1):
        try:
            refresh_series_episodes(
                account,
                relation.series,
                relation.external_series_id,
                only_missing=True,
            )
        except Exception:
            logger.exception(
                "Error refreshing Stalker seasons/episodes during catalog refresh for relation %s",
                relation.id,
            )
        finally:
            if progress_callback:
                progress_callback(completed_count, relation_count)


def get_enabled_series_relations_queryset(queryset):
    """Drop relations whose category the account has explicitly disabled.

    A category with no ``M3UVODCategoryRelation`` row yet (or no category at
    all) counts as enabled, so content stays visible until a user turns it off.
    """
    disabled_category_relations = M3UVODCategoryRelation.objects.filter(
        m3u_account_id=OuterRef("m3u_account_id"),
        category_id=OuterRef("category_id"),
        enabled=False,
    )

    return queryset.annotate(
        category_disabled=Exists(disabled_category_relations)
    ).filter(category_disabled=False)



@shared_task
def process_movie_batch(account, batch, categories, relations, scan_start_time=None, seen_movie_keys=None):
    """Process a batch of movies using simple bulk operations like M3U processing"""
    logger.info(f"Processing movie batch of {len(batch)} movies for account {account.name}")

    movies_to_create = []
    movies_to_update = []
    relations_to_create = []
    relations_to_update = []
    movie_entries = {}
    relation_entries = []
    seen_stream_ids = set()
    is_stalker = account.account_type == M3UAccount.Types.STALKER
    if seen_movie_keys is None:
        seen_movie_keys = set()

    # Prefetch existing relations before computing identity so an already-known
    # stream stays pinned to its current movie for this batch. A category
    # re-tag only takes effect via reconcile_movie_language_identity(), run
    # once after the full account refresh, not mid-batch.
    batch_stream_ids = [
        extract_stalker_relation_id(movie_data) if is_stalker else str(movie_data.get('stream_id'))
        for movie_data in batch
    ]
    existing_relations = {
        rel.stream_id: rel for rel in M3UMovieRelation.objects.filter(
            m3u_account=account,
            stream_id__in=batch_stream_ids
        ).select_related('movie')
    }

    # Process each movie in the batch
    for movie_data in batch:
        try:
            if is_stalker:
                stream_id = extract_stalker_relation_id(movie_data)
                name = truncate_with_warning(
                    extract_display_name(movie_data),
                    max_length=Movie._meta.get_field('name').max_length,
                    label='Movie name',
                )
            else:
                stream_id = str(movie_data.get('stream_id'))
                # Skip blank names: Movie.name is NOT NULL, and one null in this
                # atomic batch would roll back every other row. Clamp length before
                # identity keys / bulk_create so one over-long title cannot abort
                # the whole chunk.
                name = truncate_with_warning(
                    str(movie_data.get('name') or '').strip(),
                    max_length=Movie._meta.get_field('name').max_length,
                    label='Movie name',
                )
                if not name:
                    logger.warning(
                        "Skipping movie with blank name (stream_id=%s, account=%s)",
                        stream_id,
                        account.id,
                    )
                    continue

            if not stream_id:
                logger.debug("Skipping movie without a stable relation key: %s", movie_data)
                continue
            if stream_id in seen_stream_ids:
                continue

            # Get category with proper error handling
            category = None

            if is_stalker:
                provider_cat_id = extract_stalker_category_context_id(movie_data)
            else:
                provider_cat_id = str(movie_data.get('category_id', '')) if movie_data.get('category_id') else None
            movie_data['_provider_category_id'] = provider_cat_id
            movie_data['_category_id'] = None

            logger.debug(f"Checking for existing provider category ID {provider_cat_id}")
            if provider_cat_id in categories:
                category = categories[provider_cat_id]
                movie_data['_category_id'] = category.id
                logger.debug(f"Found category {category.name} (ID: {category.id}) for movie {name}")

                relation = relations.get(category.id, None)
                if relation and not relation.enabled:
                    logger.debug("Skipping disabled category")
                    continue
            else:
                # Assign to Uncategorized category if no category_id provided
                logger.debug(f"No category ID provided for movie {name}, assigning to 'Uncategorized'")
                category = categories.get('__uncategorized__')
                if category:
                    movie_data['_category_id'] = category.id
                    # Check if uncategorized is disabled
                    relation = relations.get(category.id, None)
                    if relation and not relation.enabled:
                        logger.debug("Skipping disabled 'Uncategorized' category")
                        continue

            if is_stalker and not movie_data.get("container_extension"):
                movie_data["container_extension"] = extract_stalker_container_extension(
                    movie_data
                )

            # Extract metadata
            title_key = 'name' if movie_data.get('name') else 'title'
            year = extract_year_from_data(movie_data, title_key)
            tmdb_id = movie_data.get('tmdb_id') or movie_data.get('tmdb')
            imdb_id = movie_data.get('imdb_id') or movie_data.get('imdb')

            # Clean empty string IDs and zero values (some providers use 0 to indicate no ID)
            if tmdb_id == '' or tmdb_id == 0 or tmdb_id == '0':
                tmdb_id = None
            if imdb_id == '' or imdb_id == 0 or imdb_id == '0':
                imdb_id = None

            # The category's language is part of movie identity. A stream we
            # already have a relation for stays pinned to its current movie's
            # language for this batch, even if its category was just tagged/
            # retagged - only the reconcile pass moves it.
            existing_relation = existing_relations.get(stream_id)
            if existing_relation is not None:
                language = existing_relation.movie.language
            else:
                language = category_language(relations.get(category.id) if category else None)

            # Create a unique key for this movie (priority: TMDB > IMDB > name+year),
            # scoped to the language like the Movie unique constraints
            if tmdb_id:
                movie_key = ('tmdb', str(tmdb_id), language)
            elif imdb_id:
                movie_key = ('imdb', str(imdb_id), language)
            else:
                movie_key = ('name', name, year, language)

            # Within a single batch, distinct stream_ids for the same movie key
            # still get their own relation, and their list-sync props are
            # merged together (same stream_id coalesces). Across batches/chunks
            # of the same scan, a non-Stalker movie key that was already fully
            # recorded in an earlier batch is skipped entirely. Stalker needs
            # to keep distinct provider relations across the whole scan so the
            # same title can remain visible in multiple categories.
            if (
                not is_stalker
                and movie_key in seen_movie_keys
                and movie_key not in movie_entries
            ):
                continue

            movie_props, logo_url = build_movie_list_props(
                movie_data, name, year, tmdb_id, imdb_id, language,
            )
            if is_stalker:
                stalker_logo_url = extract_stalker_logo_url(movie_data)
                if stalker_logo_url:
                    logo_url = stalker_logo_url

            existing_entry = movie_entries.get(movie_key)
            if existing_entry is None:
                movie_entries[movie_key] = {
                    'props': movie_props,
                    'logo_url': logo_url,  # Keep logo URL for later processing
                }
            else:
                merge_blank_vod_list_props(existing_entry['props'], movie_props)
                if not existing_entry.get('logo_url') and logo_url:
                    existing_entry['logo_url'] = logo_url

            relation_entries.append({
                'movie_key': movie_key,
                'stream_id': stream_id,
                'category': category,
                'movie_data': movie_data,
            })
            seen_stream_ids.add(stream_id)
            if not is_stalker:
                seen_movie_keys.add(movie_key)

        except Exception as e:
            logger.error(f"Error preparing movie {movie_data.get('name', 'Unknown')}: {str(e)}")

    # Collect all logo URLs and create logos in batch
    logo_urls = set()
    logo_url_to_name = {}  # Map logo URLs to movie names
    for data in movie_entries.values():
        logo_url = data.get('logo_url')
        if logo_url and len(logo_url) <= 500:  # Ignore overly long URLs (likely embedded image data)
            logo_urls.add(logo_url)
            # Map this logo URL to the movie name (use first occurrence if multiple movies share same logo)
            if logo_url not in logo_url_to_name:
                movie_name = data['props'].get('name', 'Unknown Movie')
                logo_url_to_name[logo_url] = movie_name

    # Get existing logos
    existing_logos = {
        logo.url: logo for logo in VODLogo.objects.filter(url__in=logo_urls)
    } if logo_urls else {}

    # Create missing logos
    logos_to_create = []
    for logo_url in logo_urls:
        if logo_url not in existing_logos:
            movie_name = logo_url_to_name.get(logo_url, 'Unknown Movie')
            logos_to_create.append(VODLogo(url=logo_url, name=movie_name))

    if logos_to_create:
        try:
            VODLogo.objects.bulk_create(logos_to_create, ignore_conflicts=True)
            # Refresh existing_logos with newly created ones
            new_logo_urls = [logo.url for logo in logos_to_create]
            newly_created = {
                logo.url: logo for logo in VODLogo.objects.filter(url__in=new_logo_urls)
            }
            existing_logos.update(newly_created)
            logger.info(f"Created {len(newly_created)} new VOD logos for movies")
        except Exception as e:
            logger.warning(f"Failed to create VOD logos: {e}")

    # Get existing movies based on our keys
    existing_movies = {}

    # Query by TMDB IDs
    tmdb_ids = {k[1] for k in movie_entries if k[0] == 'tmdb'}
    if tmdb_ids:
        for movie in Movie.objects.filter(tmdb_id__in=tmdb_ids):
            existing_movies[('tmdb', movie.tmdb_id, movie.language)] = movie

    # Query by IMDB IDs
    imdb_ids = {k[1] for k in movie_entries if k[0] == 'imdb'}
    if imdb_ids:
        for movie in Movie.objects.filter(imdb_id__in=imdb_ids):
            existing_movies[('imdb', movie.imdb_id, movie.language)] = movie

    # Query by name+year+language for movies without external IDs
    name_year_keys = _name_year_keys_including_untagged(
        [k[1:] for k in movie_entries if k[0] == 'name']
    )
    for key_tuple, movie in lookup_by_name_year(Movie, name_year_keys).items():
        existing_movies[('name', *key_tuple)] = movie

    # existing_relations was already prefetched above (before movie_entries was
    # built) so per-row identity could pin to it.

    resolved_movies = {}

    # Process each unique movie
    for movie_key, data in movie_entries.items():
        movie_props = data['props']
        logo_url = data.get('logo_url')

        movie = _existing_vod_row(movie_key, existing_movies)
        if movie is not None:
            # Language changes happen in reconcile, not here. A tagged stream
            # that joined an untagged row must not rename that row mid-batch.
            updated = False

            for field, value in movie_props.items():
                if field == 'language':
                    continue
                if field == 'custom_properties':
                    # Merge custom_properties: fill director/actors/release_date
                    # only when empty; apply other non-blank list keys.
                    existing_cp = movie.custom_properties or {}
                    incoming_cp = value or {}
                    merged = dict(existing_cp)
                    for k, v in incoming_cp.items():
                        if k in ('director', 'actors', 'release_date'):
                            if not existing_cp.get(k):
                                merged[k] = v
                        elif not is_blank_vod_value(v):
                            merged[k] = v
                    if merged != existing_cp:
                        movie.custom_properties = merged
                        updated = True
                elif should_apply_provider_list_field(getattr(movie, field), value):
                    setattr(movie, field, value)
                    updated = True

            # Handle logo assignment for existing movies
            logo_updated = False
            if logo_url and len(logo_url) <= 500:
                if logo_url in existing_logos:
                    new_logo = existing_logos[logo_url]
                    if movie.logo_id != new_logo.id:
                        movie._logo_to_update = new_logo
                        logo_updated = True
                elif movie.logo_id:
                    logger.warning(f"Logo URL provided but logo not found in database for movie '{movie.name}', clearing logo reference")
                    movie._logo_to_update = None
                    logo_updated = True
            elif (not logo_url or len(logo_url) > 500) and movie.logo_id:
                # Clear logo if no logo URL provided or URL is too long
                movie._logo_to_update = None
                logo_updated = True

            if updated or logo_updated:
                movies_to_update.append(movie)
        else:
            # Create new movie
            movie = Movie(**movie_props)

            # Assign logo if available
            if logo_url and len(logo_url) <= 500 and logo_url in existing_logos:
                movie.logo = existing_logos[logo_url]

            movies_to_create.append(movie)

        resolved_movies[movie_key] = movie

    for relation_data in relation_entries:
        movie_key = relation_data['movie_key']
        stream_id = relation_data['stream_id']
        category = relation_data['category']
        movie_data = relation_data['movie_data']
        movie = resolved_movies[movie_key]

        # Handle relation
        if stream_id in existing_relations:
            # Update existing relation
            relation = existing_relations[stream_id]
            movie_changed = relation.movie_id != movie.pk
            relation.movie = movie
            relation.category = category
            relation.container_extension = movie_data.get('container_extension', 'mp4')
            # Merge so list sync updates basic_data without dropping detail
            # payloads or detailed_fetched / related flags.
            existing_rel_cp = relation.custom_properties or {}
            relation.custom_properties = {
                **existing_rel_cp,
                'basic_data': movie_data,
            }
            if movie_changed:
                # Re-fetch details for the row this stream now belongs to,
                # e.g. after its category was assigned a language
                relation.custom_properties['detailed_fetched'] = False
            relation.last_seen = scan_start_time or timezone.now()  # Mark as seen during this scan
            relations_to_update.append(relation)
        else:
            # Create new relation
            relation = M3UMovieRelation(
                m3u_account=account,
                movie=movie,
                category=category,
                stream_id=stream_id,
                container_extension=movie_data.get('container_extension', 'mp4'),
                custom_properties={
                    'basic_data': movie_data,
                    'detailed_fetched': False
                },
                last_seen=scan_start_time or timezone.now()  # Mark as seen during this scan
            )
            relations_to_create.append(relation)

    # Execute batch operations
    logger.info(f"Executing batch operations: {len(movies_to_create)} movies to create, {len(movies_to_update)} to update")

    try:
        with transaction.atomic():
            # First, create new movies and get their IDs
            created_movies = {}
            if movies_to_create:
                # Bulk query to check which movies already exist
                tmdb_ids = [str(m.tmdb_id) for m in movies_to_create if m.tmdb_id]
                imdb_ids = [str(m.imdb_id) for m in movies_to_create if m.imdb_id]
                name_year_keys = _name_year_keys_including_untagged(
                    [(m.name, m.year, m.language) for m in movies_to_create if not m.tmdb_id and not m.imdb_id]
                )

                existing_by_tmdb = {(m.tmdb_id, m.language): m for m in Movie.objects.filter(tmdb_id__in=tmdb_ids)} if tmdb_ids else {}
                existing_by_imdb = {(m.imdb_id, m.language): m for m in Movie.objects.filter(imdb_id__in=imdb_ids)} if imdb_ids else {}

                existing_by_name_year = lookup_by_name_year(Movie, name_year_keys)

                # Check each movie against the bulk query results
                movies_actually_created = []
                for movie in movies_to_create:
                    existing = _match_existing_vod_row(
                        movie, existing_by_tmdb, existing_by_imdb, existing_by_name_year
                    )
                    if existing:
                        created_movies[id(movie)] = existing
                    else:
                        movies_actually_created.append(movie)
                        created_movies[id(movie)] = movie

                # Bulk create only movies that don't exist
                if movies_actually_created:
                    Movie.objects.bulk_create(movies_actually_created)

            # Update existing movies
            if movies_to_update:
                # First, update all fields except logo to avoid unsaved related object issues
                Movie.objects.bulk_update(movies_to_update, [
                    'description', 'rating', 'genre', 'year', 'tmdb_id', 'imdb_id',
                    'duration_secs', 'is_adult', 'custom_properties'
                ])

                # Handle logo updates separately to avoid bulk_update issues
                for movie in movies_to_update:
                    if hasattr(movie, '_logo_to_update'):
                        movie.logo = movie._logo_to_update
                        movie.save(update_fields=['logo'])

            # Update relations to reference the correct movie objects (with PKs)
            for relation in relations_to_create:
                if id(relation.movie) in created_movies:
                    relation.movie = created_movies[id(relation.movie)]

            for relation in relations_to_update:
                if id(relation.movie) in created_movies:
                    relation.movie = created_movies[id(relation.movie)]

            # All movies now have PKs, safe to bulk create/update relations
            if relations_to_create:
                M3UMovieRelation.objects.bulk_create(relations_to_create, ignore_conflicts=True)

            if relations_to_update:
                M3UMovieRelation.objects.bulk_update(relations_to_update, [
                    'movie', 'category', 'container_extension', 'custom_properties', 'last_seen'
                ])

        logger.info("Movie batch processing completed successfully!")
        return f"Movie batch processed: {len(movies_to_create)} created, {len(movies_to_update)} updated"

    except Exception as e:
        logger.error(f"Movie batch processing failed: {str(e)}")
        return f"Movie batch processing failed: {str(e)}"


@shared_task
def process_series_batch(account, batch, categories, relations, scan_start_time=None, seen_series_keys=None):
    """Process a batch of series using simple bulk operations like M3U processing"""
    logger.info(f"Processing series batch of {len(batch)} series for account {account.name}")

    series_to_create = []
    series_to_update = []
    relations_to_create = []
    relations_to_update = []
    series_entries = {}
    relation_entries = []
    seen_relation_ids = set()
    is_stalker = account.account_type == M3UAccount.Types.STALKER
    if seen_series_keys is None:
        seen_series_keys = set()

    # Prefetch existing relations before computing identity so an already-known
    # series stays pinned to its current series for this batch. A category
    # re-tag only takes effect via reconcile_series_language_identity(), run
    # once after the full account refresh, not mid-batch.
    batch_series_ids = [
        extract_stalker_relation_id(series_data) if is_stalker else str(series_data.get('series_id'))
        for series_data in batch
    ]
    existing_relations = {
        rel.external_series_id: rel for rel in M3USeriesRelation.objects.filter(
            m3u_account=account,
            external_series_id__in=batch_series_ids
        ).select_related('series')
    }

    # Process each series in the batch
    for series_data in batch:
        try:
            if is_stalker:
                series_id = extract_stalker_relation_id(series_data)
                name = truncate_with_warning(
                    extract_display_name(series_data),
                    max_length=Series._meta.get_field('name').max_length,
                    label='Series name',
                )
            else:
                series_id = str(series_data.get('series_id'))
                # Skip blank names: Series.name is NOT NULL, and one null in this
                # atomic batch would roll back every other row. Clamp length before
                # identity keys / bulk_create so one over-long title cannot abort
                # the whole chunk.
                name = truncate_with_warning(
                    str(series_data.get('name') or '').strip(),
                    max_length=Series._meta.get_field('name').max_length,
                    label='Series name',
                )
                if not name:
                    logger.warning(
                        "Skipping series with blank name (series_id=%s, account=%s)",
                        series_id,
                        account.id,
                    )
                    continue

            if not series_id:
                logger.debug("Skipping series without a stable relation key: %s", series_data)
                continue
            if series_id in seen_relation_ids:
                continue

            # Get category with proper error handling
            category = None

            if is_stalker:
                provider_cat_id = extract_stalker_category_context_id(series_data)
            else:
                provider_cat_id = str(series_data.get('category_id', '')) if series_data.get('category_id') else None
            series_data['_provider_category_id'] = provider_cat_id
            series_data['_category_id'] = None

            if provider_cat_id in categories:
                category = categories[provider_cat_id]
                series_data['_category_id'] = category.id
                logger.debug(f"Found category {category.name} (ID: {category.id}) for series {name}")
                relation = relations.get(category.id, None)

                if relation and not relation.enabled:
                    logger.debug("Skipping disabled category")
                    continue
            else:
                # Assign to Uncategorized category if no category_id provided
                logger.debug(f"No category ID provided for series {name}, assigning to 'Uncategorized'")
                category = categories.get('__uncategorized__')
                if category:
                    series_data['_category_id'] = category.id
                    # Check if uncategorized is disabled
                    relation = relations.get(category.id, None)
                    if relation and not relation.enabled:
                        logger.debug("Skipping disabled 'Uncategorized' category")
                        continue

            # Extract metadata
            title_key = 'name' if series_data.get('name') else 'title'
            year = extract_year_from_data(series_data, title_key)

            tmdb_id = series_data.get('tmdb') or series_data.get('tmdb_id')
            imdb_id = series_data.get('imdb') or series_data.get('imdb_id')

            # Clean empty string IDs and zero values (some providers use 0 to indicate no ID)
            if tmdb_id == '' or tmdb_id == 0 or tmdb_id == '0':
                tmdb_id = None
            if imdb_id == '' or imdb_id == 0 or imdb_id == '0':
                imdb_id = None

            # The category's language is part of series identity. A series we
            # already have a relation for stays pinned to its current series'
            # language for this batch, even if its category was just tagged/
            # retagged - only the reconcile pass moves it.
            existing_relation = existing_relations.get(series_id)
            if existing_relation is not None:
                language = existing_relation.series.language
            else:
                language = category_language(relations.get(category.id) if category else None)

            # Create a unique key for this series (priority: TMDB > IMDB > name+year),
            # scoped to the language like the Series unique constraints
            if tmdb_id:
                series_key = ('tmdb', str(tmdb_id), language)
            elif imdb_id:
                series_key = ('imdb', str(imdb_id), language)
            else:
                series_key = ('name', name, year, language)

            # Within a single batch, distinct series_ids for the same series key
            # still get their own relation, and their list-sync props are
            # merged together (same series_id coalesces). Across batches/chunks
            # of the same scan, a non-Stalker series key that was already fully
            # recorded in an earlier batch is skipped entirely. Stalker needs
            # to keep distinct provider relations across the whole scan so the
            # same title can remain visible in multiple categories.
            if (
                not is_stalker
                and series_key in seen_series_keys
                and series_key not in series_entries
            ):
                continue

            series_props, logo_url = build_series_list_props(
                series_data, name, year, tmdb_id, imdb_id, language,
            )
            if is_stalker:
                stalker_logo_url = extract_stalker_logo_url(series_data)
                if stalker_logo_url:
                    logo_url = stalker_logo_url

            existing_entry = series_entries.get(series_key)
            if existing_entry is None:
                series_entries[series_key] = {
                    'props': series_props,
                    'logo_url': logo_url,  # Keep logo URL for later processing
                }
            else:
                merge_blank_vod_list_props(existing_entry['props'], series_props)
                if not existing_entry.get('logo_url') and logo_url:
                    existing_entry['logo_url'] = logo_url

            relation_entries.append({
                'series_key': series_key,
                'series_id': series_id,
                'category': category,
                'series_data': series_data,
            })
            seen_relation_ids.add(series_id)
            if not is_stalker:
                seen_series_keys.add(series_key)

        except Exception as e:
            logger.error(f"Error preparing series {series_data.get('name', 'Unknown')}: {str(e)}")

    # Collect all logo URLs and create logos in batch
    logo_urls = set()
    logo_url_to_name = {}  # Map logo URLs to series names
    for data in series_entries.values():
        logo_url = data.get('logo_url')
        if logo_url and len(logo_url) <= 500:  # Ignore overly long URLs (likely embedded image data)
            logo_urls.add(logo_url)
            # Map this logo URL to the series name (use first occurrence if multiple series share same logo)
            if logo_url not in logo_url_to_name:
                series_name = data['props'].get('name', 'Unknown Series')
                logo_url_to_name[logo_url] = series_name

    # Get existing logos
    existing_logos = {
        logo.url: logo for logo in VODLogo.objects.filter(url__in=logo_urls)
    } if logo_urls else {}

    # Create missing logos
    logos_to_create = []
    for logo_url in logo_urls:
        if logo_url not in existing_logos:
            series_name = logo_url_to_name.get(logo_url, 'Unknown Series')
            logos_to_create.append(VODLogo(url=logo_url, name=series_name))

    if logos_to_create:
        try:
            VODLogo.objects.bulk_create(logos_to_create, ignore_conflicts=True)
            # Refresh existing_logos with newly created ones
            new_logo_urls = [logo.url for logo in logos_to_create]
            newly_created = {
                logo.url: logo for logo in VODLogo.objects.filter(url__in=new_logo_urls)
            }
            existing_logos.update(newly_created)
            logger.info(f"Created {len(newly_created)} new VOD logos for series")
        except Exception as e:
            logger.warning(f"Failed to create VOD logos: {e}")

    # Get existing series based on our keys - same pattern as movies
    existing_series = {}

    # Query by TMDB IDs
    tmdb_ids = {k[1] for k in series_entries if k[0] == 'tmdb'}
    if tmdb_ids:
        for series in Series.objects.filter(tmdb_id__in=tmdb_ids):
            existing_series[('tmdb', series.tmdb_id, series.language)] = series

    # Query by IMDB IDs
    imdb_ids = {k[1] for k in series_entries if k[0] == 'imdb'}
    if imdb_ids:
        for series in Series.objects.filter(imdb_id__in=imdb_ids):
            existing_series[('imdb', series.imdb_id, series.language)] = series

    # Query by name+year+language for series without external IDs
    name_year_keys = _name_year_keys_including_untagged(
        [k[1:] for k in series_entries if k[0] == 'name']
    )
    for key_tuple, series in lookup_by_name_year(Series, name_year_keys).items():
        existing_series[('name', *key_tuple)] = series

    # existing_relations was already prefetched above (before series_entries was
    # built) so per-row identity could pin to it.

    resolved_series = {}

    # Process each unique series
    for series_key, data in series_entries.items():
        series_props = data['props']
        logo_url = data.get('logo_url')

        series = _existing_vod_row(series_key, existing_series)
        if series is not None:
            # Language changes happen in reconcile, not here. A tagged stream
            # that joined an untagged row must not rename that row mid-batch.
            updated = False

            for field, value in series_props.items():
                if field == 'language':
                    continue
                if field == 'custom_properties':
                    existing_cp = series.custom_properties or {}
                    incoming_cp = value or {}
                    merged = dict(existing_cp)
                    for k, v in incoming_cp.items():
                        if not is_blank_vod_value(v):
                            merged[k] = v
                    if merged != existing_cp:
                        series.custom_properties = merged
                        updated = True
                elif should_apply_provider_list_field(getattr(series, field), value):
                    setattr(series, field, value)
                    updated = True

            # Handle logo assignment for existing series
            logo_updated = False
            if logo_url and len(logo_url) <= 500:
                if logo_url in existing_logos:
                    new_logo = existing_logos[logo_url]
                    if series.logo_id != new_logo.id:
                        series._logo_to_update = new_logo
                        logo_updated = True
                elif series.logo_id:
                    # Logo URL exists but logo creation failed or logo not found
                    # Clear the orphaned logo reference
                    logger.warning(f"Logo URL provided but logo not found in database for series '{series.name}', clearing logo reference")
                    series._logo_to_update = None
                    logo_updated = True
            elif (not logo_url or len(logo_url) > 500) and series.logo_id:
                # Clear logo if no logo URL provided or URL is too long
                series._logo_to_update = None
                logo_updated = True

            if updated or logo_updated:
                series_to_update.append(series)
        else:
            # Create new series
            series = Series(**series_props)

            # Assign logo if available
            if logo_url and len(logo_url) <= 500 and logo_url in existing_logos:
                series.logo = existing_logos[logo_url]

            series_to_create.append(series)

        resolved_series[series_key] = series

    for relation_data in relation_entries:
        series_key = relation_data['series_key']
        series_id = relation_data['series_id']
        category = relation_data['category']
        series_data = relation_data['series_data']
        series = resolved_series[series_key]

        # Handle relation
        if series_id in existing_relations:
            # Update existing relation
            relation = existing_relations[series_id]
            series_changed = relation.series_id != series.pk
            relation.series = series
            relation.category = category
            # Merge so list sync updates basic_data without dropping detail
            # payloads or detailed_fetched / episodes_fetched flags.
            relation.custom_properties = build_series_relation_custom_properties(
                relation.custom_properties,
                series_data,
            )
            if series_changed:
                # Re-fetch details and episodes for the row this series now
                # belongs to, e.g. after its category was assigned a language
                relation.custom_properties['detailed_fetched'] = False
                relation.custom_properties['episodes_fetched'] = False
            relation.last_seen = scan_start_time or timezone.now()  # Mark as seen during this scan
            relations_to_update.append(relation)
        else:
            # Create new relation
            relation = M3USeriesRelation(
                m3u_account=account,
                series=series,
                category=category,
                external_series_id=series_id,
                custom_properties=build_series_relation_custom_properties(
                    None,
                    series_data,
                ),
                last_seen=scan_start_time or timezone.now()  # Mark as seen during this scan
            )
            relations_to_create.append(relation)

    # Execute batch operations
    logger.info(f"Executing batch operations: {len(series_to_create)} series to create, {len(series_to_update)} to update")

    try:
        with transaction.atomic():
            # First, create new series and get their IDs
            created_series = {}
            if series_to_create:
                # Bulk query to check which series already exist
                tmdb_ids = [str(s.tmdb_id) for s in series_to_create if s.tmdb_id]
                imdb_ids = [str(s.imdb_id) for s in series_to_create if s.imdb_id]
                name_year_keys = _name_year_keys_including_untagged(
                    [(s.name, s.year, s.language) for s in series_to_create if not s.tmdb_id and not s.imdb_id]
                )

                existing_by_tmdb = {(s.tmdb_id, s.language): s for s in Series.objects.filter(tmdb_id__in=tmdb_ids)} if tmdb_ids else {}
                existing_by_imdb = {(s.imdb_id, s.language): s for s in Series.objects.filter(imdb_id__in=imdb_ids)} if imdb_ids else {}

                existing_by_name_year = lookup_by_name_year(Series, name_year_keys)

                # Check each series against the bulk query results
                series_actually_created = []
                for series in series_to_create:
                    existing = _match_existing_vod_row(
                        series, existing_by_tmdb, existing_by_imdb, existing_by_name_year
                    )
                    if existing:
                        created_series[id(series)] = existing
                    else:
                        series_actually_created.append(series)
                        created_series[id(series)] = series

                # Bulk create only series that don't exist
                if series_actually_created:
                    Series.objects.bulk_create(series_actually_created)

            # Update existing series
            if series_to_update:
                # First, update all fields except logo to avoid unsaved related object issues
                Series.objects.bulk_update(series_to_update, [
                    'description', 'rating', 'genre', 'year', 'tmdb_id', 'imdb_id',
                    'custom_properties'
                ])

                # Handle logo updates separately to avoid bulk_update issues
                for series in series_to_update:
                    if hasattr(series, '_logo_to_update'):
                        series.logo = series._logo_to_update
                        series.save(update_fields=['logo'])

            # Update relations to reference the correct series objects (with PKs)
            for relation in relations_to_create:
                if id(relation.series) in created_series:
                    relation.series = created_series[id(relation.series)]

            for relation in relations_to_update:
                if id(relation.series) in created_series:
                    relation.series = created_series[id(relation.series)]

            # All series now have PKs, safe to bulk create/update relations
            if relations_to_create:
                M3USeriesRelation.objects.bulk_create(relations_to_create, ignore_conflicts=True)

            if relations_to_update:
                M3USeriesRelation.objects.bulk_update(relations_to_update, [
                    'series', 'category', 'custom_properties', 'last_seen'
                ])

        logger.info("Series batch processing completed successfully!")
        return f"Series batch processed: {len(series_to_create)} created, {len(series_to_update)} updated"

    except Exception as e:
        logger.error(f"Series batch processing failed: {str(e)}")
        return f"Series batch processing failed: {str(e)}"


# Cap for provider duration_secs. Well above normal episodes and features
# (scripted episodes rarely exceed ~3 hours; cinematic outliers top out around
# 15 hours) and still rejects junk that would overflow a DB integer.
MAX_DURATION_SECS = 48 * 60 * 60


def normalize_duration_secs(value):
    """Return positive whole seconds within MAX_DURATION_SECS, else None.

    Zero is missing. Providers send it when they have no runtime.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    # Reject non-integral floats (1.5); allow whole values like 1800.0.
    if isinstance(value, float) and value != seconds:
        return None
    if seconds <= 0 or seconds > MAX_DURATION_SECS:
        return None
    return seconds


def extract_duration_from_data(movie_data):
    """Extract duration in seconds from movie data.

    A usable duration_secs wins. Missing, zero, or unusable duration_secs
    falls through to duration (or Stalker's time/runtime), where a bare
    number is minutes.
    """
    raw_seconds = movie_data.get('duration_secs')
    if raw_seconds is not None and raw_seconds != '':
        seconds = normalize_duration_secs(raw_seconds)
        if seconds is not None:
            return seconds

    raw_duration = next(
        (
            movie_data.get(key)
            for key in ('duration', 'time', 'runtime')
            if movie_data.get(key) not in (None, '')
        ),
        None,
    )
    if raw_duration is None:
        return None

    duration_str = str(raw_duration)
    try:
        if duration_str.isdigit():
            # Assume minutes if just a number. isdigit() accepts some
            # characters int() rejects, so this stays inside the try.
            parsed = int(duration_str) * 60
        else:
            time_parts = duration_str.split(':')
            if len(time_parts) == 3:
                hours, minutes, seconds = map(int, time_parts)
                parsed = (hours * 3600) + (minutes * 60) + seconds
            elif len(time_parts) == 2:
                minutes, seconds = map(int, time_parts)
                parsed = minutes * 60 + seconds
            else:
                return None
    except (ValueError, TypeError, OverflowError, AttributeError):
        return None

    return normalize_duration_secs(parsed)


def normalize_rating(rating_value):
    """Normalize rating value by converting commas to decimals and validating as float"""
    if not rating_value:
        return None

    try:
        # Convert to string for processing
        rating_str = str(rating_value).strip()

        if not rating_str or rating_str == '':
            return None

        # Replace comma with decimal point (European format)
        rating_str = rating_str.replace(',', '.')

        # Try to convert to float
        rating_float = float(rating_str)

        # Return as string to maintain compatibility with existing code
        # but ensure it's a valid numeric format
        return str(rating_float)
    except (ValueError, TypeError, AttributeError):
        # If conversion fails, discard the rating
        logger.debug(f"Invalid rating value discarded: {rating_value}")
        return None


# Helper functions for year and date extraction

def extract_year(date_string):
    """Extract year from date string"""
    if not date_string:
        return None
    try:
        return int(date_string.split('-')[0])
    except (ValueError, IndexError):
        return None


def extract_year_from_title(title):
    """Extract year from movie title if present"""
    if not title:
        return None

    # Pattern for (YYYY) format
    pattern1 = r'\((\d{4})\)'
    # Pattern for - YYYY format
    pattern2 = r'\s-\s(\d{4})'
    # Pattern for YYYY at the end
    pattern3 = r'\s(\d{4})$'

    for pattern in [pattern1, pattern2, pattern3]:
        match = re.search(pattern, title)
        if match:
            year = int(match.group(1))
            # Validate year is reasonable (between 1900 and current year + 5)
            if 1900 <= year <= 2030:
                return year

    return None


def extract_year_from_data(data, title_key='name'):
    """Extract year from various data sources with fallback options"""
    try:
        # First try the year field
        year = data.get('year')
        if year and str(year).strip() and str(year).strip() != '':
            try:
                year_int = int(year)
                if 1900 <= year_int <= 2030:
                    return year_int
            except (ValueError, TypeError):
                pass

        # Try releaseDate or release_date fields
        for date_field in ['releaseDate', 'release_date']:
            date_value = data.get(date_field)
            if date_value and isinstance(date_value, str) and date_value.strip():
                # Extract year from date format like "2011-09-19"
                try:
                    year_str = date_value.split('-')[0].strip()
                    if year_str:
                        year = int(year_str)
                        if 1900 <= year <= 2030:
                            return year
                except (ValueError, IndexError):
                    continue

        # Finally try extracting from title
        title = data.get(title_key, '')
        if title and title.strip():
            return extract_year_from_title(title)

    except Exception:
        # Don't fail processing if year extraction fails
        pass

    return None


def extract_date_from_data(data):
    """Extract date from various data sources with fallback options"""
    try:
        for date_field in ['air_date', 'releasedate', 'release_date']:
            date_value = data.get(date_field)
            if date_value and isinstance(date_value, str) and date_value.strip():
                parsed = parse_date(date_value)
                if parsed:
                    return parsed
    except Exception:
        # Don't fail processing if date extraction fails
        pass
    return None


def parse_date(date_string):
    """Parse date string into a datetime object"""
    if not date_string:
        return None
    try:
        # Try to parse ISO format first
        return datetime.fromisoformat(date_string)
    except ValueError:
        # Fallback to parsing with strptime for common formats
        try:
            return datetime.strptime(date_string, '%Y-%m-%d')
        except ValueError:
            return None  # Return None if parsing fails


def extract_stalker_vod_cmd(item):
    if not isinstance(item, dict):
        return ""

    for key in ("cmd", "stream_cmd", "play_cmd", "play_url"):
        value = item.get(key)
        if value not in (None, ""):
            text = str(value).strip()
            if text:
                return text

    return ""


def extract_stalker_target_container_from_cmd(cmd):
    text = str(cmd or "").strip()
    if not text:
        return ""

    normalized = text
    missing_padding = len(normalized) % 4
    if missing_padding:
        normalized += "=" * (4 - missing_padding)

    try:
        payload = json.loads(base64.b64decode(normalized, validate=False).decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError, UnicodeDecodeError):
        return ""

    if not isinstance(payload, dict):
        return ""

    target_container = payload.get("target_container")
    if isinstance(target_container, list):
        for value in target_container:
            text = str(value or "").strip().lstrip(".").lower()
            if text:
                return text
        return ""

    if isinstance(target_container, str):
        stripped_target_container = target_container.strip()
        if stripped_target_container.startswith("[") and stripped_target_container.endswith("]"):
            try:
                decoded_target_container = json.loads(stripped_target_container)
            except (TypeError, ValueError, json.JSONDecodeError):
                decoded_target_container = None
            if isinstance(decoded_target_container, list):
                for value in decoded_target_container:
                    text = str(value or "").strip().lstrip(".").lower()
                    if text:
                        return text
                return ""

    text = str(target_container or "").strip().lstrip(".").lower()
    return text


def extract_int_from_value(value):
    if value in (None, ""):
        return None

    try:
        return int(str(value).strip())
    except (TypeError, ValueError, AttributeError):
        return None


def extract_number_from_text(text, patterns=None, allow_fallback=True):
    normalized_text = str(text or "").strip()
    if not normalized_text:
        return None

    if patterns:
        for pattern in patterns:
            match = re.search(pattern, normalized_text, re.IGNORECASE)
            if match:
                try:
                    return int(match.group(1))
                except (TypeError, ValueError, IndexError):
                    continue

    if allow_fallback:
        fallback_match = re.search(r"(\d+)", normalized_text)
        if fallback_match:
            try:
                return int(fallback_match.group(1))
            except (TypeError, ValueError, IndexError):
                return None

    return None


def extract_stalker_season_number(item, fallback=None):
    if isinstance(item, dict):
        for key in ("season_number", "season_num", "season", "number"):
            value = extract_int_from_value(item.get(key))
            if value is not None:
                return value

    display_name = extract_display_name(item, "")
    value = extract_number_from_text(
        display_name,
        patterns=[
            r"(?:season|saison|stagione|temporada|series)\s*0*(\d+)",
            r"\bs\s*0*(\d+)\b",
        ],
    )
    if value is not None:
        return value

    if fallback is not None:
        return int(fallback)

    return 0


def extract_stalker_season_query_candidates(item, fallback=None):
    candidates = []

    if isinstance(item, dict):
        for key in ("season_id", "season_number", "season_num", "number", "id", "movie_id"):
            value = item.get(key)
            if value in (None, ""):
                continue
            text = str(value).strip()
            if text and text not in candidates:
                candidates.append(text)

    parsed_number = extract_stalker_season_number(item, fallback=fallback)
    if parsed_number:
        parsed_text = str(parsed_number)
        if parsed_text not in candidates:
            candidates.insert(0, parsed_text)

    return candidates


def extract_stalker_episode_number(item, fallback=None):
    if isinstance(item, dict):
        for key in ("series_number", "episode_number", "episode_num", "number"):
            value = extract_int_from_value(item.get(key))
            if value is not None:
                return value

    display_name = extract_display_name(item, "")
    value = extract_number_from_text(
        display_name,
        patterns=[
            r"(?:episode|episodio|ep)\s*0*(\d+)",
            r"\be\s*0*(\d+)\b",
        ],
        allow_fallback=False,
    )
    if value is not None:
        return value

    if fallback is not None:
        return int(fallback)

    return 0


def extract_stalker_embedded_episode_numbers(item):
    if not isinstance(item, dict):
        return []

    series_list = item.get("series")
    if not isinstance(series_list, list):
        return []

    episode_numbers = []
    for value in series_list:
        parsed = extract_int_from_value(value)
        if parsed is not None and parsed > 0 and parsed not in episode_numbers:
            episode_numbers.append(parsed)

    return episode_numbers


def is_probable_stalker_episode_item(item):
    if not isinstance(item, dict):
        return False

    embedded_episode_numbers = extract_stalker_embedded_episode_numbers(item)
    display_name = extract_display_name(item, "")
    if embedded_episode_numbers and re.search(
        r"(?:season|saison|stagione|temporada|series)\s*0*\d+",
        display_name,
        re.IGNORECASE,
    ):
        return False

    for key in ("episode_id", "series_number", "episode_number"):
        if item.get(key) not in (None, ""):
            return True

    if extract_stalker_vod_cmd(item) and not embedded_episode_numbers:
        return True

    return bool(
        re.search(r"(?:episode|episodio|ep)\s*0*\d+", display_name, re.IGNORECASE)
    )


def looks_like_stalker_season_list(items):
    inspected_items = 0
    season_like_items = 0

    for item in items:
        if not isinstance(item, dict):
            continue

        inspected_items += 1
        if is_probable_stalker_episode_item(item):
            return False

        display_name = extract_display_name(item, "")
        if re.search(
            r"(?:season|saison|stagione|temporada|series)\s*0*\d+",
            display_name,
            re.IGNORECASE,
        ):
            season_like_items += 1

    return inspected_items > 0 and season_like_items == inspected_items


def extract_stalker_container_extension(item):
    if isinstance(item, dict):
        for key in ("container_extension", "extension", "ext"):
            value = item.get(key)
            if value not in (None, ""):
                text = str(value).strip().lstrip(".").lower()
                if text:
                    return text

    cmd = extract_stalker_vod_cmd(item)
    if cmd:
        target_container = extract_stalker_target_container_from_cmd(cmd)
        if target_container:
            return target_container

        target = cmd.split()[-1].split("?", 1)[0].rstrip("/")
        if "." in target:
            extension = target.rsplit(".", 1)[-1].lower()
            if extension and len(extension) <= 5:
                return extension

    return "mp4"


def build_stalker_episode_info(item):
    info = {}
    if not isinstance(item, dict):
        return info

    existing_info = item.get("info")
    if isinstance(existing_info, dict):
        info.update(existing_info)

    for key in (
        "description",
        "plot",
        "overview",
        "rating",
        "air_date",
        "releasedate",
        "release_date",
        "duration_secs",
        "time",
        "runtime",
        "tmdb_id",
        "imdb_id",
        "movie_image",
        "backdrop_path",
        "crew",
        "actors",
        "cast",
        "director",
        "video",
        "audio",
        "bitrate",
    ):
        value = item.get(key)
        if value not in (None, "", []):
            info.setdefault(key, value)

    cmd = extract_stalker_vod_cmd(item)
    if cmd:
        info.setdefault("cmd", cmd)

    return info


def build_stalker_embedded_episode_rows(
    season_item,
    season_relation_id,
    season_number,
    external_series_id,
):
    embedded_episode_numbers = extract_stalker_embedded_episode_numbers(season_item)
    if not embedded_episode_numbers:
        return []

    season_info = build_stalker_episode_info(season_item)
    season_cmd = extract_stalker_vod_cmd(season_item)
    container_extension = extract_stalker_container_extension(season_item)
    normalized_episodes = []

    for episode_number in embedded_episode_numbers:
        episode_id = f"{season_relation_id}:{episode_number}"
        episode_info = dict(season_info)
        episode_info["episode_number"] = episode_number
        episode_info["series_number"] = episode_number
        if season_cmd:
            episode_info["cmd"] = season_cmd

        normalized_episodes.append(
            {
                "id": episode_id,
                "title": f"Episode {episode_number}",
                "episode_num": episode_number,
                "series_number": episode_number,
                "container_extension": container_extension,
                "info": episode_info,
                "cmd": season_cmd,
                "_stalker_series_id": external_series_id,
                "_stalker_season_id": season_relation_id,
                "_stalker_relation_id": episode_id,
                "_stalker_placeholder_episode": True,
            }
        )

    return normalized_episodes


def build_stalker_series_detail_data(series_relation, season_items):
    detail_data = dict((series_relation.custom_properties or {}).get("basic_data") or {})

    for season_item in season_items:
        if not isinstance(season_item, dict):
            continue
        for key, value in season_item.items():
            if key.startswith("_"):
                continue
            if value in (None, "", []):
                continue
            if key not in detail_data or detail_data.get(key) in (None, "", []):
                detail_data[key] = value

    return detail_data


def update_series_from_detail_payload(series, detail_data):
    if not detail_data:
        return

    updated = False

    if should_update_field(series.description, detail_data.get("plot")):
        series.description = extract_string_from_array_or_string(detail_data.get("plot"))
        updated = True
    elif should_update_field(series.description, detail_data.get("description")):
        series.description = extract_string_from_array_or_string(detail_data.get("description"))
        updated = True

    normalized_rating = normalize_rating(detail_data.get("rating"))
    if normalized_rating and (not series.rating or not str(series.rating).strip()):
        series.rating = normalized_rating
        updated = True

    if should_update_field(series.genre, detail_data.get("genre")):
        series.genre = truncate_with_warning(
            extract_string_from_array_or_string(detail_data.get("genre")),
            max_length=Series._meta.get_field("genre").max_length,
            label="Series genre",
        )
        updated = True

    title_key = "title" if detail_data.get("title") else "name"
    year = extract_year_from_data(detail_data, title_key=title_key)
    if year and not series.year:
        series.year = year
        updated = True

    custom_props = dict(series.custom_properties or {})

    for key in (
        "releaseDate",
        "release_date",
        "episode_run_time",
        "status",
        "type",
        "country",
        "language",
        "age",
    ):
        new_value = detail_data.get(key)
        existing_value = custom_props.get(key)
        if new_value not in (None, "", []) and existing_value in (None, "", []):
            custom_props[key] = new_value
            updated = True

    for key in ("cast", "director", "youtube_trailer"):
        if should_update_field(custom_props.get(key), detail_data.get(key)):
            custom_props[key] = extract_string_from_array_or_string(detail_data.get(key))
            updated = True

    backdrop = extract_string_from_array_or_string(detail_data.get("backdrop_path"))
    if backdrop and not extract_string_from_array_or_string(custom_props.get("backdrop_path")):
        custom_props["backdrop_path"] = [backdrop]
        updated = True

    if updated:
        series.custom_properties = clean_custom_properties(custom_props)
        series.save()


def get_stalker_series_refresh_progress(series_relation):
    custom_props = dict(series_relation.custom_properties or {})

    complete_through_season = extract_int_from_value(
        custom_props.get("stalker_complete_through_season")
    )
    if complete_through_season is None or complete_through_season < 0:
        complete_through_season = 0

    latest_complete_episode = extract_int_from_value(
        custom_props.get("stalker_latest_complete_episode")
    )
    if latest_complete_episode is None or latest_complete_episode < 0:
        latest_complete_episode = 0

    return {
        "complete_through_season": complete_through_season,
        "latest_complete_episode": latest_complete_episode,
    }


def build_stalker_series_refresh_progress(season_episode_numbers):
    complete_through_season = 0
    latest_complete_episode = 0

    for season_number in sorted(number for number in season_episode_numbers if number > 0):
        episode_numbers = sorted(set(season_episode_numbers.get(season_number) or []))
        if not episode_numbers:
            break

        expected_episode = 1
        for episode_number in episode_numbers:
            if episode_number != expected_episode:
                return {
                    "complete_through_season": complete_through_season,
                    "latest_complete_episode": latest_complete_episode,
                }
            expected_episode += 1

        complete_through_season = season_number
        latest_complete_episode = episode_numbers[-1]

    return {
        "complete_through_season": complete_through_season,
        "latest_complete_episode": latest_complete_episode,
    }


def refresh_stalker_series_episodes(account, series_relation):
    client = StalkerClient(
        server_url=account.server_url,
        mac=(account.custom_properties or {}).get("mac", ""),
        username=account.username or "",
        password=account.password or "",
        user_agent=getattr(account.user_agent, "user_agent", None),
        custom_properties=account.custom_properties or {},
    )
    portal_url = get_stalker_vod_portal_url(client, account)
    client.prepare_authenticated_session(portal_url)
    client.vod_portal_url = portal_url
    persist_stalker_runtime_state(account, client, portal_url=portal_url)

    page_workers = get_stalker_series_detail_page_worker_count(account, client)

    season_items = collect_stalker_paginated_items(
        lambda page: fetch_stalker_series_season_page(
            client,
            account,
            portal_url,
            series_relation.external_series_id,
            page,
        ),
        relation_id_extractor=extract_stalker_season_relation_id,
        content_label="series seasons",
        context_label=f"series {series_relation.external_series_id}",
        page_workers=page_workers,
    )

    detail_data = build_stalker_series_detail_data(series_relation, season_items)
    episodes_data = {}
    prefer_embedded_episode_rows = {"value": False}
    previous_progress = get_stalker_series_refresh_progress(series_relation)
    season_episode_numbers = {}

    season_jobs = [
        (season_index, season_item)
        for season_index, season_item in enumerate(season_items, start=1)
    ]

    def load_season_episodes(job):
        season_index, season_item = job
        season_id = extract_stalker_season_relation_id(season_item)
        if not season_id:
            return None

        season_number = extract_stalker_season_number(season_item, fallback=season_index)
        if season_number > 0 and season_number <= previous_progress["complete_through_season"]:
            logger.debug(
                "Skipping Stalker season refresh for series %s season %s because it is already marked complete",
                series_relation.external_series_id,
                season_number,
            )
            return None
        embedded_episode_rows = build_stalker_embedded_episode_rows(
            season_item,
            season_relation_id=season_id,
            season_number=season_number,
            external_series_id=series_relation.external_series_id,
        )
        if embedded_episode_rows and prefer_embedded_episode_rows["value"]:
            return season_number, embedded_episode_rows
        season_query_candidates = extract_stalker_season_query_candidates(
            season_item,
            fallback=season_number,
        )
        episode_items = []
        episode_query_season_id = season_id

        for candidate_index, season_query_id in enumerate(season_query_candidates):
            candidate_items = collect_stalker_paginated_items(
                lambda page, season_query_id=season_query_id: fetch_stalker_series_episode_page(
                    client,
                    account,
                    portal_url,
                    series_relation.external_series_id,
                    season_query_id,
                    page,
                ),
                relation_id_extractor=extract_stalker_episode_relation_id,
                content_label="series episodes",
                context_label=(
                    f"series {series_relation.external_series_id} season {season_query_id}"
                ),
                page_workers=page_workers,
            )

            if candidate_items and looks_like_stalker_season_list(candidate_items):
                if embedded_episode_rows:
                    prefer_embedded_episode_rows["value"] = True
                logger.warning(
                    "Stalker series %s season query %s returned season rows instead of episodes; trying the next season id candidate",
                    series_relation.external_series_id,
                    season_query_id,
                )
                continue

            if not candidate_items and candidate_index + 1 < len(season_query_candidates):
                logger.debug(
                    "Stalker series %s season query %s returned no episode rows; trying the next season id candidate",
                    series_relation.external_series_id,
                    season_query_id,
                )
                continue

            episode_items = candidate_items
            episode_query_season_id = season_query_id
            break

        if not episode_items and embedded_episode_rows:
            logger.info(
                "Stalker series %s season %s is using embedded episode numbers from the season payload",
                series_relation.external_series_id,
                season_id,
            )
            episode_items = embedded_episode_rows
            episode_query_season_id = season_id

        normalized_episodes = []
        for episode_index, episode_item in enumerate(episode_items, start=1):
            episode_id = extract_stalker_episode_relation_id(episode_item)
            if not episode_id:
                continue

            episode_number = extract_stalker_episode_number(
                episode_item,
                fallback=episode_index,
            )
            normalized_episode = dict(episode_item)
            normalized_episode["id"] = episode_id
            normalized_episode["title"] = extract_display_name(
                episode_item,
                f"Episode {episode_number}",
            )
            normalized_episode["episode_num"] = episode_number
            normalized_episode["container_extension"] = extract_stalker_container_extension(
                episode_item
            )
            normalized_episode["info"] = build_stalker_episode_info(episode_item)
            normalized_episode["_stalker_series_id"] = series_relation.external_series_id
            normalized_episode["_stalker_season_id"] = episode_query_season_id
            normalized_episode["_stalker_relation_id"] = episode_id
            normalized_episodes.append(normalized_episode)

        return season_number, normalized_episodes

    season_worker_count = get_stalker_series_detail_worker_count(
        account,
        len(season_jobs),
        client,
    )

    if season_worker_count == 1:
        season_results = map(load_season_episodes, season_jobs)
    else:
        with ThreadPoolExecutor(max_workers=season_worker_count) as executor:
            season_results = executor.map(load_season_episodes, season_jobs)

    for season_result in season_results:
        if not season_result:
            continue
        season_number, normalized_episodes = season_result
        episodes_data.setdefault(str(season_number), []).extend(normalized_episodes)
        if season_number > 0:
            season_episode_numbers.setdefault(season_number, [])
            season_episode_numbers[season_number].extend(
                [
                    extract_int_from_value(episode.get("episode_num"))
                    for episode in normalized_episodes
                    if extract_int_from_value(episode.get("episode_num")) is not None
                ]
            )

    refresh_progress = build_stalker_series_refresh_progress(season_episode_numbers)
    refresh_progress["complete_through_season"] = max(
        previous_progress["complete_through_season"],
        refresh_progress["complete_through_season"],
    )
    if (
        refresh_progress["complete_through_season"]
        == previous_progress["complete_through_season"]
    ):
        refresh_progress["latest_complete_episode"] = max(
            previous_progress["latest_complete_episode"],
            refresh_progress["latest_complete_episode"],
        )

    return detail_data, episodes_data, refresh_progress


def build_episode_relation_custom_properties(
    account,
    episode_data,
    season_number,
    series_relation=None,
):
    relation_custom_properties = {
        "info": episode_data,
        "season_number": season_number,
    }

    if account.account_type == M3UAccount.Types.STALKER:
        relation_custom_properties["provider_type"] = "stalker"
        relation_custom_properties["stalker_episode_id"] = extract_stalker_episode_relation_id(
            episode_data
        )

        season_id = episode_data.get("_stalker_season_id")
        if season_id not in (None, ""):
            relation_custom_properties["stalker_season_id"] = str(season_id)

        if series_relation is not None:
            relation_custom_properties["stalker_series_id"] = str(
                series_relation.external_series_id
            )

        cmd = extract_stalker_vod_cmd(episode_data)
        if cmd:
            relation_custom_properties["cmd"] = cmd

    return relation_custom_properties


def stalker_episode_import_looks_stale(series_relation):
    if (
        not series_relation
        or not getattr(series_relation, "m3u_account", None)
        or series_relation.m3u_account.account_type != M3UAccount.Types.STALKER
    ):
        return False

    episode_relations = list(
        M3UEpisodeRelation.objects.filter(series_relation=series_relation)
        .select_related("episode")
        .order_by("id")[:10]
    )

    for relation in episode_relations:
        custom_props = relation.custom_properties or {}
        stalker_episode_id = str(
            custom_props.get("stalker_episode_id") or relation.stream_id or ""
        ).strip()
        stalker_season_id = str(
            custom_props.get("stalker_season_id") or ""
        ).strip()
        episode_name = str(getattr(relation.episode, "name", "") or "").strip().lower()

        if stalker_episode_id and stalker_season_id and stalker_episode_id == stalker_season_id:
            return True

        if episode_name.startswith("season "):
            return True

    return False


def _coerce_provider_info(info_raw):
    """Return a dict from XC info, which is sometimes a one-element list."""
    if isinstance(info_raw, dict):
        return info_raw
    if isinstance(info_raw, list):
        if info_raw and isinstance(info_raw[0], dict):
            return info_raw[0]
        return {}
    return {}


# Episode processing and other advanced features

def refresh_series_episodes(
    account,
    series,
    external_series_id,
    episodes_data=None,
    only_missing=False,
):
    """Refresh episodes for a series - only called on-demand"""
    try:
        # Fetch the series relation once, used both to pass into batch_process_episodes
        # (so episode relations get the FK set) and to update metadata afterwards.
        series_relation = M3USeriesRelation.objects.filter(
            m3u_account=account,
            external_series_id=external_series_id
        ).first()
        if series_relation and not get_enabled_series_relations_queryset(
            M3USeriesRelation.objects.filter(pk=series_relation.pk)
        ).exists():
            logger.info(
                "Skipping episode refresh for series %s on account %s because category %s is disabled",
                series.name,
                account.id,
                series_relation.category_id,
            )
            return
        detail_data = None
        refresh_progress = None
        # None means this call did not ask the provider for series info.
        # False means it did, and the body was missing or not an object.
        # True means the body was an object, even when info itself is blank.
        has_details = None

        if not episodes_data:
            has_details = False
            if account.account_type == M3UAccount.Types.STALKER:
                if not series_relation:
                    raise ValueError(
                        f"Missing Stalker series relation for external_series_id={external_series_id}"
                    )
                detail_data, episodes_data, refresh_progress = refresh_stalker_series_episodes(
                    account,
                    series_relation,
                )
                # The season listing answered, so the detail attempt is complete.
                has_details = True
                update_series_from_detail_payload(series, detail_data)
            else:
                # Fetch detailed series info including episodes
                with XtreamCodesClient(
                    account.server_url,
                    account.username,
                    account.password,
                    account.get_user_agent_string()
                ) as client:
                    series_info = client.get_series_info(external_series_id)
                    if isinstance(series_info, dict):
                        has_details = True
                        raw_info = series_info.get('info')
                        if isinstance(raw_info, list):
                            logger.warning(
                                "Series info for %s (external_id=%s) returned list "
                                "instead of dict, using first item",
                                series.name,
                                external_series_id,
                            )
                        elif raw_info is not None and not isinstance(raw_info, dict):
                            logger.warning(
                                "Series info for %s (external_id=%s) returned unexpected "
                                "info type %s",
                                series.name,
                                external_series_id,
                                type(raw_info).__name__,
                            )
                        detail_data = _coerce_provider_info(raw_info)
                        update_series_from_detail_payload(series, detail_data)
                        episodes_data = series_info.get('episodes') or {}
                    else:
                        episodes_data = {}
                        logger.info(
                            "Provider returned no series details for series %s "
                            "(external_id=%s); clearing detailed_fetched for retry",
                            series.name,
                            external_series_id,
                        )

        # Count comes from the same flatten batch_process_episodes uses.
        episode_count = batch_process_episodes(
            account,
            series,
            episodes_data,
            series_relation=series_relation,
            only_missing=only_missing,
        )

        if series_relation:
            custom_props = dict(series_relation.custom_properties or {})
            if detail_data:
                custom_props['detail_data'] = detail_data
            if refresh_progress:
                custom_props["stalker_complete_through_season"] = refresh_progress[
                    "complete_through_season"
                ]
                custom_props["stalker_latest_complete_episode"] = refresh_progress[
                    "latest_complete_episode"
                ]
            # A real series_info object completes the detail attempt, including
            # a blank info key. Only a missing or non-object body stays retryable.
            # Episode completion still requires episode dicts. An empty episode
            # list does not clear episodes_fetched when this series relation
            # already has rows, or provider-info would hide episodes that are
            # still stored.
            if has_details is not None:
                custom_props['detailed_fetched'] = has_details
            if episode_count > 0:
                custom_props['episodes_fetched'] = True
            else:
                has_stored_episodes = M3UEpisodeRelation.objects.filter(
                    series_relation=series_relation,
                ).exists()
                if has_stored_episodes:
                    custom_props['episodes_fetched'] = True
                    logger.info(
                        "Provider returned no episodes for series %s "
                        "(external_id=%s); keeping stored episode relations",
                        series.name,
                        external_series_id,
                    )
                else:
                    custom_props['episodes_fetched'] = False
                    logger.info(
                        "Provider returned no episodes for series %s "
                        "(external_id=%s); clearing episodes_fetched for retry",
                        series.name,
                        external_series_id,
                    )
            # Stamp the attempt so the 24h batch picks up empty fetches later.
            # Client opens still retry immediately while either flag is false.
            # Never-opened relations keep a null timestamp and stay out of that batch.
            update_fields = ['custom_properties']
            if has_details is not None or episode_count > 0:
                series_relation.last_episode_refresh = timezone.now()
                update_fields.append('last_episode_refresh')
            series_relation.custom_properties = custom_props
            series_relation.save(update_fields=update_fields)

    except Exception as e:
        logger.error(f"Error refreshing episodes for series {series.name}: {str(e)}")


@shared_task
def refresh_series_relation_episodes_task(series_relation_id):
    """Refresh one series relation's provider details/episodes in a Celery worker."""
    if not acquire_task_lock("refresh_series_relation_episodes", series_relation_id):
        return f"Refresh already in progress for relation {series_relation_id}"

    try:
        try:
            relation = (
                M3USeriesRelation.objects.select_related("m3u_account", "series")
                .get(id=series_relation_id)
            )
        except M3USeriesRelation.DoesNotExist:
            logger.warning(
                "Skipping series episode refresh for missing relation %s",
                series_relation_id,
            )
            return "Series relation not found"

        account = relation.m3u_account
        if not account or not account.is_active:
            logger.info(
                "Skipping series episode refresh for relation %s because account is inactive",
                series_relation_id,
            )
            return "Account inactive"

        refresh_series_episodes(account, relation.series, relation.external_series_id)
        return f"Refreshed series relation {series_relation_id}"
    finally:
        release_task_lock("refresh_series_relation_episodes", series_relation_id)


def batch_process_episodes(
    account,
    series,
    episodes_data,
    scan_start_time=None,
    series_relation=None,
    only_missing=False,
):
    """Process episodes in batches for better performance.

    Note: Multiple streams can represent the same episode (e.g., different languages
    or qualities). Each stream has a unique stream_id, but they share the same
    season/episode number. We create one Episode record per (series, season, episode)
    and multiple M3UEpisodeRelation records pointing to it.

    series_relation, when provided, is stored as a FK on each M3UEpisodeRelation so
    that CASCADE correctly removes episode relations when their parent series relation
    is deleted, and so that stale-stream cleanup is scoped precisely to relations that
    came from this specific provider query.

    Returns the number of episode dicts in the payload. Zero means there was
    nothing to process, including empty, missing, and unexpected shapes.
    """
    if not episodes_data:
        return 0

    is_stalker = account.account_type == M3UAccount.Types.STALKER

    # XC panels encode seasons as a PHP array keyed by season number. When keys are
    # contiguous from 0 (common with Season 0 specials), json_encode emits a JSON
    # array instead of an object. Accept both shapes and use the key/index as the
    # season number.
    if isinstance(episodes_data, dict):
        season_items = episodes_data.items()
    elif isinstance(episodes_data, list):
        season_items = enumerate(episodes_data)
    else:
        logger.warning(
            f"Unexpected episodes_data type {type(episodes_data).__name__} "
            f"for series {series.name}; skipping"
        )
        return 0

    # Flatten episodes data
    all_episodes_data = []
    for season_num, season_episodes in season_items:
        if not isinstance(season_episodes, list):
            continue
        for episode_data in season_episodes:
            if not isinstance(episode_data, dict):
                continue
            normalized_episode = dict(episode_data)
            normalized_episode['_season_number'] = int(season_num)
            all_episodes_data.append(normalized_episode)
            if is_stalker and "episode_num" not in normalized_episode:
                normalized_episode["episode_num"] = extract_stalker_episode_number(
                    normalized_episode
                )

    if not all_episodes_data:
        return 0

    logger.info(f"Batch processing {len(all_episodes_data)} episodes for series {series.name}")

    # Extract episode identifiers
    # Note: episode_keys may have duplicates when multiple streams represent same episode
    episode_keys = set()  # Use set to track unique episode keys
    episode_ids = []
    for episode_data in all_episodes_data:
        season_num = episode_data['_season_number']
        episode_num = (
            extract_stalker_episode_number(episode_data)
            if is_stalker
            else episode_data.get('episode_num', 0)
        )
        episode_keys.add((series.id, season_num, episode_num))
        episode_id = (
            extract_stalker_episode_relation_id(episode_data)
            if is_stalker
            else episode_data.get('id')
        )
        if episode_id not in (None, ""):
            episode_ids.append(str(episode_id))

    # Pre-fetch existing episodes
    existing_episodes = {}
    for episode in Episode.objects.filter(series=series):
        key = (episode.series_id, episode.season_number, episode.episode_number)
        existing_episodes[key] = episode

    # Pre-fetch existing episode relations
    existing_relations = {
        rel.stream_id: rel for rel in M3UEpisodeRelation.objects.filter(
            m3u_account=account,
            stream_id__in=episode_ids
        ).select_related('episode')
    }

    # Prepare batch operations
    episodes_to_create = []
    episodes_to_update = []
    relations_to_create = []
    relations_to_update = []

    # Track episodes we're creating in this batch to avoid duplicates
    # Key: (series_id, season_number, episode_number) -> Episode object
    episodes_pending_creation = {}

    for episode_data in all_episodes_data:
        try:
            if is_stalker:
                stable_episode_id = extract_stalker_episode_relation_id(episode_data)
            else:
                stable_episode_id = episode_data.get('id')

            if stable_episode_id in (None, ""):
                logger.debug("Skipping episode without a stable relation key: %s", episode_data)
                continue

            episode_id = str(stable_episode_id)
            # Ensure season and episode numbers are integers (API may return strings)
            try:
                season_number = int(episode_data['_season_number'])
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid season_number '{episode_data.get('_season_number')}' for episode '{episode_data.get('title', 'Unknown Episode')}': {e}")
                season_number = 0
            try:
                raw_episode_number = (
                    extract_stalker_episode_number(episode_data)
                    if is_stalker
                    else episode_data.get('episode_num', 0)
                )
                episode_number = int(raw_episode_number)
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid episode_num '{episode_data.get('episode_num')}' for episode '{episode_data.get('title', 'Unknown Episode')}': {e}")
                episode_number = 0
            episode_name = (
                extract_display_name(episode_data, f'Episode {episode_number or 0}')
                if is_stalker
                else episode_data.get('title', 'Unknown Episode')
            )
            info = episode_data.get('info', {})

            # Extract episode metadata
            description = info.get('plot') or info.get('overview', '') if info else ''
            rating = normalize_rating(info.get('rating')) if info else None
            air_date = extract_date_from_data(info) if info else None
            if is_stalker:
                # Stalker rows carry runtime as duration_secs or time/runtime.
                duration_secs = extract_duration_from_data(info) if info else None
            else:
                duration_secs = normalize_duration_secs(
                    info.get('duration_secs') if info else None
                )
            tmdb_id = info.get('tmdb_id') if info else None
            imdb_id = info.get('imdb_id') if info else None

            # Prepare custom properties
            custom_props = {}
            if info:
                if info.get('crew'):
                    custom_props['crew'] = info.get('crew')
                if info.get('movie_image'):
                    movie_image = extract_string_from_array_or_string(info.get('movie_image'))
                    if movie_image:
                        custom_props['movie_image'] = movie_image
                backdrop = extract_string_from_array_or_string(info.get('backdrop_path'))
                if backdrop:
                    custom_props['backdrop_path'] = [backdrop]

            # Find existing episode - check DB first, then pending creations
            episode_key = (series.id, season_number, episode_number)
            episode = existing_episodes.get(episode_key)

            # Check if we already have this episode pending creation (multiple streams for same episode)
            if not episode and episode_key in episodes_pending_creation:
                episode = episodes_pending_creation[episode_key]
                logger.debug(f"Reusing pending episode for S{season_number}E{episode_number} (stream_id: {episode_id})")

            if episode:
                # Update existing episode
                updated = False
                if not only_missing and episode_name != episode.name:
                    episode.name = episode_name
                    updated = True
                if not only_missing and description != episode.description:
                    episode.description = description
                    updated = True
                if not only_missing and rating != episode.rating:
                    episode.rating = rating
                    updated = True
                if not only_missing and air_date != episode.air_date:
                    episode.air_date = air_date
                    updated = True
                # Keep an existing duration when the provider sends missing or
                # invalid data; only apply a successfully normalized value.
                if (
                    not only_missing
                    and duration_secs is not None
                    and duration_secs != episode.duration_secs
                ):
                    episode.duration_secs = duration_secs
                    updated = True
                if not only_missing and tmdb_id != episode.tmdb_id:
                    episode.tmdb_id = tmdb_id
                    updated = True
                if not only_missing and imdb_id != episode.imdb_id:
                    episode.imdb_id = imdb_id
                    updated = True
                if not only_missing and custom_props != episode.custom_properties:
                    episode.custom_properties = custom_props if custom_props else None
                    updated = True

                # Only add to update list if episode has a PK (exists in DB) and isn't already in list
                # Episodes pending creation don't have PKs yet and will be created via bulk_create
                if updated and episode.pk and episode not in episodes_to_update:
                    episodes_to_update.append(episode)
            else:
                # Create new episode
                episode = Episode(
                    series=series,
                    name=episode_name,
                    description=description,
                    air_date=air_date,
                    rating=rating,
                    duration_secs=duration_secs,
                    season_number=season_number,
                    episode_number=episode_number,
                    tmdb_id=tmdb_id,
                    imdb_id=imdb_id,
                    custom_properties=custom_props if custom_props else None
                )
                episodes_to_create.append(episode)
                # Track this episode so subsequent streams with same season/episode can reuse it
                episodes_pending_creation[episode_key] = episode

            # Handle episode relation
            if episode_id in existing_relations:
                # Update existing relation
                relation = existing_relations[episode_id]
                if only_missing:
                    relation.last_seen = scan_start_time or timezone.now()
                    relations_to_update.append(relation)
                else:
                    relation.episode = episode
                    relation.series_relation = series_relation
                    relation.container_extension = episode_data.get('container_extension', 'mp4')
                    relation.custom_properties = build_episode_relation_custom_properties(
                        account,
                        episode_data,
                        season_number,
                        series_relation=series_relation,
                    )
                    relation.last_seen = scan_start_time or timezone.now()  # Mark as seen during this scan
                    relations_to_update.append(relation)
            else:
                # Create new relation
                relation = M3UEpisodeRelation(
                    m3u_account=account,
                    episode=episode,
                    series_relation=series_relation,
                    stream_id=episode_id,
                    container_extension=episode_data.get('container_extension', 'mp4'),
                    custom_properties=build_episode_relation_custom_properties(
                        account,
                        episode_data,
                        season_number,
                        series_relation=series_relation,
                    ),
                    last_seen=scan_start_time or timezone.now()  # Mark as seen during this scan
                )
                relations_to_create.append(relation)

        except Exception as e:
            logger.error(f"Error preparing episode {episode_data.get('title', 'Unknown')}: {str(e)}")

    # Execute batch operations
    with transaction.atomic():
        # Create new episodes - use ignore_conflicts in case of race conditions
        if episodes_to_create:
            Episode.objects.bulk_create(episodes_to_create, ignore_conflicts=True)

            # Re-fetch the created episodes to get their PKs
            # We need to do this because bulk_create with ignore_conflicts doesn't set PKs
            created_episode_keys = [
                (ep.series_id, ep.season_number, ep.episode_number)
                for ep in episodes_to_create
            ]
            db_episodes = Episode.objects.filter(series=series)
            episode_pk_map = {
                (ep.series_id, ep.season_number, ep.episode_number): ep
                for ep in db_episodes
            }

            # Update relations to point to the actual DB episodes with PKs
            for relation in relations_to_create:
                ep = relation.episode
                key = (ep.series_id, ep.season_number, ep.episode_number)
                if key in episode_pk_map:
                    relation.episode = episode_pk_map[key]

        # Filter out relations with unsaved episodes (no PK)
        # This can happen if bulk_create had a conflict and ignore_conflicts=True didn't save the episode
        valid_relations_to_create = []
        for relation in relations_to_create:
            if relation.episode.pk is not None:
                valid_relations_to_create.append(relation)
            else:
                season_num = relation.episode.season_number
                episode_num = relation.episode.episode_number
                logger.warning(
                    f"Skipping relation for episode S{season_num}E{episode_num} "
                    f"- episode not saved to database"
                )
        relations_to_create = valid_relations_to_create

        # Update existing episodes
        if episodes_to_update:
            Episode.objects.bulk_update(episodes_to_update, [
                'name', 'description', 'air_date', 'rating', 'duration_secs',
                'tmdb_id', 'imdb_id', 'custom_properties'
            ])

        # Create new episode relations - use ignore_conflicts for stream_id duplicates
        if relations_to_create:
            M3UEpisodeRelation.objects.bulk_create(relations_to_create, ignore_conflicts=True)

        # Update existing episode relations
        if relations_to_update:
            update_fields = ['last_seen'] if only_missing else [
                'episode', 'series_relation', 'container_extension', 'custom_properties', 'last_seen'
            ]
            M3UEpisodeRelation.objects.bulk_update(relations_to_update, update_fields)

        # Delete relations for streams no longer returned by the provider.
        # Scope to this series_relation FK (post-migration rows) plus any legacy NULL rows
        # for the same account+series (pre-migration rows whose stream is now gone — the
        # update path only backfills the FK for streams still present in the response).
        # Falls back to account+series scope when series_relation is None (shouldn't occur).
        if not only_missing:
            if series_relation is not None:
                stale_qs = M3UEpisodeRelation.objects.filter(
                    Q(series_relation=series_relation) |
                    Q(series_relation__isnull=True, m3u_account=account, episode__series=series)
                )
            else:
                stale_qs = M3UEpisodeRelation.objects.filter(
                    m3u_account=account,
                    episode__series=series
                )
            removed_count = stale_qs.exclude(stream_id__in=episode_ids).delete()[0]
            if removed_count:
                logger.info(f"Removed {removed_count} episode relations no longer present in provider for series {series.name}")

    logger.info(f"Batch processed episodes: {len(episodes_to_create)} new, {len(episodes_to_update)} updated, "
                f"{len(relations_to_create)} new relations, {len(relations_to_update)} updated relations")
    return len(all_episodes_data)


@shared_task
def batch_refresh_series_episodes(account_id, series_ids=None):
    """
    Batch refresh episodes for multiple series.
    If series_ids is None, refresh all series that haven't been refreshed recently.
    """
    try:
        account = M3UAccount.objects.select_related("user_agent").get(id=account_id, is_active=True)

        if account.account_type not in (
            M3UAccount.Types.XC,
            M3UAccount.Types.STALKER,
        ):
            logger.warning(
                "Episode refresh called for unsupported account %s",
                account_id,
            )
            return "Episode refresh only available for XtreamCodes and Stalker accounts"

        # Determine which series to refresh
        if series_ids:
            series_relations = get_enabled_series_relations_queryset(
                M3USeriesRelation.objects.filter(
                    m3u_account=account,
                    series__id__in=series_ids
                )
            ).select_related('series')
            
        else:
            # Refresh series last fetched more than 24 hours ago. Never-opened
            # series keep a null timestamp and stay on-demand. Empty attempts
            # still stamp last_episode_refresh, so they re-enter after the
            # interval instead of a null check pulling in the whole catalog.
            cutoff_time = timezone.now() - timezone.timedelta(hours=24)
            series_relations = get_enabled_series_relations_queryset(
                M3USeriesRelation.objects.filter(
                    m3u_account=account,
                    last_episode_refresh__lt=cutoff_time,
                )
            ).select_related('series')

        logger.info(f"Batch refreshing episodes for {series_relations.count()} series")
        relation_ids = list(series_relations.values_list("id", flat=True))
        if not relation_ids:
            return "Batch episode refresh completed for 0 series"

        if current_app.conf.task_always_eager:
            refreshed_count = 0
            for relation_id in relation_ids:
                try:
                    refresh_series_relation_episodes_task(relation_id)
                    refreshed_count += 1
                except Exception as e:
                    logger.error(
                        "Error refreshing episodes for relation %s: %s",
                        relation_id,
                        e,
                    )

            logger.info(f"Batch episode refresh completed for {refreshed_count} series")
            return f"Batch episode refresh completed for {refreshed_count} series"

        job = group(
            refresh_series_relation_episodes_task.s(relation_id)
            for relation_id in relation_ids
        ).apply_async()
        logger.info(
            "Queued batch episode refresh for %s series relations on account %s (group_id=%s)",
            len(relation_ids),
            account_id,
            job.id,
        )
        return (
            f"Queued batch episode refresh for {len(relation_ids)} series "
            f"(group_id={job.id})"
        )

    except Exception as e:
        logger.error(f"Error in batch episode refresh for account {account_id}: {str(e)}")
        return f"Batch episode refresh failed: {str(e)}"


def _find_vod_for_language(model, source, language):
    """Existing Movie/Series that already holds this language for source's identity.

    TMDB is checked first, then IMDB. A row with a different TMDB id can still
    occupy the ``(imdb_id, language)`` slot, and claiming past it would fail
    the unique constraint on every later refresh.
    """
    if source.tmdb_id:
        row = model.objects.filter(tmdb_id=source.tmdb_id, language=language).first()
        if row is not None:
            return row
    if source.imdb_id:
        row = model.objects.filter(imdb_id=source.imdb_id, language=language).first()
        if row is not None:
            return row
    if not source.tmdb_id and not source.imdb_id:
        return model.objects.filter(
            name=source.name, year=source.year, language=language,
            tmdb_id__isnull=True, imdb_id__isnull=True,
        ).first()
    return None


def _find_or_create_vod_for_language(model, source, language):
    existing = _find_vod_for_language(model, source, language)
    if existing is not None:
        return existing
    # Explicit tmdb_id/imdb_id here, not get_or_create(..., tmdb_id__isnull=True):
    # get_or_create() strips '__' kwargs when building the create() call, which
    # would leave tmdb_id/imdb_id as '' (CharField default) instead of NULL and
    # silently defeat the partial UniqueConstraint's isnull condition.
    return model.objects.create(
        name=source.name,
        year=source.year,
        language=language,
        tmdb_id=source.tmdb_id,
        imdb_id=source.imdb_id,
    )


def _move_language_relations(relation_model, relations, target, fk_name, *, refetch_episodes):
    """Point relations at target and force a detail refetch on next open."""
    for rel in relations:
        setattr(rel, fk_name, target)
        cp = rel.custom_properties or {}
        cp['detailed_fetched'] = False
        if refetch_episodes:
            cp['episodes_fetched'] = False
        rel.custom_properties = cp
    relation_model.objects.bulk_update(relations, [fk_name, 'custom_properties'])


def _language_reconcile_candidate_ids(account, scan_start_time, *, relation_model, fk_name):
    """Primary keys whose touched relations no longer match the row language.

    Compared in SQL so a refresh with no language work does not load the
    catalog into Python. Covers first-time tags (untagged row, tagged
    category), retags, and clears. Missing or null category language counts
    as untagged, and the code is compared case-insensitively.
    """
    lang_sq = (
        M3UVODCategoryRelation.objects.filter(
            m3u_account_id=OuterRef('m3u_account_id'),
            category_id=OuterRef('category_id'),
        )
        .annotate(
            _lang=Lower(
                Coalesce(
                    KeyTextTransform('language', 'custom_properties'),
                    Value(''),
                    output_field=TextField(),
                )
            )
        )
        .values('_lang')[:1]
    )
    return set(
        relation_model.objects.filter(
            m3u_account=account,
            last_seen__gte=scan_start_time,
        )
        .annotate(
            resolved_lang=Coalesce(
                Subquery(lang_sq, output_field=TextField()),
                Value(''),
                output_field=TextField(),
            )
        )
        .exclude(resolved_lang=F(f'{fk_name}__language'))
        .values_list(f'{fk_name}_id', flat=True)
        .distinct()
    )


def _language_reconcile_candidates(account, scan_start_time, *, model, relation_model, fk_name):
    """Rows this account's refresh may need to rename or split by language."""
    candidate_ids = _language_reconcile_candidate_ids(
        account, scan_start_time, relation_model=relation_model, fk_name=fk_name,
    )
    if not candidate_ids:
        return []
    return list(model.objects.filter(id__in=candidate_ids))


def _category_language_map(relations):
    """``(account_id, category_id) -> language`` for these relations, loaded once."""
    account_ids = {rel.m3u_account_id for rel in relations if rel.category_id}
    category_ids = {rel.category_id for rel in relations if rel.category_id}
    if not category_ids:
        return {}
    return {
        (category_rel.m3u_account_id, category_rel.category_id): category_language(category_rel)
        for category_rel in M3UVODCategoryRelation.objects.filter(
            m3u_account_id__in=account_ids, category_id__in=category_ids
        )
    }


def _relation_language(rel, language_map):
    if not rel.category_id:
        return ''
    return language_map.get((rel.m3u_account_id, rel.category_id), '')


def _group_relations_by_language(relations, language_map):
    """Map category language to the relations that currently resolve to it."""
    groups = {}
    for rel in relations:
        groups.setdefault(_relation_language(rel, language_map), []).append(rel)
    return groups


def _identity_key(row):
    """Identity used to find another language of the same title. TMDB wins, then IMDB."""
    if row.tmdb_id:
        return ('tmdb', row.tmdb_id)
    if row.imdb_id:
        return ('imdb', row.imdb_id)
    return ('name', row.name, row.year)


def _load_language_slots(model, rows):
    """``(identity key, language) -> row`` for titles these rows might collide with."""
    slots = {}

    def add(row):
        if row.tmdb_id:
            slots[(('tmdb', row.tmdb_id), row.language)] = row
        if row.imdb_id:
            slots[(('imdb', row.imdb_id), row.language)] = row
        if not row.tmdb_id and not row.imdb_id:
            slots[(('name', row.name, row.year), row.language)] = row

    tmdb_ids = {row.tmdb_id for row in rows if row.tmdb_id}
    imdb_ids = {row.imdb_id for row in rows if row.imdb_id}
    names = {row.name for row in rows if not row.tmdb_id and not row.imdb_id}
    if tmdb_ids:
        for row in model.objects.filter(tmdb_id__in=tmdb_ids):
            add(row)
    if imdb_ids:
        for row in model.objects.filter(imdb_id__in=imdb_ids):
            add(row)
    if names:
        for row in model.objects.filter(
            name__in=names, tmdb_id__isnull=True, imdb_id__isnull=True
        ):
            add(row)
    return slots


def _language_slot_owner(slots, source, language):
    """Another row already stored at source's identity and language, or None."""
    if source.tmdb_id:
        owner = slots.get((('tmdb', source.tmdb_id), language))
        if owner is not None and owner.id != source.id:
            return owner
    if source.imdb_id:
        owner = slots.get((('imdb', source.imdb_id), language))
        if owner is not None and owner.id != source.id:
            return owner
    if not source.tmdb_id and not source.imdb_id:
        owner = slots.get((('name', source.name, source.year), language))
        if owner is not None and owner.id != source.id:
            return owner
    return None


def _language_in_use(model, source, language):
    """DB row, other than source, occupying this identity and language."""
    owner = _find_vod_for_language(model, source, language)
    if owner is not None and owner.id != source.id:
        return owner
    return None


_PARK_LETTERS = "zyxwvutsrqponmlkjihgfedcba"
_BULK_LANGUAGE_CHUNK = 500


class _ReconcileRun:
    """Counts and ids for one committed title. Discarded if that transaction rolls back."""

    def __init__(self):
        self.updated = 0
        self.moved = 0
        self.absorbed = 0
        self.absorbed_ids = set()
        self.done = set()
        self.stack = []


_SKIPPED_TITLE_RE = re.compile(r"(\d+) titles? skipped")


def _language_skip_note(movie_summary, series_summary):
    """Short refresh-status sentence when any title was skipped."""
    notes = []
    for summary, kind in ((movie_summary, "movie"), (series_summary, "series")):
        match = _SKIPPED_TITLE_RE.search(summary or "")
        if not match:
            continue
        count = int(match.group(1))
        if count == 1:
            notes.append(f"1 {kind} title skipped during language reconcile")
        else:
            notes.append(f"{count} {kind} titles skipped during language reconcile")
    if not notes:
        return ""
    return ". " + ". ".join(notes)


def _skip_phrase(failed):
    if failed == 1:
        return "1 title skipped"
    return f"{failed} titles skipped"


def _reconcile_keep_language(source, groups, non_empty_langs):
    """Language that stays on source.id among the groups still on this row.

    Hand-off may already have moved streams that have a clean home, so
    ``groups`` can be smaller than the row started with. Among what remains:
    an untagged group keeps '', a still-matching tagged language stays,
    otherwise the largest remaining group wins (language code breaks a
    tie). Clearing every category language leaves ''.
    """
    if source.language == '':
        if '' in groups:
            return ''
        if len(non_empty_langs) == 1:
            return non_empty_langs[0]
        return max(non_empty_langs, key=lambda lang: (len(groups[lang]), lang))

    if source.language in groups:
        return source.language
    if not non_empty_langs:
        return ''
    if len(non_empty_langs) == 1:
        return non_empty_langs[0]
    return max(non_empty_langs, key=lambda lang: (len(groups[lang]), lang))


def _row_keep_language(source, groups):
    """Language this row should end on, or None when there is nothing to do."""
    if not groups:
        return None
    non_empty_langs = [lang for lang in groups if lang != '']
    if source.language == '':
        if not non_empty_langs:
            return None
    elif set(groups) == {source.language}:
        # A cleared category resolves to '' and is not a match.
        return None
    return _reconcile_keep_language(source, groups, non_empty_langs)


def _groups_for_row(ctx, row):
    """Group this row's relations, loading any category languages not seen yet.

    A donor is often not one of this account's candidates, so its categories
    are absent from the map built for the candidate scan.
    """
    relations = list(ctx.relation_model.objects.filter(**{ctx.fk_id: row.id}))
    missing = [
        rel for rel in relations
        if rel.category_id and (rel.m3u_account_id, rel.category_id) not in ctx.language_map
    ]
    if missing:
        ctx.language_map.update(_category_language_map(missing))
    return _group_relations_by_language(relations, ctx.language_map)


def _relations_all_match(ctx, row, language):
    """True when every relation on row resolves to language (or row has none)."""
    groups = _groups_for_row(ctx, row)
    if not groups:
        return True
    return set(groups) <= {language}


def _set_language(source, language, run):
    if source.language == language:
        return
    source.language = language
    source.save(update_fields=['language'])
    run.updated += 1


def _park_language(ctx, row, forbidden):
    """Move row off its language slot onto a code this title does not use.

    Used only inside the claim transaction so a pair of rows can exchange
    languages without tripping the unique constraint. The parked value is
    overwritten before commit.
    """
    for first in _PARK_LETTERS:
        for second in _PARK_LETTERS:
            code = first + second
            if code in forbidden:
                continue
            if _language_in_use(ctx.model, row, code) is None:
                row.language = code
                row.save(update_fields=['language'])
                return
    raise RuntimeError(f"no free language code to park {ctx.fk_name} id={row.id}")


def _claim_language(ctx, source, keep_lang, run):
    """Make source.language == keep_lang, keeping ids of rows whose streams disagree.

    A stored language row is absorbed only when every one of its relations
    resolves to keep_lang. Otherwise that row is reconciled first so it leaves
    the slot under its own id.
    """
    # Retry only while the occupant actually changes. A swap settles in a
    # couple of tries. The same occupant twice means this claim is stuck.
    seen_occupants = set()
    while True:
        try:
            source.refresh_from_db()
        except ctx.model.DoesNotExist:
            return
        if source.language == keep_lang:
            return
        donor = _find_vod_for_language(ctx.model, source, keep_lang)
        if donor is None or donor.id == source.id or donor.id in run.absorbed_ids:
            _set_language(source, keep_lang, run)
            return
        if _relations_all_match(ctx, donor, keep_lang):
            run.absorbed += _absorb_language_row(
                source, donor, ctx.relation_model, ctx.fk_name,
                refetch_episodes=ctx.refetch_episodes,
            )
            run.absorbed_ids.add(donor.id)
            _set_language(source, keep_lang, run)
            return
        if source.id in run.stack:
            # The occupant is part of this claim chain (the two titles swapped
            # languages). Park it, then take the slot on the next attempt.
            _park_language(ctx, donor, forbidden={keep_lang, source.language, donor.language, ''})
            continue
        occupant = (donor.id, donor.language)
        if occupant in seen_occupants:
            raise RuntimeError(f"language claim did not settle for {ctx.fk_name} id={source.id}")
        seen_occupants.add(occupant)
        run.stack.append(source.id)
        try:
            _reconcile_one(ctx, donor, run)
        finally:
            run.stack.pop()


def _clean_language_row(ctx, source, language, run):
    """Row that already is `language` and whose streams all want it, or None."""
    donor = _find_vod_for_language(ctx.model, source, language)
    if donor is None or donor.id == source.id or donor.id in run.absorbed_ids:
        return None
    if not _relations_all_match(ctx, donor, language):
        return None
    return donor


def _hand_off_clean_languages(ctx, source, run):
    """Move streams onto rows that already own their language, in one pass.

    Languages with a clean home leave this row. The keep rule then runs on
    whatever remains, which may be a smaller group than the row started
    with. When every language already has a home, one language is kept so
    this id does not disappear, and claim absorbs that language's duplicate.
    """
    groups = _groups_for_row(ctx, source)
    keep_lang = _row_keep_language(source, groups)
    if keep_lang is None:
        return
    homes = {
        lang: _clean_language_row(ctx, source, lang, run)
        for lang in groups
    }
    homes = {lang: donor for lang, donor in homes.items() if donor is not None}
    if not homes:
        return
    to_move = set(homes)
    if to_move >= set(groups):
        to_move.discard(keep_lang)
    for lang in to_move:
        rels = groups.get(lang) or []
        if not rels:
            continue
        _move_language_relations(
            ctx.relation_model, rels, homes[lang], ctx.fk_name,
            refetch_episodes=ctx.refetch_episodes,
        )
        run.moved += len(rels)


def _reconcile_one(ctx, source, run):
    """Rename, split, or absorb one row. Nested calls share ``run``."""
    if source.id in run.done or source.id in run.absorbed_ids:
        return
    try:
        source.refresh_from_db()
    except ctx.model.DoesNotExist:
        run.done.add(source.id)
        return

    moved_before = run.moved
    _hand_off_clean_languages(ctx, source, run)
    groups = _groups_for_row(ctx, source)
    keep_lang = _row_keep_language(source, groups)
    if keep_lang is not None:
        _claim_language(ctx, source, keep_lang, run)

    try:
        source.refresh_from_db()
    except ctx.model.DoesNotExist:
        run.done.add(source.id)
        return

    current_groups = _groups_for_row(ctx, source)
    for lang, rels in current_groups.items():
        if lang == source.language or not rels:
            continue
        target = _find_or_create_vod_for_language(ctx.model, source, lang)
        if target.id == source.id or target.id in run.absorbed_ids:
            continue
        _move_language_relations(
            ctx.relation_model, rels, target, ctx.fk_name,
            refetch_episodes=ctx.refetch_episodes,
        )
        run.moved += len(rels)
    if ctx.before_split is not None and run.moved > moved_before:
        ctx.before_split(source)
    run.done.add(source.id)


class _LanguageReconcileContext:
    def __init__(self, model, relation_model, fk_name, language_map, refetch_episodes, before_split):
        self.model = model
        self.relation_model = relation_model
        self.fk_name = fk_name
        self.fk_id = f'{fk_name}_id'
        self.language_map = language_map
        self.refetch_episodes = refetch_episodes
        self.before_split = before_split
        self.finished = set()
        self.absorbed_ids = set()


def _language_only_rows(candidates, groups_by_id, slots):
    """Rows whose every relation wants one language and that slot is free.

    These are a language update and nothing else, so they can be written
    with one bulk_update. Two candidates claiming the same slot stay on the
    per-title path, which collapses them.
    """
    plans = {}
    claimants = {}
    for source in candidates:
        groups = groups_by_id.get(source.id, {})
        keep_lang = _row_keep_language(source, groups)
        if keep_lang is None or set(groups) != {keep_lang} or keep_lang == source.language:
            continue
        plans[source.id] = keep_lang
        claimants.setdefault((_identity_key(source), keep_lang), []).append(source.id)

    simple = []
    for source in candidates:
        keep_lang = plans.get(source.id)
        if keep_lang is None:
            continue
        if len(claimants[(_identity_key(source), keep_lang)]) != 1:
            continue
        if _language_slot_owner(slots, source, keep_lang) is not None:
            continue
        simple.append(source)
    return plans, simple


def _bulk_set_language(model, rows, plans):
    for row in rows:
        row.language = plans[row.id]
    for offset in range(0, len(rows), _BULK_LANGUAGE_CHUNK):
        model.objects.bulk_update(rows[offset:offset + _BULK_LANGUAGE_CHUNK], ['language'])


def _reconcile_language_identity(
    account,
    scan_start_time,
    *,
    model,
    relation_model,
    fk_name,
    noun,
    title,
    refetch_episodes=False,
    before_split=None,
):
    """Resolve language identity for rows this account's refresh touched.

    The batch pins an already-known stream to its current row so a category
    re-tag cannot fork mid-ingest. This runs once per content type after the
    batches, before cleanup_orphaned_vod_content, and considers every
    account's relations on those rows.

    The existing row keeps its id. A new id is created only for a language
    group that cannot stay on that row, including relations whose category
    language was cleared. before_split(source), when set, runs after series
    relations have moved so episodes can follow series_relation.

    A donor is absorbed only when its relations all want the language being
    claimed. Otherwise it is reconciled first and keeps its id. A title that
    raises is rolled back and counted as skipped; the rest of the account
    continues.
    """
    candidates = _language_reconcile_candidates(
        account, scan_start_time,
        model=model, relation_model=relation_model, fk_name=fk_name,
    )
    if not candidates:
        return f"No {noun} needed language reconcile this refresh."

    fk_id = f'{fk_name}_id'
    relations = list(relation_model.objects.filter(**{f'{fk_id}__in': [row.id for row in candidates]}))
    language_map = _category_language_map(relations)
    groups_by_id = {}
    for rel in relations:
        groups_by_id.setdefault(getattr(rel, fk_id), []).append(rel)
    groups_by_id = {
        row_id: _group_relations_by_language(rels, language_map)
        for row_id, rels in groups_by_id.items()
    }
    slots = _load_language_slots(model, candidates)
    plans, simple = _language_only_rows(candidates, groups_by_id, slots)
    simple_ids = {row.id for row in simple}

    updated = moved = absorbed = failed = 0
    if simple:
        try:
            with transaction.atomic():
                _bulk_set_language(model, simple, plans)
        except Exception:
            logger.exception(
                "Bulk language update failed for account %s; retrying those %s per title",
                account.id, noun,
            )
            for row in simple:
                try:
                    row.refresh_from_db()
                except model.DoesNotExist:
                    pass
            simple_ids = set()
        else:
            updated += len(simple)

    pending = [
        row for row in candidates
        if row.id not in simple_ids
        and _row_keep_language(row, groups_by_id.get(row.id, {})) is not None
    ]
    # Rows leaving their stored language run first, so a row arriving at that
    # language finds the slot empty. Within each group, newer ids run first
    # and the older id absorbs them when both end on the same language.
    pending.sort(key=lambda row: (
        0 if row.language and row.language not in groups_by_id.get(row.id, {}) else 1,
        -row.id,
    ))

    ctx = _LanguageReconcileContext(
        model, relation_model, fk_name, language_map, refetch_episodes, before_split,
    )
    for source in pending:
        if source.id in ctx.finished or source.id in ctx.absorbed_ids:
            continue
        run = _ReconcileRun()
        try:
            with transaction.atomic():
                _reconcile_one(ctx, source, run)
        except Exception:
            logger.exception(
                "Language reconcile failed for %s id=%s (account %s); "
                "continuing with remaining titles",
                noun, source.id, account.id,
            )
            failed += 1
            continue
        updated += run.updated
        moved += run.moved
        absorbed += run.absorbed
        ctx.finished |= run.done
        ctx.absorbed_ids |= run.absorbed_ids

    if before_split is not None:
        # Split only runs when relations move. Rename-only and bulk updates
        # still drop empty episode rows left on titles this refresh touched.
        Episode.objects.filter(
            series_id__in=[row.id for row in candidates],
            m3u_relations__isnull=True,
        ).delete()

    if updated == 0 and moved == 0 and absorbed == 0 and failed == 0:
        return f"No {noun} needed language reconcile this refresh."

    result = (
        f"{title} language reconcile: {updated} updated in place, "
        f"{moved} relations moved, {absorbed} existing language rows absorbed"
    )
    if failed:
        result = f"{result}, {_skip_phrase(failed)}"
        logger.warning(result)
    else:
        logger.info(result)
    return result


def reconcile_movie_language_identity(account, scan_start_time):
    """Resolve movie language identity after this account's refresh. See _reconcile_language_identity."""
    return _reconcile_language_identity(
        account,
        scan_start_time,
        model=Movie,
        relation_model=M3UMovieRelation,
        fk_name='movie',
        noun='movies',
        title='Movie',
    )


def _fill_blank_vod_metadata(survivor, donor):
    """Copy donor fields onto survivor only where survivor is blank."""
    update_fields = []
    for field in ('description', 'rating', 'genre', 'year'):
        current = getattr(survivor, field)
        incoming = getattr(donor, field)
        if is_blank_vod_value(current) and not is_blank_vod_value(incoming):
            setattr(survivor, field, incoming)
            update_fields.append(field)
    if hasattr(survivor, 'duration_secs'):
        current = survivor.duration_secs
        incoming = donor.duration_secs
        if not current and incoming:
            survivor.duration_secs = incoming
            update_fields.append('duration_secs')
    if not survivor.logo_id and donor.logo_id:
        survivor.logo_id = donor.logo_id
        update_fields.append('logo')
    survivor_cp = dict(survivor.custom_properties or {})
    changed = False
    for key, value in (donor.custom_properties or {}).items():
        if not is_blank_vod_value(value) and is_blank_vod_value(survivor_cp.get(key)):
            survivor_cp[key] = value
            changed = True
    if changed:
        survivor.custom_properties = survivor_cp
        update_fields.append('custom_properties')
    if update_fields:
        survivor.save(update_fields=update_fields)


def _absorb_language_row(source, donor, relation_model, fk_name, *, refetch_episodes):
    """Move donor onto source and delete donor. source keeps its id.

    donor is removed before source.language is set by the caller, so the
    unique (external id, language) slot is free.
    """
    donor_relations = list(relation_model.objects.filter(**{f'{fk_name}_id': donor.id}))
    if donor_relations:
        _move_language_relations(
            relation_model, donor_relations, source, fk_name,
            refetch_episodes=refetch_episodes,
        )
    if refetch_episodes:
        _migrate_series_episodes(donor, source)
    _fill_blank_vod_metadata(source, donor)
    donor.delete()
    return 1


def _migrate_series_episodes(source_series, target_series):
    """Move source_series's Episodes onto target_series before source_series
    is deleted.

    Repoints Episode.series in place (preserving Episode/relation ids - those
    ids are what clients are currently playing) unless target_series already
    has an Episode at the same (season, episode), in which case the source
    episode's M3UEpisodeRelations move onto the existing target episode and
    the now-empty source episode is deleted.
    """
    for episode in list(Episode.objects.filter(series=source_series)):
        collision = Episode.objects.filter(
            series=target_series,
            season_number=episode.season_number,
            episode_number=episode.episode_number,
        ).first()
        if collision:
            M3UEpisodeRelation.objects.filter(episode=episode).update(episode=collision)
            episode.delete()
        else:
            episode.series = target_series
            episode.save(update_fields=['series'])


def _clone_episode_onto_series(episode, series_id):
    """Episode row on series_id for this season/episode, creating one if needed."""
    existing = Episode.objects.filter(
        series_id=series_id,
        season_number=episode.season_number,
        episode_number=episode.episode_number,
    ).first()
    if existing is not None:
        return existing
    return Episode.objects.create(
        series_id=series_id,
        name=episode.name,
        description=episode.description,
        air_date=episode.air_date,
        rating=episode.rating,
        duration_secs=episode.duration_secs,
        season_number=episode.season_number,
        episode_number=episode.episode_number,
        tmdb_id=episode.tmdb_id,
        imdb_id=episode.imdb_id,
        custom_properties=episode.custom_properties,
    )


def _split_series_episodes(source_series):
    """Point each episode stream at an episode of the series it was fetched for.

    The Episode row stays with whichever destination has the most of its
    relations (series id breaks a tie), so that episode id does not change
    for that series. Other series_relation values get their own episode row.
    A null series_relation stays on the original episode. Rows with no
    streams left, including ones that were already empty, are deleted.
    """
    episodes = list(Episode.objects.filter(series=source_series))
    if not episodes:
        return
    relations = M3UEpisodeRelation.objects.filter(
        episode_id__in=[episode.id for episode in episodes]
    ).select_related('series_relation')
    by_episode = {}
    for rel in relations:
        by_episode.setdefault(rel.episode_id, []).append(rel)

    for episode in episodes:
        episode_relations = by_episode.get(episode.id, [])
        if not episode_relations:
            episode.delete()
            continue
        destinations = {}
        for rel in episode_relations:
            if rel.series_relation_id and rel.series_relation.series_id != episode.series_id:
                dest = rel.series_relation.series_id
            else:
                dest = episode.series_id
            destinations.setdefault(dest, []).append(rel)
        if len(destinations) == 1 and episode.series_id in destinations:
            continue
        winner = max(destinations, key=lambda series_id: (len(destinations[series_id]), series_id))
        if winner != episode.series_id:
            collision = Episode.objects.filter(
                series_id=winner,
                season_number=episode.season_number,
                episode_number=episode.episode_number,
            ).exclude(pk=episode.pk).first()
            if collision is not None:
                M3UEpisodeRelation.objects.filter(
                    id__in=[rel.id for rel in destinations[winner]]
                ).update(episode=collision)
                destinations[winner] = []
            else:
                episode.series_id = winner
                episode.save(update_fields=['series'])
        home = episode.series_id
        for dest, group in destinations.items():
            if dest == home or not group:
                continue
            clone = _clone_episode_onto_series(episode, dest)
            M3UEpisodeRelation.objects.filter(
                id__in=[rel.id for rel in group]
            ).update(episode=clone)
        if not M3UEpisodeRelation.objects.filter(episode=episode).exists():
            episode.delete()


def reconcile_series_language_identity(account, scan_start_time):
    """Resolve series language identity after this account's refresh. See _reconcile_language_identity.

    When relations move to another series, episode streams follow
    series_relation onto the series they were fetched for. Episode ids stay
    with the series that has the most streams of that episode.
    """
    return _reconcile_language_identity(
        account,
        scan_start_time,
        model=Series,
        relation_model=M3USeriesRelation,
        fk_name='series',
        noun='series',
        title='Series',
        refetch_episodes=True,
        before_split=_split_series_episodes,
    )


@shared_task
def cleanup_orphaned_vod_content(
    stale_days=0,
    scan_start_time=None,
    account_id=None,
    keep_movie_relations=None,
    keep_series_relations=None,
):
    """Clean up VOD content that has no M3U relations or has stale relations.

    Relations matching ``keep_movie_relations`` / ``keep_series_relations``
    (Q filters) are never treated as stale: their category could not be
    fetched during this scan, so ``last_seen`` is not a reliable signal.
    """
    from datetime import timedelta

    # Use scan start time as reference, or current time if not provided
    reference_time = scan_start_time or timezone.now()

    # Calculate cutoff date for stale relations
    cutoff_date = reference_time - timedelta(days=stale_days)

    # Build base query filters
    base_filters = {'last_seen__lt': cutoff_date}
    if account_id:
        base_filters['m3u_account_id'] = account_id
        logger.info(f"Cleaning up stale VOD content for account {account_id}")
    else:
        logger.info("Cleaning up stale VOD content across all accounts")

    # Clean up stale movie relations (haven't been seen in the specified days)
    stale_movie_relations = M3UMovieRelation.objects.filter(**base_filters)
    if keep_movie_relations is not None:
        # Exclude by id: excluding the Q directly would also keep rows where
        # the JSON key is missing, because NOT (... OR NULL) is not true.
        stale_movie_relations = stale_movie_relations.exclude(
            id__in=M3UMovieRelation.objects.filter(keep_movie_relations).values("id")
        )
    stale_movie_count = stale_movie_relations.count()
    stale_movie_relations.delete()

    # Clean up stale series relations.
    # Episode relations are removed via CASCADE on the series_relation FK.
    stale_series_relations = M3USeriesRelation.objects.filter(**base_filters)
    if keep_series_relations is not None:
        stale_series_relations = stale_series_relations.exclude(
            id__in=M3USeriesRelation.objects.filter(keep_series_relations).values("id")
        )
    stale_series_count = stale_series_relations.count()
    stale_series_relations.delete()

    # Clean up movies with no relations (orphaned)
    # Safe to delete even during account-specific cleanup because if ANY account
    # has a relation, m3u_relations will not be null
    orphaned_movies = Movie.objects.filter(m3u_relations__isnull=True)
    orphaned_movie_count = orphaned_movies.count()
    if orphaned_movie_count > 0:
        logger.info(f"Deleting {orphaned_movie_count} orphaned movies with no M3U relations")
        try:
            orphaned_movies.delete()
        except IntegrityError:
            # A concurrent refresh task created a new relation for one of these movies
            # between our query and the DELETE. Skip and let the next cleanup run handle it.
            logger.warning(
                "Skipped some orphaned movie deletions due to concurrent modifications; "
                "they will be retried on the next cleanup run."
            )
            orphaned_movie_count = 0

    # Clean up series with no relations (orphaned)
    orphaned_series = Series.objects.filter(m3u_relations__isnull=True)
    orphaned_series_count = orphaned_series.count()
    if orphaned_series_count > 0:
        logger.info(f"Deleting {orphaned_series_count} orphaned series with no M3U relations")
        try:
            orphaned_series.delete()
        except IntegrityError:
            logger.warning(
                "Skipped some orphaned series deletions due to concurrent modifications; "
                "they will be retried on the next cleanup run."
            )
            orphaned_series_count = 0

    result = (f"Cleaned up {stale_movie_count} stale movie relations, "
              f"{stale_series_count} stale series relations, "
              f"{orphaned_movie_count} orphaned movies, and "
              f"{orphaned_series_count} orphaned series")

    logger.info(result)
    return result


def handle_movie_id_conflicts(current_movie, relation, tmdb_id_to_set, imdb_id_to_set):
    """
    Handle potential duplicate key conflicts when setting tmdb_id or imdb_id.

    Since this is called when a user is actively accessing movie details, we always
    preserve the current movie (user's selection) and merge the existing one into it.
    This prevents breaking the user's current viewing experience.

    Returns:
        tuple: (movie_to_use, relation_was_updated)
    """
    from django.db import IntegrityError

    existing_movie_with_tmdb = None
    existing_movie_with_imdb = None

    # Check for existing movies with these IDs
    if tmdb_id_to_set:
        try:
            existing_movie_with_tmdb = Movie.objects.get(
                tmdb_id=tmdb_id_to_set, language=current_movie.language
            )
        except Movie.DoesNotExist:
            pass

    if imdb_id_to_set:
        try:
            existing_movie_with_imdb = Movie.objects.get(
                imdb_id=imdb_id_to_set, language=current_movie.language
            )
        except Movie.DoesNotExist:
            pass

    # If no conflicts, proceed normally
    if not existing_movie_with_tmdb and not existing_movie_with_imdb:
        return current_movie, False

    # Determine which existing movie has the conflicting ID (prefer TMDB match)
    existing_movie = existing_movie_with_tmdb or existing_movie_with_imdb

    # CRITICAL: Check if the existing movie is actually the same as the current movie
    # This can happen if the current movie already has the ID we're trying to set
    if existing_movie.id == current_movie.id:
        logger.debug(f"Current movie {current_movie.id} already has the target ID, no conflict resolution needed")
        return current_movie, False

    logger.info(f"ID conflict detected: Merging existing movie '{existing_movie.name}' (ID: {existing_movie.id}) into current movie '{current_movie.name}' (ID: {current_movie.id}) to preserve user selection")

    # FIRST: Clear the conflicting ID from the existing movie before any merging
    if existing_movie_with_tmdb and tmdb_id_to_set:
        logger.info(f"Clearing tmdb_id from existing movie {existing_movie.id} to avoid constraint violation")
        existing_movie.tmdb_id = None
        existing_movie.save(update_fields=['tmdb_id'])

    if existing_movie_with_imdb and imdb_id_to_set:
        logger.info(f"Clearing imdb_id from existing movie {existing_movie.id} to avoid constraint violation")
        existing_movie.imdb_id = None
        existing_movie.save(update_fields=['imdb_id'])

    # THEN: Merge data from existing movie into current movie (now safe to set IDs)
    merge_movie_data(source_movie=existing_movie, target_movie=current_movie,
                     tmdb_id_to_set=tmdb_id_to_set, imdb_id_to_set=imdb_id_to_set)

    # Transfer all relations from existing movie to current movie
    existing_relations = existing_movie.m3u_relations.all()
    if existing_relations.exists():
        logger.info(f"Transferring {existing_relations.count()} relations from existing movie {existing_movie.id} to current movie {current_movie.id}")
        existing_relations.update(movie=current_movie)

    # Now safe to delete the existing movie since all its relations have been transferred
    logger.info(f"Deleting existing movie {existing_movie.id} '{existing_movie.name}' after merging data and transferring relations")
    existing_movie.delete()

    return current_movie, False  # No relation update needed since we kept current movie


def merge_movie_data(source_movie, target_movie, tmdb_id_to_set=None, imdb_id_to_set=None):
    """
    Merge valuable data from source_movie into target_movie.
    Only overwrites target fields that are empty/None with non-empty source values.

    Args:
        source_movie: Movie to copy data from
        target_movie: Movie to copy data to
        tmdb_id_to_set: TMDB ID to set on target (overrides source tmdb_id)
        imdb_id_to_set: IMDB ID to set on target (overrides source imdb_id)
    """
    updated = False

    # Basic fields - only fill if target is empty
    if not target_movie.description and source_movie.description:
        target_movie.description = source_movie.description
        updated = True
        logger.debug(f"Merged description from movie {source_movie.id} to {target_movie.id}")

    if not target_movie.year and source_movie.year:
        target_movie.year = source_movie.year
        updated = True
        logger.debug(f"Merged year from movie {source_movie.id} to {target_movie.id}")

    if not target_movie.rating and source_movie.rating:
        target_movie.rating = source_movie.rating
        updated = True
        logger.debug(f"Merged rating from movie {source_movie.id} to {target_movie.id}")

    if not target_movie.genre and source_movie.genre:
        target_movie.genre = source_movie.genre
        updated = True
        logger.debug(f"Merged genre from movie {source_movie.id} to {target_movie.id}")

    if not target_movie.duration_secs and source_movie.duration_secs:
        target_movie.duration_secs = source_movie.duration_secs
        updated = True
        logger.debug(f"Merged duration_secs from movie {source_movie.id} to {target_movie.id}")

    if not target_movie.logo and source_movie.logo:
        target_movie.logo = source_movie.logo
        updated = True
        logger.debug(f"Merged logo from movie {source_movie.id} to {target_movie.id}")

    # Handle external IDs - use the specific IDs we want to set, or fall back to source
    if not target_movie.tmdb_id:
        if tmdb_id_to_set:
            target_movie.tmdb_id = tmdb_id_to_set
            updated = True
            logger.debug(f"Set tmdb_id {tmdb_id_to_set} on movie {target_movie.id}")
        elif source_movie.tmdb_id:
            target_movie.tmdb_id = source_movie.tmdb_id
            updated = True
            logger.debug(f"Merged tmdb_id from movie {source_movie.id} to {target_movie.id}")

    if not target_movie.imdb_id:
        if imdb_id_to_set:
            target_movie.imdb_id = imdb_id_to_set
            updated = True
            logger.debug(f"Set imdb_id {imdb_id_to_set} on movie {target_movie.id}")
        elif source_movie.imdb_id:
            target_movie.imdb_id = source_movie.imdb_id
            updated = True
            logger.debug(f"Merged imdb_id from movie {source_movie.id} to {target_movie.id}")

    # Merge custom properties
    target_props = target_movie.custom_properties or {}
    source_props = source_movie.custom_properties or {}

    for key, value in source_props.items():
        if value and not target_props.get(key):
            target_props[key] = value
            updated = True
            logger.debug(f"Merged custom property '{key}' from movie {source_movie.id} to {target_movie.id}")

    if updated:
        target_movie.custom_properties = target_props
        target_movie.save()
        logger.info(f"Successfully merged data from movie {source_movie.id} into {target_movie.id}")


def handle_series_id_conflicts(current_series, relation, tmdb_id_to_set, imdb_id_to_set):
    """
    Handle potential duplicate key conflicts when setting tmdb_id or imdb_id for series.

    Since this is called when a user is actively accessing series details, we always
    preserve the current series (user's selection) and merge the existing one into it.
    This prevents breaking the user's current viewing experience.

    Returns:
        tuple: (series_to_use, relation_was_updated)
    """
    from django.db import IntegrityError

    existing_series_with_tmdb = None
    existing_series_with_imdb = None

    # Check for existing series with these IDs
    if tmdb_id_to_set:
        try:
            existing_series_with_tmdb = Series.objects.get(
                tmdb_id=tmdb_id_to_set, language=current_series.language
            )
        except Series.DoesNotExist:
            pass

    if imdb_id_to_set:
        try:
            existing_series_with_imdb = Series.objects.get(
                imdb_id=imdb_id_to_set, language=current_series.language
            )
        except Series.DoesNotExist:
            pass

    # If no conflicts, proceed normally
    if not existing_series_with_tmdb and not existing_series_with_imdb:
        return current_series, False

    # Determine which existing series has the conflicting ID (prefer TMDB match)
    existing_series = existing_series_with_tmdb or existing_series_with_imdb

    # CRITICAL: Check if the existing series is actually the same as the current series
    # This can happen if the current series already has the ID we're trying to set
    if existing_series.id == current_series.id:
        logger.debug(f"Current series {current_series.id} already has the target ID, no conflict resolution needed")
        return current_series, False

    logger.info(f"ID conflict detected: Merging existing series '{existing_series.name}' (ID: {existing_series.id}) into current series '{current_series.name}' (ID: {current_series.id}) to preserve user selection")

    # FIRST: Clear the conflicting ID from the existing series before any merging
    if existing_series_with_tmdb and tmdb_id_to_set:
        logger.info(f"Clearing tmdb_id from existing series {existing_series.id} to avoid constraint violation")
        existing_series.tmdb_id = None
        existing_series.save(update_fields=['tmdb_id'])

    if existing_series_with_imdb and imdb_id_to_set:
        logger.info(f"Clearing imdb_id from existing series {existing_series.id} to avoid constraint violation")
        existing_series.imdb_id = None
        existing_series.save(update_fields=['imdb_id'])

    # THEN: Merge data from existing series into current series (now safe to set IDs)
    merge_series_data(source_series=existing_series, target_series=current_series,
                      tmdb_id_to_set=tmdb_id_to_set, imdb_id_to_set=imdb_id_to_set)

    # Transfer all relations from existing series to current series
    existing_relations = existing_series.m3u_relations.all()
    if existing_relations.exists():
        logger.info(f"Transferring {existing_relations.count()} relations from existing series {existing_series.id} to current series {current_series.id}")
        existing_relations.update(series=current_series)

    # Now safe to delete the existing series since all its relations have been transferred
    logger.info(f"Deleting existing series {existing_series.id} '{existing_series.name}' after merging data and transferring relations")
    existing_series.delete()

    return current_series, False  # No relation update needed since we kept current series


def merge_series_data(source_series, target_series, tmdb_id_to_set=None, imdb_id_to_set=None):
    """
    Merge valuable data from source_series into target_series.
    Only overwrites target fields that are empty/None with non-empty source values.

    Args:
        source_series: Series to copy data from
        target_series: Series to copy data to
        tmdb_id_to_set: TMDB ID to set on target (overrides source tmdb_id)
        imdb_id_to_set: IMDB ID to set on target (overrides source imdb_id)
    """
    updated = False

    # Basic fields - only fill if target is empty
    if not target_series.description and source_series.description:
        target_series.description = source_series.description
        updated = True
        logger.debug(f"Merged description from series {source_series.id} to {target_series.id}")

    if not target_series.year and source_series.year:
        target_series.year = source_series.year
        updated = True
        logger.debug(f"Merged year from series {source_series.id} to {target_series.id}")

    if not target_series.rating and source_series.rating:
        target_series.rating = source_series.rating
        updated = True
        logger.debug(f"Merged rating from series {source_series.id} to {target_series.id}")

    if not target_series.genre and source_series.genre:
        target_series.genre = source_series.genre
        updated = True
        logger.debug(f"Merged genre from series {source_series.id} to {target_series.id}")

    if not target_series.logo and source_series.logo:
        target_series.logo = source_series.logo
        updated = True
        logger.debug(f"Merged logo from series {source_series.id} to {target_series.id}")

    # Handle external IDs - use the specific IDs we want to set, or fall back to source
    if not target_series.tmdb_id:
        if tmdb_id_to_set:
            target_series.tmdb_id = tmdb_id_to_set
            updated = True
            logger.debug(f"Set tmdb_id {tmdb_id_to_set} on series {target_series.id}")
        elif source_series.tmdb_id:
            target_series.tmdb_id = source_series.tmdb_id
            updated = True
            logger.debug(f"Merged tmdb_id from series {source_series.id} to {target_series.id}")

    if not target_series.imdb_id:
        if imdb_id_to_set:
            target_series.imdb_id = imdb_id_to_set
            updated = True
            logger.debug(f"Set imdb_id {imdb_id_to_set} on series {target_series.id}")
        elif source_series.imdb_id:
            target_series.imdb_id = source_series.imdb_id
            updated = True
            logger.debug(f"Merged imdb_id from series {source_series.id} to {target_series.id}")

    # Merge custom properties
    target_props = target_series.custom_properties or {}
    source_props = source_series.custom_properties or {}

    for key, value in source_props.items():
        if value and not target_props.get(key):
            target_props[key] = value
            updated = True
            logger.debug(f"Merged custom property '{key}' from series {source_series.id} to {target_series.id}")

    if updated:
        target_series.custom_properties = target_props
        target_series.save()
        logger.info(f"Successfully merged data from series {source_series.id} into {target_series.id}")


def is_non_empty_string(value):
    """
    Helper function to safely check if a value is a non-empty string.
    Returns True only if value is a string and has non-whitespace content.
    """
    return isinstance(value, str) and value.strip()


def extract_string_from_array_or_string(value):
    """
    Helper function to extract a string value from either a string or array.
    Returns the first non-null string from an array, or the string itself.
    Returns None if no valid string is found.
    """
    if isinstance(value, str):
        return value.strip() if value.strip() else None
    elif isinstance(value, list) and value:
        # Find first non-null, non-empty string in the array
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
            elif item is not None and str(item).strip():
                return str(item).strip()
    return None


def clean_custom_properties(custom_props):
    """
    Remove null, empty, or invalid values from custom_properties dict.
    Only keeps properties that have meaningful values.
    """
    if not custom_props:
        return None

    cleaned = {}
    for key, value in custom_props.items():
        # Handle fields that should extract clean strings
        if key in ['youtube_trailer', 'actors', 'director', 'cast']:
            clean_value = extract_string_from_array_or_string(value)
            if clean_value:
                cleaned[key] = clean_value
        # Handle backdrop_path which should remain as array format
        elif key == 'backdrop_path':
            clean_value = extract_string_from_array_or_string(value)
            if clean_value:
                cleaned[key] = [clean_value]
        else:
            # For other properties, keep them if they're not None and not empty
            if value is not None and value != '' and value != []:
                # If it's a list with only null values, skip it
                if isinstance(value, list) and all(item is None for item in value):
                    continue
                cleaned[key] = value

    return cleaned if cleaned else None


def should_update_field(existing_value, new_value):
    """
    Helper function to determine if we should update a field.
    Returns True if:
    - new_value is a non-empty string (or contains one if it's an array) AND
    - existing_value is None, empty string, array with null/empty values, or non-string
    """
    # Extract actual string values from arrays if needed
    new_string = extract_string_from_array_or_string(new_value)
    existing_string = extract_string_from_array_or_string(existing_value)

    return new_string is not None and (existing_string is None or not existing_string)


def movie_relation_has_cached_advanced_data(relation):
    custom_props = relation.custom_properties or {}
    detailed_info = custom_props.get("detailed_info") or {}
    detailed_fetched = bool(custom_props.get("detailed_fetched"))
    return detailed_fetched and isinstance(detailed_info, dict) and bool(detailed_info)


def is_blank_vod_value(value):
    """Return True for None, empty string, empty list, or all-null/empty list items."""
    if value is None or value == '' or value == []:
        return True
    if isinstance(value, list) and all(item is None or item == '' for item in value):
        return True
    return False


def should_apply_provider_list_field(existing_value, new_value):
    """Return True when a non-blank list-API value should replace the stored field.

    Blank or missing provider values are ignored so detail filled from
    get_vod_info is not cleared by sparse get_vod_streams / get_series rows.
    """
    if is_blank_vod_value(new_value):
        return False
    return existing_value != new_value


def merge_blank_vod_list_props(existing_props, incoming_props):
    """Fill blank keys on existing_props from incoming_props (in place)."""
    for field, value in incoming_props.items():
        if field == 'custom_properties':
            existing_cp = existing_props.get('custom_properties') or {}
            incoming_cp = value or {}
            merged = dict(existing_cp)
            for k, v in incoming_cp.items():
                if not is_blank_vod_value(v) and is_blank_vod_value(merged.get(k)):
                    merged[k] = v
            existing_props['custom_properties'] = merged or None
        elif field not in existing_props or (
            is_blank_vod_value(existing_props.get(field)) and not is_blank_vod_value(value)
        ):
            existing_props[field] = value


def build_movie_list_props(movie_data, name, year, tmdb_id, imdb_id, language=''):
    """Build Movie list-sync props and logo URL from a provider row."""
    description = movie_data.get('description') or movie_data.get('plot') or ''
    rating = normalize_rating(movie_data.get('rating') or movie_data.get('vote_average'))
    # genre (and sometimes category_name) can exceed varchar(255); clamp so
    # bulk_create inside the atomic movie batch cannot roll back the chunk.
    genre = truncate_with_warning(
        movie_data.get('genre') or movie_data.get('category_name') or '',
        max_length=Movie._meta.get_field('genre').max_length,
        label='Movie genre',
    )
    duration_secs = extract_duration_from_data(movie_data)
    trailer_raw = movie_data.get('trailer') or movie_data.get('youtube_trailer') or ''
    trailer = extract_string_from_array_or_string(trailer_raw) if trailer_raw else None
    logo_url = movie_data.get('stream_icon') or ''

    director = extract_string_from_array_or_string(
        movie_data.get('director') or ''
    )
    actors_raw = movie_data.get('actors') or movie_data.get('cast') or ''
    if isinstance(actors_raw, list):
        actors = ', '.join(s.strip() for s in actors_raw if s and str(s).strip()) or None
    else:
        actors = actors_raw.strip() if actors_raw else None
    release_date = movie_data.get('release_date') or movie_data.get('releasedate') or ''

    custom_props = {}
    if trailer:
        custom_props['youtube_trailer'] = trailer
    if director:
        custom_props['director'] = director
    if actors:
        custom_props['actors'] = actors
    if release_date:
        custom_props['release_date'] = release_date

    movie_props = {
        'name': name,
        'year': year,
        'tmdb_id': tmdb_id,
        'imdb_id': imdb_id,
        'language': language,
        'description': description,
        'rating': rating,
        'genre': genre,
        'duration_secs': duration_secs,
        'custom_properties': custom_props or None,
    }
    # Only set is_adult when the provider actually reports it. Movies are
    # shared across providers (matched by TMDB/IMDB/name+year), and many
    # providers omit this key entirely; defaulting it to False here would
    # let a sparse provider row silently clear a flag another provider set.
    if 'is_adult' in movie_data:
        movie_props['is_adult'] = parse_is_adult(movie_data['is_adult'])

    return movie_props, logo_url


def build_series_list_props(series_data, name, year, tmdb_id, imdb_id, language=''):
    """Build Series list-sync props and logo URL from a provider row."""
    description = series_data.get('description') or series_data.get('plot') or ''
    rating = normalize_rating(series_data.get('rating'))
    # Same varchar(255) limit as Movie.genre; clamp before bulk_create.
    genre = truncate_with_warning(
        series_data.get('genre', '') or '',
        max_length=Series._meta.get_field('genre').max_length,
        label='Series genre',
    )
    logo_url = series_data.get('cover') or ''

    additional_metadata = {}
    for key in ['backdrop_path', 'poster_path', 'original_name', 'first_air_date', 'last_air_date',
               'episode_run_time', 'status', 'type', 'cast', 'director', 'country', 'language',
               'releaseDate', 'release_date', 'youtube_trailer', 'category_id', 'age', 'seasons', 'added']:
        value = series_data.get(key)
        if value:
            if key == 'cast':
                if isinstance(value, list):
                    clean_value = ', '.join(s.strip() for s in value if s and str(s).strip()) or None
                else:
                    clean_value = extract_string_from_array_or_string(value)
                if clean_value:
                    additional_metadata[key] = clean_value
            elif key in ['poster_path', 'youtube_trailer', 'director']:
                clean_value = extract_string_from_array_or_string(value)
                if clean_value:
                    additional_metadata[key] = clean_value
            elif key == 'backdrop_path':
                clean_value = extract_string_from_array_or_string(value)
                if clean_value:
                    additional_metadata[key] = [clean_value]
            else:
                if value is not None and value != '' and value != []:
                    additional_metadata[key] = value

    series_props = {
        'name': name,
        'year': year,
        'tmdb_id': tmdb_id,
        'imdb_id': imdb_id,
        'language': language,
        'description': description,
        'rating': rating,
        'genre': genre,
        'custom_properties': additional_metadata if additional_metadata else None,
    }
    return series_props, logo_url


@shared_task
def refresh_movie_advanced_data(m3u_movie_relation_id, force_refresh=False):
    """
    Fetch advanced movie data from provider and update Movie and M3UMovieRelation.

    Skips when detailed_fetched is set and last_advanced_refresh is within 24h,
    unless force_refresh is True.
    """
    try:
        relation = M3UMovieRelation.objects.select_related(
            'movie', 'm3u_account__user_agent'
        ).get(id=m3u_movie_relation_id)
        if not force_refresh and movie_relation_has_cached_advanced_data(relation):
            return "Advanced data already cached, skipping."

        account = relation.m3u_account
        movie = relation.movie

        if account.account_type == M3UAccount.Types.STALKER:
            info = dict((relation.custom_properties or {}).get('detailed_info') or {})
            if not info:
                info = dict((relation.custom_properties or {}).get('basic_data') or {})
            movie_data = dict((relation.custom_properties or {}).get('movie_data') or {})
        else:
            from core.xtream_codes import Client as XtreamCodesClient

            with XtreamCodesClient(
                server_url=account.server_url,
                username=account.username,
                password=account.password,
                user_agent=account.get_user_agent_string()
            ) as client:
                vod_info = client.get_vod_info(relation.stream_id)
                if vod_info and 'info' in vod_info:
                    info_raw = vod_info.get('info', {})

                    # Handle case where 'info' might be a list instead of dict
                    if isinstance(info_raw, list):
                        # If it's a list, try to use the first item or create empty dict
                        info = info_raw[0] if info_raw and isinstance(info_raw[0], dict) else {}
                        logger.warning(f"VOD info for stream {relation.stream_id} returned list instead of dict, using first item")
                    elif isinstance(info_raw, dict):
                        info = info_raw
                    else:
                        info = {}
                        logger.warning(f"VOD info for stream {relation.stream_id} returned unexpected type: {type(info_raw)}")

                    movie_data_raw = vod_info.get('movie_data', {})

                    # Handle case where 'movie_data' might be a list instead of dict
                    if isinstance(movie_data_raw, list):
                        movie_data = movie_data_raw[0] if movie_data_raw and isinstance(movie_data_raw[0], dict) else {}
                        logger.warning(f"VOD movie_data for stream {relation.stream_id} returned list instead of dict, using first item")
                    elif isinstance(movie_data_raw, dict):
                        movie_data = movie_data_raw
                    else:
                        movie_data = {}
                        logger.warning(f"VOD movie_data for stream {relation.stream_id} returned unexpected type: {type(movie_data_raw)}")
                else:
                    info = {}
                    movie_data = {}

        # Update Movie fields if changed
        updated = False
        custom_props = movie.custom_properties or {}
        if info.get('plot') and info.get('plot') != movie.description:
            movie.description = info.get('plot')
            updated = True
        normalized_rating = normalize_rating(info.get('rating'))
        if normalized_rating and normalized_rating != movie.rating:
            movie.rating = normalized_rating
            updated = True
        if info.get('genre') and info.get('genre') != movie.genre:
            movie.genre = truncate_with_warning(
                info.get('genre'),
                max_length=Movie._meta.get_field('genre').max_length,
                label='Movie genre',
            )
            updated = True
        # Keep an existing duration when the provider sends missing or
        # invalid data, including 0. Only apply a successfully extracted value.
        duration_secs = extract_duration_from_data(info)
        if duration_secs is not None and duration_secs != movie.duration_secs:
            movie.duration_secs = duration_secs
            updated = True
        # Check for releasedate or release_date
        release_date_value = info.get('releasedate') or info.get('release_date')
        if release_date_value:
            try:
                year = int(str(release_date_value).split('-')[0])
                if year != movie.year:
                    movie.year = year
                    updated = True
            except Exception:
                pass
        # Handle TMDB/IMDB ID updates with duplicate key protection
        tmdb_id_to_set = info.get('tmdb_id') if info.get('tmdb_id') and info.get('tmdb_id') != movie.tmdb_id else None
        imdb_id_to_set = info.get('imdb_id') if info.get('imdb_id') and info.get('imdb_id') != movie.imdb_id else None

        logger.debug(f"Movie {movie.id} current IDs: tmdb_id={movie.tmdb_id}, imdb_id={movie.imdb_id}")
        logger.debug(f"IDs to set: tmdb_id={tmdb_id_to_set}, imdb_id={imdb_id_to_set}")

        if tmdb_id_to_set or imdb_id_to_set:
            # Check for existing movies with these IDs and handle duplicates
            updated_movie, relation_updated = handle_movie_id_conflicts(
                movie, relation, tmdb_id_to_set, imdb_id_to_set
            )
            if relation_updated:
                # If the relation was updated to point to a different movie,
                # we need to update our reference and continue with that movie
                movie = updated_movie
                logger.info(f"Relation updated, now working with movie {movie.id}")
            else:
                # No relation update, safe to set the IDs
                if tmdb_id_to_set:
                    movie.tmdb_id = tmdb_id_to_set
                    updated = True
                    logger.debug(f"Set tmdb_id {tmdb_id_to_set} on movie {movie.id}")
                if imdb_id_to_set:
                    movie.imdb_id = imdb_id_to_set
                    updated = True
                    logger.debug(f"Set imdb_id {imdb_id_to_set} on movie {movie.id}")
        if should_update_field(custom_props.get('youtube_trailer'), info.get('trailer')):
            custom_props['youtube_trailer'] = extract_string_from_array_or_string(info.get('trailer'))
            updated = True
        if should_update_field(custom_props.get('youtube_trailer'), info.get('youtube_trailer')):
            custom_props['youtube_trailer'] = extract_string_from_array_or_string(info.get('youtube_trailer'))
            updated = True
        if should_update_field(custom_props.get('backdrop_path'), info.get('backdrop_path')):
            backdrop_url = extract_string_from_array_or_string(info.get('backdrop_path'))
            custom_props['backdrop_path'] = [backdrop_url] if backdrop_url else None
            updated = True
        for actors_key in ('actors', 'cast'):
            actors_raw = info.get(actors_key)
            if should_update_field(custom_props.get('actors'), actors_raw):
                if isinstance(actors_raw, list):
                    custom_props['actors'] = ', '.join(s.strip() for s in actors_raw if s and str(s).strip()) or None
                else:
                    custom_props['actors'] = extract_string_from_array_or_string(actors_raw)
                updated = True
                break
        if should_update_field(custom_props.get('director'), info.get('director')):
            custom_props['director'] = extract_string_from_array_or_string(info.get('director'))
            updated = True
        if updated:
            # Clean custom_properties before saving to remove null/empty values
            movie.custom_properties = clean_custom_properties(custom_props)
            try:
                movie.save()
            except Exception as save_error:
                # If we still get an integrity error after our conflict resolution,
                # log it and try to save without the problematic IDs
                logger.error(f"Failed to save movie {movie.id} after conflict resolution: {str(save_error)}")
                if 'tmdb_id' in str(save_error) and movie.tmdb_id:
                    logger.warning(f"Clearing tmdb_id {movie.tmdb_id} from movie {movie.id} due to save error")
                    movie.tmdb_id = None
                if 'imdb_id' in str(save_error) and movie.imdb_id:
                    logger.warning(f"Clearing imdb_id {movie.imdb_id} from movie {movie.id} due to save error")
                    movie.imdb_id = None
                try:
                    movie.save()
                    logger.info(f"Successfully saved movie {movie.id} after clearing problematic IDs")
                except Exception as final_error:
                    logger.error(f"Final save attempt failed for movie {movie.id}: {str(final_error)}")
                    raise

        # Update relation custom_properties and last_advanced_refresh
        relation_custom_props = relation.custom_properties or {}

        # Clean the detailed_info before saving to avoid storing null/empty arrays
        cleaned_info = clean_custom_properties(info) if info else None
        cleaned_movie_data = clean_custom_properties(movie_data) if movie_data else None

        if cleaned_info:
            relation_custom_props['detailed_info'] = cleaned_info
        if cleaned_movie_data:
            relation_custom_props['movie_data'] = cleaned_movie_data
        relation_custom_props['detailed_fetched'] = True

        relation.custom_properties = relation_custom_props
        relation.last_advanced_refresh = timezone.now()
        relation.save(update_fields=['custom_properties', 'last_advanced_refresh'])

        return "Advanced data refreshed."
    except Exception as e:
        logger.error(f"Error refreshing advanced movie data for relation {m3u_movie_relation_id}: {str(e)}")
        return f"Error: {str(e)}"
