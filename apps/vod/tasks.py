from celery import shared_task, current_app, group
from django.utils import timezone
from django.db import transaction, IntegrityError
from django.db.models import Q
from apps.m3u.models import M3UAccount
from core.xtream_codes import Client as XtreamCodesClient
from .models import (
    VODCategory, Series, Movie, Episode, VODLogo,
    M3USeriesRelation, M3UMovieRelation, M3UEpisodeRelation, M3UVODCategoryRelation
)
from datetime import datetime
import logging
import json
import re

logger = logging.getLogger(__name__)


@shared_task
def refresh_vod_content(account_id):
    """Refresh VOD content for an M3U account with batch processing for improved performance"""
    # Import here to avoid circular import
    from apps.m3u.tasks import send_m3u_update

    try:
        account = M3UAccount.objects.get(id=account_id, is_active=True)

        if account.account_type != M3UAccount.Types.XC:
            logger.warning(f"VOD refresh called for non-XC account {account_id}")
            return "VOD refresh only available for XtreamCodes accounts"

        logger.info(f"Starting batch VOD refresh for account {account.name}")
        start_time = timezone.now()

        # Send start notification
        send_m3u_update(account_id, "vod_refresh", 0, status="processing")

        with XtreamCodesClient(
            account.server_url,
            account.username,
            account.password,
            account.get_user_agent().user_agent
        ) as client:

            movie_categories, series_categories = refresh_categories(account.id, client)

            logger.debug("Fetching relations for filtering category filtering")
            relations = { rel.category_id: rel for rel in M3UVODCategoryRelation.objects
                .filter(m3u_account=account)
                .select_related("category", "m3u_account")
            }

            # Refresh movies with batch processing (pass scan start time)
            refresh_movies(client, account, movie_categories, relations, scan_start_time=start_time)

            # Refresh series with batch processing (pass scan start time)
            refresh_series(client, account, series_categories, relations, scan_start_time=start_time)

        end_time = timezone.now()
        duration = (end_time - start_time).total_seconds()

        logger.info(f"Batch VOD refresh completed for account {account.name} in {duration:.2f} seconds")

        # Cleanup orphaned VOD content after refresh (scoped to this account only)
        logger.info(f"Starting cleanup of orphaned VOD content for account {account.name}")
        cleanup_result = cleanup_orphaned_vod_content(account_id=account_id, scan_start_time=start_time)
        logger.info(f"VOD cleanup completed: {cleanup_result}")

        # Send completion notification
        send_m3u_update(account_id, "vod_refresh", 100, status="success",
                       message=f"VOD refresh completed in {duration:.2f} seconds")

        return f"Batch VOD refresh completed for account {account.name} in {duration:.2f} seconds"

    except Exception as e:
        logger.error(f"Error refreshing VOD for account {account_id}: {str(e)}")

        # Send error notification
        send_m3u_update(account_id, "vod_refresh", 100, status="error",
                       message=f"VOD refresh failed: {str(e)}")

        return f"VOD refresh failed: {str(e)}"

def refresh_categories(account_id, client=None):
    account = M3UAccount.objects.get(id=account_id, is_active=True)

    if not client:
        client = XtreamCodesClient(
            account.server_url,
            account.username,
            account.password,
            account.get_user_agent().user_agent
        )
    logger.info(f"Refreshing movie categories for account {account.name}")

    # First, get the category list to properly map category IDs and names
    logger.info("Fetching movie categories from provider...")
    categories_data = client.get_vod_categories()
    category_map = batch_create_categories(categories_data, 'movie', account)

    # Create a mapping from provider category IDs to our category objects
    movies_category_id_map = {}
    for cat_data in categories_data:
        cat_name = cat_data.get('category_name', 'Unknown')
        provider_cat_id = cat_data.get('category_id')
        our_category = category_map.get(cat_name)
        if provider_cat_id and our_category:
            movies_category_id_map[str(provider_cat_id)] = our_category

    # Get the category list to properly map category IDs and names
    logger.info("Fetching series categories from provider...")
    categories_data = client.get_series_categories()
    category_map = batch_create_categories(categories_data, 'series', account)

    # Create a mapping from provider category IDs to our category objects
    series_category_id_map = {}
    for cat_data in categories_data:
        cat_name = cat_data.get('category_name', 'Unknown')
        provider_cat_id = cat_data.get('category_id')
        our_category = category_map.get(cat_name)
        if provider_cat_id and our_category:
            series_category_id_map[str(provider_cat_id)] = our_category

    return movies_category_id_map, series_category_id_map

def refresh_movies(client, account, categories_by_provider, relations, scan_start_time=None):
    """Refresh movie content using single API call for all movies"""
    logger.info(f"Refreshing movies for account {account.name}")

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
        process_movie_batch(account, chunk, categories_by_provider, relations, scan_start_time)

    logger.info(f"Completed processing all {total_movies} movies in {total_chunks} chunks")


def refresh_series(client, account, categories_by_provider, relations, scan_start_time=None):
    """Refresh series content using single API call for all series"""
    logger.info(f"Refreshing series for account {account.name}")

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
        process_series_batch(account, chunk, categories_by_provider, relations, scan_start_time)

    logger.info(f"Completed processing all {total_series} series in {total_chunks} chunks")


def batch_create_categories(categories_data, category_type, account):
    """Create categories in batch and return a mapping"""
    category_names = [cat.get('category_name', 'Unknown') for cat in categories_data]

    relations_to_create = []

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

    # Create missing categories in batch
    new_categories = []

    for name in category_names:
        if name not in existing_categories:
            # Always create new categories
            new_categories.append(VODCategory(name=name, category_type=category_type))
        else:
            # Existing category - create relationship with enabled based on auto_enable setting
            # (category exists globally but is new to this account)
            relations_to_create.append(M3UVODCategoryRelation(
                category=existing_categories[name],
                m3u_account=account,
                custom_properties={},
                enabled=auto_enable_new,
            ))

    logger.debug(f"{len(new_categories)} new categories found")
    logger.debug(f"{len(relations_to_create)} existing categories found for account")

    if new_categories:
        logger.debug("Creating new categories...")
        created_categories = list(VODCategory.bulk_create_and_fetch(new_categories, ignore_conflicts=True))

        # Create relations for newly created categories with enabled based on auto_enable setting
        for cat in created_categories:
            if not auto_enable_new:
                logger.info(f"New {category_type} category '{cat.name}' created but DISABLED - auto_enable_new_groups is disabled for account {account.id}")

            relations_to_create.append(
                M3UVODCategoryRelation(
                    category=cat,
                    m3u_account=account,
                    custom_properties={},
                    enabled=auto_enable_new,
                )
            )

        # Convert to dictionary for easy lookup
        newly_created = {cat.name: cat for cat in created_categories}
        existing_categories.update(newly_created)

    # Create missing relations
    logger.debug("Updating category account relations...")
    M3UVODCategoryRelation.objects.bulk_create(relations_to_create, ignore_conflicts=True)

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



@shared_task
def process_movie_batch(account, batch, categories, relations, scan_start_time=None):
    """Process a batch of movies using simple bulk operations like M3U processing"""
    logger.info(f"Processing movie batch of {len(batch)} movies for account {account.name}")

    movies_to_create = []
    movies_to_update = []
    relations_to_create = []
    relations_to_update = []
    movie_keys = {}  # For deduplication like M3U stream_hashes

    # Process each movie in the batch
    for movie_data in batch:
        try:
            stream_id = str(movie_data.get('stream_id'))
            name = movie_data.get('name', 'Unknown')

            # Get category with proper error handling
            category = None

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

            # Extract metadata
            year = extract_year_from_data(movie_data, 'name')
            tmdb_id = movie_data.get('tmdb_id') or movie_data.get('tmdb')
            imdb_id = movie_data.get('imdb_id') or movie_data.get('imdb')

            # Clean empty string IDs
            if tmdb_id == '':
                tmdb_id = None
            if imdb_id == '':
                imdb_id = None

            # Create a unique key for this movie (priority: TMDB > IMDB > name+year)
            if tmdb_id:
                movie_key = f"tmdb_{tmdb_id}"
            elif imdb_id:
                movie_key = f"imdb_{imdb_id}"
            else:
                movie_key = f"name_{name}_{year or 'None'}"

            # Skip duplicates in this batch
            if movie_key in movie_keys:
                continue

            # Prepare movie properties
            description = movie_data.get('description') or movie_data.get('plot') or ''
            rating = normalize_rating(movie_data.get('rating') or movie_data.get('vote_average'))
            genre = movie_data.get('genre') or movie_data.get('category_name') or ''
            duration_secs = extract_duration_from_data(movie_data)
            trailer_raw = movie_data.get('trailer') or movie_data.get('youtube_trailer') or ''
            trailer = extract_string_from_array_or_string(trailer_raw) if trailer_raw else None
            logo_url = movie_data.get('stream_icon') or ''

            movie_props = {
                'name': name,
                'year': year,
                'tmdb_id': tmdb_id,
                'imdb_id': imdb_id,
                'description': description,
                'rating': rating,
                'genre': genre,
                'duration_secs': duration_secs,
                'custom_properties': {'trailer': trailer} if trailer else None,
            }

            movie_keys[movie_key] = {
                'props': movie_props,
                'stream_id': stream_id,
                'category': category,
                'movie_data': movie_data,
                'logo_url': logo_url  # Keep logo URL for later processing
            }

        except Exception as e:
            logger.error(f"Error preparing movie {movie_data.get('name', 'Unknown')}: {str(e)}")

    # Collect all logo URLs and create logos in batch
    logo_urls = set()
    logo_url_to_name = {}  # Map logo URLs to movie names
    for data in movie_keys.values():
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
    tmdb_keys = [k for k in movie_keys.keys() if k.startswith('tmdb_')]
    tmdb_ids = [k.replace('tmdb_', '') for k in tmdb_keys]
    if tmdb_ids:
        for movie in Movie.objects.filter(tmdb_id__in=tmdb_ids):
            existing_movies[f"tmdb_{movie.tmdb_id}"] = movie

    # Query by IMDB IDs
    imdb_keys = [k for k in movie_keys.keys() if k.startswith('imdb_')]
    imdb_ids = [k.replace('imdb_', '') for k in imdb_keys]
    if imdb_ids:
        for movie in Movie.objects.filter(imdb_id__in=imdb_ids):
            existing_movies[f"imdb_{movie.imdb_id}"] = movie

    # Query by name+year for movies without external IDs
    name_year_keys = [k for k in movie_keys.keys() if k.startswith('name_')]
    if name_year_keys:
        for movie in Movie.objects.filter(tmdb_id__isnull=True, imdb_id__isnull=True):
            key = f"name_{movie.name}_{movie.year or 'None'}"
            if key in name_year_keys:
                existing_movies[key] = movie

    # Get existing relations
    stream_ids = [data['stream_id'] for data in movie_keys.values()]
    existing_relations = {
        rel.stream_id: rel for rel in M3UMovieRelation.objects.filter(
            m3u_account=account,
            stream_id__in=stream_ids
        ).select_related('movie')
    }

    # Process each movie
    for movie_key, data in movie_keys.items():
        movie_props = data['props']
        stream_id = data['stream_id']
        category = data['category']
        movie_data = data['movie_data']
        logo_url = data.get('logo_url')

        if movie_key in existing_movies:
            # Update existing movie
            movie = existing_movies[movie_key]
            updated = False

            for field, value in movie_props.items():
                if field == 'custom_properties':
                    if value != movie.custom_properties:
                        movie.custom_properties = value
                        updated = True
                elif getattr(movie, field) != value:
                    setattr(movie, field, value)
                    updated = True

            # Handle logo assignment for existing movies
            logo_updated = False
            if logo_url and len(logo_url) <= 500 and logo_url in existing_logos:
                new_logo = existing_logos[logo_url]
                if movie.logo != new_logo:
                    movie._logo_to_update = new_logo
                    logo_updated = True
            elif (not logo_url or len(logo_url) > 500) and movie.logo:
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

        # Handle relation
        if stream_id in existing_relations:
            # Update existing relation
            relation = existing_relations[stream_id]
            relation.movie = movie
            relation.category = category
            relation.container_extension = movie_data.get('container_extension', 'mp4')
            relation.custom_properties = {
                'basic_data': movie_data,
                'detailed_fetched': False
            }
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
                Movie.objects.bulk_create(movies_to_create, ignore_conflicts=True)

                # Get the newly created movies with their IDs
                # We need to re-fetch them to get the primary keys
                for movie in movies_to_create:
                    # Find the movie by its unique identifiers
                    if movie.tmdb_id:
                        db_movie = Movie.objects.filter(tmdb_id=movie.tmdb_id).first()
                    elif movie.imdb_id:
                        db_movie = Movie.objects.filter(imdb_id=movie.imdb_id).first()
                    else:
                        db_movie = Movie.objects.filter(
                            name=movie.name,
                            year=movie.year,
                            tmdb_id__isnull=True,
                            imdb_id__isnull=True
                        ).first()

                    if db_movie:
                        created_movies[id(movie)] = db_movie

            # Update existing movies
            if movies_to_update:
                # First, update all fields except logo to avoid unsaved related object issues
                Movie.objects.bulk_update(movies_to_update, [
                    'description', 'rating', 'genre', 'year', 'tmdb_id', 'imdb_id',
                    'duration_secs', 'custom_properties'
                ])

                # Handle logo updates separately to avoid bulk_update issues
                for movie in movies_to_update:
                    if hasattr(movie, '_logo_to_update'):
                        movie.logo = movie._logo_to_update
                        movie.save(update_fields=['logo'])

            # Update relations to reference the correct movie objects
            for relation in relations_to_create:
                if id(relation.movie) in created_movies:
                    relation.movie = created_movies[id(relation.movie)]

            # Handle relations
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
def process_series_batch(account, batch, categories, relations, scan_start_time=None):
    """Process a batch of series using simple bulk operations like M3U processing"""
    logger.info(f"Processing series batch of {len(batch)} series for account {account.name}")

    series_to_create = []
    series_to_update = []
    relations_to_create = []
    relations_to_update = []
    series_keys = {}  # For deduplication like M3U stream_hashes

    # Process each series in the batch
    for series_data in batch:
        try:
            series_id = str(series_data.get('series_id'))
            name = series_data.get('name', 'Unknown')

            # Get category with proper error handling
            category = None

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
            year = extract_year(series_data.get('releaseDate', ''))
            if not year and series_data.get('release_date'):
                year = extract_year(series_data.get('release_date'))

            tmdb_id = series_data.get('tmdb') or series_data.get('tmdb_id')
            imdb_id = series_data.get('imdb') or series_data.get('imdb_id')

            # Clean empty string IDs
            if tmdb_id == '':
                tmdb_id = None
            if imdb_id == '':
                imdb_id = None

            # Create a unique key for this series (priority: TMDB > IMDB > name+year)
            if tmdb_id:
                series_key = f"tmdb_{tmdb_id}"
            elif imdb_id:
                series_key = f"imdb_{imdb_id}"
            else:
                series_key = f"name_{name}_{year or 'None'}"

            # Skip duplicates in this batch
            if series_key in series_keys:
                continue

            # Prepare series properties
            description = series_data.get('plot', '')
            rating = normalize_rating(series_data.get('rating'))
            genre = series_data.get('genre', '')
            logo_url = series_data.get('cover') or ''

            # Extract additional metadata for custom_properties
            additional_metadata = {}
            for key in ['backdrop_path', 'poster_path', 'original_name', 'first_air_date', 'last_air_date',
                       'episode_run_time', 'status', 'type', 'cast', 'director', 'country', 'language',
                       'releaseDate', 'youtube_trailer', 'category_id', 'age', 'seasons']:
                value = series_data.get(key)
                if value:
                    # For string-like fields that might be arrays, extract clean strings
                    if key in ['poster_path', 'youtube_trailer', 'cast', 'director']:
                        clean_value = extract_string_from_array_or_string(value)
                        if clean_value:
                            additional_metadata[key] = clean_value
                    elif key == 'backdrop_path':
                        clean_value = extract_string_from_array_or_string(value)
                        if clean_value:
                            additional_metadata[key] = [clean_value]
                    else:
                        # For other fields, keep as-is if not null/empty
                        if value is not None and value != '' and value != []:
                            additional_metadata[key] = value

            series_props = {
                'name': name,
                'year': year,
                'tmdb_id': tmdb_id,
                'imdb_id': imdb_id,
                'description': description,
                'rating': rating,
                'genre': genre,
                'custom_properties': additional_metadata if additional_metadata else None,
            }

            series_keys[series_key] = {
                'props': series_props,
                'series_id': series_id,
                'category': category,
                'series_data': series_data,
                'logo_url': logo_url  # Keep logo URL for later processing
            }

        except Exception as e:
            logger.error(f"Error preparing series {series_data.get('name', 'Unknown')}: {str(e)}")

    # Collect all logo URLs and create logos in batch
    logo_urls = set()
    logo_url_to_name = {}  # Map logo URLs to series names
    for data in series_keys.values():
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
    tmdb_keys = [k for k in series_keys.keys() if k.startswith('tmdb_')]
    tmdb_ids = [k.replace('tmdb_', '') for k in tmdb_keys]
    if tmdb_ids:
        for series in Series.objects.filter(tmdb_id__in=tmdb_ids):
            existing_series[f"tmdb_{series.tmdb_id}"] = series

    # Query by IMDB IDs
    imdb_keys = [k for k in series_keys.keys() if k.startswith('imdb_')]
    imdb_ids = [k.replace('imdb_', '') for k in imdb_keys]
    if imdb_ids:
        for series in Series.objects.filter(imdb_id__in=imdb_ids):
            existing_series[f"imdb_{series.imdb_id}"] = series

    # Query by name+year for series without external IDs
    name_year_keys = [k for k in series_keys.keys() if k.startswith('name_')]
    if name_year_keys:
        for series in Series.objects.filter(tmdb_id__isnull=True, imdb_id__isnull=True):
            key = f"name_{series.name}_{series.year or 'None'}"
            if key in name_year_keys:
                existing_series[key] = series

    # Get existing relations
    series_ids = [data['series_id'] for data in series_keys.values()]
    existing_relations = {
        rel.external_series_id: rel for rel in M3USeriesRelation.objects.filter(
            m3u_account=account,
            external_series_id__in=series_ids
        ).select_related('series')
    }

    # Process each series
    for series_key, data in series_keys.items():
        series_props = data['props']
        series_id = data['series_id']
        category = data['category']
        series_data = data['series_data']
        logo_url = data.get('logo_url')

        if series_key in existing_series:
            # Update existing series
            series = existing_series[series_key]
            updated = False

            for field, value in series_props.items():
                if field == 'custom_properties':
                    if value != series.custom_properties:
                        series.custom_properties = value
                        updated = True
                elif getattr(series, field) != value:
                    setattr(series, field, value)
                    updated = True

            # Handle logo assignment for existing series
            logo_updated = False
            if logo_url and len(logo_url) <= 500 and logo_url in existing_logos:
                new_logo = existing_logos[logo_url]
                if series.logo != new_logo:
                    series._logo_to_update = new_logo
                    logo_updated = True
            elif (not logo_url or len(logo_url) > 500) and series.logo:
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

        # Handle relation
        if series_id in existing_relations:
            # Update existing relation
            relation = existing_relations[series_id]
            relation.series = series
            relation.category = category
            relation.custom_properties = {
                'basic_data': series_data,
                'detailed_fetched': False,
                'episodes_fetched': False
            }
            relation.last_seen = scan_start_time or timezone.now()  # Mark as seen during this scan
            relations_to_update.append(relation)
        else:
            # Create new relation
            relation = M3USeriesRelation(
                m3u_account=account,
                series=series,
                category=category,
                external_series_id=series_id,
                custom_properties={
                    'basic_data': series_data,
                    'detailed_fetched': False,
                    'episodes_fetched': False
                },
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
                Series.objects.bulk_create(series_to_create, ignore_conflicts=True)

                # Get the newly created series with their IDs
                # We need to re-fetch them to get the primary keys
                for series in series_to_create:
                    # Find the series by its unique identifiers
                    if series.tmdb_id:
                        db_series = Series.objects.filter(tmdb_id=series.tmdb_id).first()
                    elif series.imdb_id:
                        db_series = Series.objects.filter(imdb_id=series.imdb_id).first()
                    else:
                        db_series = Series.objects.filter(
                            name=series.name,
                            year=series.year,
                            tmdb_id__isnull=True,
                            imdb_id__isnull=True
                        ).first()

                    if db_series:
                        created_series[id(series)] = db_series

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

            # Update relations to reference the correct series objects
            for relation in relations_to_create:
                if id(relation.series) in created_series:
                    relation.series = created_series[id(relation.series)]

            # Handle relations
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


# Helper functions for year and date extraction

def extract_duration_from_data(movie_data):
    """Extract duration in seconds from movie data"""
    duration_secs = None

    # Try to extract duration from various possible fields
    if movie_data.get('duration_secs'):
        duration_secs = int(movie_data.get('duration_secs'))
    elif movie_data.get('duration'):
        # Handle duration that might be in different formats
        duration_str = str(movie_data.get('duration'))
        if duration_str.isdigit():
            duration_secs = int(duration_str) * 60  # Assume minutes if just a number
        else:
            # Try to parse time format like "01:30:00"
            try:
                time_parts = duration_str.split(':')
                if len(time_parts) == 3:
                    hours, minutes, seconds = map(int, time_parts)
                    duration_secs = (hours * 3600) + (minutes * 60) + seconds
                elif len(time_parts) == 2:
                    minutes, seconds = map(int, time_parts)
                    duration_secs = minutes * 60 + seconds
            except (ValueError, AttributeError):
                pass

    return duration_secs


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


# Episode processing and other advanced features

def refresh_series_episodes(account, series, external_series_id, episodes_data=None):
    """Refresh episodes for a series - only called on-demand"""
    try:
        if not episodes_data:
            # Fetch detailed series info including episodes
            with XtreamCodesClient(
                account.server_url,
                account.username,
                account.password,
                account.get_user_agent().user_agent
            ) as client:
                series_info = client.get_series_info(external_series_id)
                if series_info:
                    # Update series with detailed info
                    info = series_info.get('info', {})
                    if info:
                        # Only update fields if new value is non-empty and either no existing value or existing value is empty
                        updated = False
                        if should_update_field(series.description, info.get('plot')):
                            series.description = extract_string_from_array_or_string(info.get('plot'))
                            updated = True
                        normalized_rating = normalize_rating(info.get('rating'))
                        if normalized_rating and (not series.rating or not str(series.rating).strip()):
                            series.rating = normalized_rating
                            updated = True
                        if should_update_field(series.genre, info.get('genre')):
                            series.genre = extract_string_from_array_or_string(info.get('genre'))
                            updated = True

                        year = extract_year_from_data(info)
                        if year and not series.year:
                            series.year = year
                            updated = True

                        if updated:
                            series.save()

                    episodes_data = series_info.get('episodes', {})
                else:
                    episodes_data = {}

        # Clear existing episodes for this account to handle deletions
        Episode.objects.filter(
            series=series,
            m3u_relations__m3u_account=account
        ).delete()

        # Process all episodes in batch
        batch_process_episodes(account, series, episodes_data)

        # Update the series relation to mark episodes as fetched
        series_relation = M3USeriesRelation.objects.filter(
            series=series,
            m3u_account=account
        ).first()

        if series_relation:
            custom_props = series_relation.custom_properties or {}
            custom_props['episodes_fetched'] = True
            custom_props['detailed_fetched'] = True
            series_relation.custom_properties = custom_props
            series_relation.last_episode_refresh = timezone.now()
            series_relation.save()

    except Exception as e:
        logger.error(f"Error refreshing episodes for series {series.name}: {str(e)}")


def batch_process_episodes(account, series, episodes_data, scan_start_time=None):
    """Process episodes in batches for better performance.

    Note: Multiple streams can represent the same episode (e.g., different languages
    or qualities). Each stream has a unique stream_id, but they share the same
    season/episode number. We create one Episode record per (series, season, episode)
    and multiple M3UEpisodeRelation records pointing to it.
    """
    if not episodes_data:
        return

    # Flatten episodes data
    all_episodes_data = []
    for season_num, season_episodes in episodes_data.items():
        for episode_data in season_episodes:
            episode_data['_season_number'] = int(season_num)
            all_episodes_data.append(episode_data)

    if not all_episodes_data:
        return

    logger.info(f"Batch processing {len(all_episodes_data)} episodes for series {series.name}")

    # Extract episode identifiers
    # Note: episode_keys may have duplicates when multiple streams represent same episode
    episode_keys = set()  # Use set to track unique episode keys
    episode_ids = []
    for episode_data in all_episodes_data:
        season_num = episode_data['_season_number']
        episode_num = episode_data.get('episode_num', 0)
        episode_keys.add((series.id, season_num, episode_num))
        episode_ids.append(str(episode_data.get('id')))

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
            episode_id = str(episode_data.get('id'))
            episode_name = episode_data.get('title', 'Unknown Episode')
            season_number = episode_data['_season_number']
            episode_number = episode_data.get('episode_num', 0)
            info = episode_data.get('info', {})

            # Extract episode metadata
            description = info.get('plot') or info.get('overview', '') if info else ''
            rating = normalize_rating(info.get('rating')) if info else None
            air_date = extract_date_from_data(info) if info else None
            duration_secs = info.get('duration_secs') if info else None
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
                logger.debug(f"Reusing pending episode for S{season_number:02d}E{episode_number:02d} (stream_id: {episode_id})")

            if episode:
                # Update existing episode
                updated = False
                if episode_name != episode.name:
                    episode.name = episode_name
                    updated = True
                if description != episode.description:
                    episode.description = description
                    updated = True
                if rating != episode.rating:
                    episode.rating = rating
                    updated = True
                if air_date != episode.air_date:
                    episode.air_date = air_date
                    updated = True
                if duration_secs != episode.duration_secs:
                    episode.duration_secs = duration_secs
                    updated = True
                if tmdb_id != episode.tmdb_id:
                    episode.tmdb_id = tmdb_id
                    updated = True
                if imdb_id != episode.imdb_id:
                    episode.imdb_id = imdb_id
                    updated = True
                if custom_props != episode.custom_properties:
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
                relation.episode = episode
                relation.container_extension = episode_data.get('container_extension', 'mp4')
                relation.custom_properties = {
                    'info': episode_data,
                    'season_number': season_number
                }
                relation.last_seen = scan_start_time or timezone.now()  # Mark as seen during this scan
                relations_to_update.append(relation)
            else:
                # Create new relation
                relation = M3UEpisodeRelation(
                    m3u_account=account,
                    episode=episode,
                    stream_id=episode_id,
                    container_extension=episode_data.get('container_extension', 'mp4'),
                    custom_properties={
                        'info': episode_data,
                        'season_number': season_number
                    },
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
            M3UEpisodeRelation.objects.bulk_update(relations_to_update, [
                'episode', 'container_extension', 'custom_properties', 'last_seen'
            ])

    logger.info(f"Batch processed episodes: {len(episodes_to_create)} new, {len(episodes_to_update)} updated, "
                f"{len(relations_to_create)} new relations, {len(relations_to_update)} updated relations")


@shared_task
def batch_refresh_series_episodes(account_id, series_ids=None):
    """
    Batch refresh episodes for multiple series.
    If series_ids is None, refresh all series that haven't been refreshed recently.
    """
    try:
        account = M3UAccount.objects.get(id=account_id, is_active=True)

        if account.account_type != M3UAccount.Types.XC:
            logger.warning(f"Episode refresh called for non-XC account {account_id}")
            return "Episode refresh only available for XtreamCodes accounts"

        # Determine which series to refresh
        if series_ids:
            series_relations = M3USeriesRelation.objects.filter(
                m3u_account=account,
                series__id__in=series_ids
            ).select_related('series')
        else:
            # Refresh series that haven't been refreshed in the last 24 hours
            cutoff_time = timezone.now() - timezone.timedelta(hours=24)
            series_relations = M3USeriesRelation.objects.filter(
                m3u_account=account,
                last_episode_refresh__lt=cutoff_time
            ).select_related('series')

        logger.info(f"Batch refreshing episodes for {series_relations.count()} series")

        with XtreamCodesClient(
            account.server_url,
            account.username,
            account.password,
            account.get_user_agent().user_agent
        ) as client:

            refreshed_count = 0
            for relation in series_relations:
                try:
                    refresh_series_episodes(
                        account,
                        relation.series,
                        relation.external_series_id
                    )
                    refreshed_count += 1
                except Exception as e:
                    logger.error(f"Error refreshing episodes for series {relation.series.name}: {str(e)}")

        logger.info(f"Batch episode refresh completed for {refreshed_count} series")
        return f"Batch episode refresh completed for {refreshed_count} series"

    except Exception as e:
        logger.error(f"Error in batch episode refresh for account {account_id}: {str(e)}")
        return f"Batch episode refresh failed: {str(e)}"


@shared_task
def cleanup_orphaned_vod_content(stale_days=0, scan_start_time=None, account_id=None):
    """Clean up VOD content that has no M3U relations or has stale relations"""
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
    stale_movie_count = stale_movie_relations.count()
    stale_movie_relations.delete()

    # Clean up stale series relations
    stale_series_relations = M3USeriesRelation.objects.filter(**base_filters)
    stale_series_count = stale_series_relations.count()
    stale_series_relations.delete()

    # Clean up stale episode relations
    stale_episode_relations = M3UEpisodeRelation.objects.filter(**base_filters)
    stale_episode_count = stale_episode_relations.count()
    stale_episode_relations.delete()

    # Clean up movies with no relations (orphaned)
    # Safe to delete even during account-specific cleanup because if ANY account
    # has a relation, m3u_relations will not be null
    orphaned_movies = Movie.objects.filter(m3u_relations__isnull=True)
    orphaned_movie_count = orphaned_movies.count()
    if orphaned_movie_count > 0:
        logger.info(f"Deleting {orphaned_movie_count} orphaned movies with no M3U relations")
        orphaned_movies.delete()

    # Clean up series with no relations (orphaned)
    orphaned_series = Series.objects.filter(m3u_relations__isnull=True)
    orphaned_series_count = orphaned_series.count()
    if orphaned_series_count > 0:
        logger.info(f"Deleting {orphaned_series_count} orphaned series with no M3U relations")
        orphaned_series.delete()

    # Episodes will be cleaned up via CASCADE when series are deleted

    result = (f"Cleaned up {stale_movie_count} stale movie relations, "
              f"{stale_series_count} stale series relations, "
              f"{stale_episode_count} stale episode relations, "
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
            existing_movie_with_tmdb = Movie.objects.get(tmdb_id=tmdb_id_to_set)
        except Movie.DoesNotExist:
            pass

    if imdb_id_to_set:
        try:
            existing_movie_with_imdb = Movie.objects.get(imdb_id=imdb_id_to_set)
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
            existing_series_with_tmdb = Series.objects.get(tmdb_id=tmdb_id_to_set)
        except Series.DoesNotExist:
            pass

    if imdb_id_to_set:
        try:
            existing_series_with_imdb = Series.objects.get(imdb_id=imdb_id_to_set)
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


@shared_task
def refresh_movie_advanced_data(m3u_movie_relation_id, force_refresh=False):
    """
    Fetch advanced movie data from provider and update Movie and M3UMovieRelation.
    Only fetch if last_advanced_refresh > 24h ago, unless force_refresh is True.
    """
    try:
        relation = M3UMovieRelation.objects.select_related('movie', 'm3u_account').get(id=m3u_movie_relation_id)
        now = timezone.now()
        if not force_refresh and relation.last_advanced_refresh and (now - relation.last_advanced_refresh).total_seconds() < 86400:
            return "Advanced data recently fetched, skipping."

        account = relation.m3u_account
        movie = relation.movie

        from core.xtream_codes import Client as XtreamCodesClient

        with XtreamCodesClient(
            server_url=account.server_url,
            username=account.username,
            password=account.password,
            user_agent=account.get_user_agent().user_agent
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
                    movie.genre = info.get('genre')
                    updated = True
                if info.get('duration_secs'):
                    duration_secs = int(info.get('duration_secs'))
                    if duration_secs != movie.duration_secs:
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
                # Only update trailer if we have a non-empty value and either no existing value or existing value is empty
                if should_update_field(custom_props.get('youtube_trailer'), info.get('trailer')):
                    custom_props['youtube_trailer'] = extract_string_from_array_or_string(info.get('trailer'))
                    updated = True
                if should_update_field(custom_props.get('youtube_trailer'), info.get('youtube_trailer')):
                    custom_props['youtube_trailer'] = extract_string_from_array_or_string(info.get('youtube_trailer'))
                    updated = True
                # Only update backdrop_path if we have a non-empty value and either no existing value or existing value is empty
                if should_update_field(custom_props.get('backdrop_path'), info.get('backdrop_path')):
                    backdrop_url = extract_string_from_array_or_string(info.get('backdrop_path'))
                    custom_props['backdrop_path'] = [backdrop_url] if backdrop_url else None
                    updated = True
                # Only update actors if we have a non-empty value and either no existing value or existing value is empty
                if should_update_field(custom_props.get('actors'), info.get('actors')):
                    custom_props['actors'] = extract_string_from_array_or_string(info.get('actors'))
                    updated = True
                if should_update_field(custom_props.get('actors'), info.get('cast')):
                    custom_props['actors'] = extract_string_from_array_or_string(info.get('cast'))
                    updated = True
                # Only update director if we have a non-empty value and either no existing value or existing value is empty
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
                relation.last_advanced_refresh = now
                relation.save(update_fields=['custom_properties', 'last_advanced_refresh'])

        return "Advanced data refreshed."
    except Exception as e:
        logger.error(f"Error refreshing advanced movie data for relation {m3u_movie_relation_id}: {str(e)}")
        return f"Error: {str(e)}"


def validate_logo_reference(obj, obj_type="object"):
    """
    Validate that a VOD logo reference exists in the database.
    If not, set it to None to prevent foreign key constraint violations.

    Args:
        obj: Object with a logo attribute
        obj_type: String description of the object type for logging

    Returns:
        bool: True if logo was valid or None, False if logo was invalid and cleared
    """
    if not hasattr(obj, 'logo') or not obj.logo:
        return True

    if not obj.logo.pk:
        # Logo doesn't have a primary key, so it's not saved
        obj.logo = None
        return False

    try:
        # Verify the logo exists in the database
        VODLogo.objects.get(pk=obj.logo.pk)
        return True
    except VODLogo.DoesNotExist:
        logger.warning(f"VOD Logo with ID {obj.logo.pk} does not exist in database for {obj_type} '{getattr(obj, 'name', 'Unknown')}', setting to None")
        obj.logo = None
        return False
