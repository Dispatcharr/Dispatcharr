"""External database IDs (TMDB, IMDb, TheTVDB) for Schedules Direct programs."""
from __future__ import annotations

import logging
import os
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

import requests
from django.db.models.fields.json import KeyTextTransform, KeyTransform
from django.utils import timezone

from apps.epg.models import ProgramData, SDSeriesExternalID
from apps.epg.tmdb_match import TMDBAuthError, TMDBClient, match_tmdb
from core.utils import dispatcharr_user_agent

logger = logging.getLogger(__name__)

# Concurrent TMDB searches; keeps well under TMDB's ~50 requests/second.
TMDB_SEARCH_WORKERS = 4
SEARCH_PROGRESS_INTERVAL = 1000
SEARCH_RETRY_INTERVAL = timedelta(days=30)
SEARCH_SHOW_TYPES = {'Series', 'Miniseries'}

# custom_properties key -> SDSeriesExternalID field
PROGRAM_PROPERTY_FIELDS = {
    'themoviedb.org_id': 'tmdb_id',
    'tmdb_type': 'tmdb_type',
    'imdb.com_id': 'imdb_id',
    'thetvdb.com_id': 'tvdb_id',
}


def sd_series_key(program_id):
    """Return the series/movie key for an SD programID, or None.

    Episodes (EP) and series (SH) of the same show share the 8-digit root, so
    both map to ``SH<root>``. Other types keep their own prefix because the
    root number space is not shared (an MV and an SH can have the same root).
    """
    if not program_id or len(program_id) < 10:
        return None
    prefix = program_id[:2]
    if prefix == 'EP':
        prefix = 'SH'
    return prefix + program_id[2:10]


def _session():
    session = requests.Session()
    session.headers['User-Agent'] = dispatcharr_user_agent()
    return session


def _search_profiles(mapped_epg_ids):
    """Collect title, language, countries, years and cast per series/movie key from stored programs."""
    rows = ProgramData.objects.filter(
        epg_id__in=mapped_epg_ids,
        program_id__isnull=False,
    ).annotate(
        cp_categories=KeyTransform('categories', 'custom_properties'),
        cp_country=KeyTextTransform('country', 'custom_properties'),
        cp_date=KeyTextTransform('date', 'custom_properties'),
        cp_language=KeyTextTransform('sd_title_language', 'custom_properties'),
        cp_actors=KeyTransform('actor', KeyTransform('credits', 'custom_properties')),
    ).values('program_id', 'title', 'cp_categories', 'cp_country', 'cp_date', 'cp_language', 'cp_actors')

    profiles = {}
    for row in rows.iterator(chunk_size=5000):
        key = sd_series_key(row['program_id'])
        if not key or key[:2] not in ('SH', 'MV'):
            continue
        p = profiles.setdefault(key, {
            'kind': 'movie' if key.startswith('MV') else 'tv',
            'titles': Counter(), 'language': None, 'countries': set(), 'years': [],
            'cast': Counter(), 'eligible': key.startswith('MV'),
        })
        p['titles'][row['title']] += 1
        p['language'] = row['cp_language'] or p['language']
        if isinstance(row['cp_categories'], list) and SEARCH_SHOW_TYPES & set(row['cp_categories']):
            p['eligible'] = True
        if row['cp_country']:
            p['countries'].update(c.strip() for c in row['cp_country'].split(','))
        date = row['cp_date'] or ''
        if date[:4].isdigit():
            p['years'].append(int(date[:4]))
        for actor in row['cp_actors'] if isinstance(row['cp_actors'], list) else []:
            if isinstance(actor, dict) and actor.get('name') and not actor.get('guest'):
                p['cast'][actor['name']] += 1
    return {k: p for k, p in profiles.items() if p['eligible']}


def _search_one(local, stop, api_key, profile):
    """Run the TMDB match for one profile on this thread's client."""
    if stop.is_set():
        raise TMDBAuthError()
    client = getattr(local, 'client', None)
    if client is None:
        client = local.client = TMDBClient(api_key, session=_session())
    if profile['kind'] == 'movie':
        year = Counter(profile['years']).most_common(1)[0][0] if profile['years'] else None
    else:
        year = min(profile['years']) if profile['years'] else None
    try:
        return match_tmdb(
            client, profile['kind'], profile['titles'].most_common(1)[0][0],
            language=profile['language'],
            countries=profile['countries'],
            year=year,
            cast=[name for name, _ in profile['cast'].most_common(6)],
        )
    except TMDBAuthError:
        stop.set()
        raise


def resolve_by_search(mapped_epg_ids):
    """Match series/movies not yet matched by TMDB search. Returns the count matched."""
    api_key = os.environ.get('TMDB_API_KEY')
    if not api_key:
        return 0
    profiles = _search_profiles(mapped_epg_ids)
    if not profiles:
        return 0
    retry_before = timezone.now() - SEARCH_RETRY_INTERVAL
    done = set(
        SDSeriesExternalID.objects.filter(series_key__in=list(profiles)).exclude(
            tmdb_id__isnull=True, attempted_at__lt=retry_before,
        ).values_list('series_key', flat=True)
    )
    due = [key for key in profiles if key not in done]
    if not due:
        return 0
    logger.info(f"External IDs: searching TMDB for {len(due)} series/movies.")

    local = threading.local()
    stop = threading.Event()
    matched = 0
    searched = 0
    with ThreadPoolExecutor(max_workers=TMDB_SEARCH_WORKERS) as pool:
        futures = {pool.submit(_search_one, local, stop, api_key, profiles[key]): key for key in due}
        for future in as_completed(futures):
            key = futures[future]
            try:
                details, reason = future.result()
            except TMDBAuthError:
                logger.warning("External IDs: TMDB rejected TMDB_API_KEY, skipping TMDB search.")
                pool.shutdown(wait=False, cancel_futures=True)
                break
            except requests.exceptions.RequestException as e:
                logger.warning(f"External IDs: TMDB search failed for {key}: {e}")
                continue
            external = (details or {}).get('external_ids') or {}
            SDSeriesExternalID.objects.update_or_create(
                series_key=key,
                defaults={
                    'tmdb_id': str(details['id']) if details else None,
                    'tmdb_type': profiles[key]['kind'] if details else None,
                    'imdb_id': external.get('imdb_id') or None,
                    'tvdb_id': str(external['tvdb_id']) if external.get('tvdb_id') else None,
                    'attempted_at': timezone.now(),
                },
            )
            if details:
                matched += 1
            searched += 1
            logger.debug(f"External IDs: search {key} -> {reason}")
            if searched % SEARCH_PROGRESS_INTERVAL == 0:
                logger.info(f"External IDs: searched {searched} of {len(due)}, {matched} matched.")
    return matched


def stamp_program_external_ids(mapped_epg_ids):
    """Write cached external IDs into ProgramData.custom_properties. Returns rows updated."""
    by_key = {
        entry['series_key']: {prop: entry[field] for prop, field in PROGRAM_PROPERTY_FIELDS.items()}
        for entry in SDSeriesExternalID.objects.values('series_key', *PROGRAM_PROPERTY_FIELDS.values())
    }
    if not by_key:
        return 0

    annotations = {
        f'cur_{field}': KeyTextTransform(prop, 'custom_properties')
        for prop, field in PROGRAM_PROPERTY_FIELDS.items()
    }
    rows = ProgramData.objects.filter(
        epg_id__in=mapped_epg_ids,
        program_id__isnull=False,
    ).annotate(**annotations).values('id', 'program_id', *annotations)

    wanted_by_row = {}
    for row in rows.iterator(chunk_size=5000):
        wanted = by_key.get(sd_series_key(row['program_id']))
        if wanted is None:
            continue
        current = {
            prop: row[f'cur_{field}'] for prop, field in PROGRAM_PROPERTY_FIELDS.items()
        }
        if current != wanted:
            wanted_by_row[row['id']] = wanted

    if not wanted_by_row:
        return 0

    updated = 0
    row_ids = list(wanted_by_row)
    for i in range(0, len(row_ids), 1000):
        batch = list(
            ProgramData.objects.filter(id__in=row_ids[i:i + 1000]).only('id', 'custom_properties')
        )
        for prog in batch:
            cp = prog.custom_properties or {}
            for prop, value in wanted_by_row[prog.id].items():
                if value:
                    cp[prop] = value
                else:
                    cp.pop(prop, None)
            prog.custom_properties = cp
        ProgramData.objects.bulk_update(batch, ['custom_properties'])
        updated += len(batch)
    return updated


def clear_program_external_ids(mapped_epg_ids):
    """Remove stamped external IDs from SD programs. Returns rows updated."""
    batch = list(
        ProgramData.objects.filter(
            epg_id__in=mapped_epg_ids,
            program_id__isnull=False,
            custom_properties__has_any_keys=list(PROGRAM_PROPERTY_FIELDS),
        ).only('id', 'custom_properties')
    )
    for prog in batch:
        for prop in PROGRAM_PROPERTY_FIELDS:
            prog.custom_properties.pop(prop, None)
    if batch:
        ProgramData.objects.bulk_update(batch, ['custom_properties'], batch_size=1000)
        logger.info(f"External IDs: disabled, removed IDs from {len(batch)} programs.")
    return len(batch)


def update_sd_external_ids(mapped_epg_ids, is_enabled=None):
    """Match series/movies on TMDB and stamp the IDs onto programs. Returns rows updated.

    ``is_enabled`` is checked again before stamping so a source switched off
    during the search is left clear.
    """
    if not os.environ.get('TMDB_API_KEY'):
        return 0
    matched = resolve_by_search(mapped_epg_ids)
    if is_enabled is not None and not is_enabled():
        logger.info("External IDs: disabled during TMDB search, not stamping.")
        return 0
    stamped = stamp_program_external_ids(mapped_epg_ids)
    logger.info(f"External IDs: {matched} matched by TMDB search, {stamped} programs updated.")
    return stamped
