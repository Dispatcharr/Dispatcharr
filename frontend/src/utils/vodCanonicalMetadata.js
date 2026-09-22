export const EMPTY_CANONICAL_METADATA_VALUES = {
  title: '',
  secondary_title: '',
  description: '',
  secondary_description: '',
  year: '',
  release_date: '',
  duration_minutes: '',
  rating: '',
  genre: '',
  age_rating: '',
  director: '',
  actors: '',
  crew: '',
  country: '',
  youtube_trailer: '',
  poster_url: '',
  backdrop_url: '',
  tmdb_id: '',
  imdb_id: '',
  tvdb_id: '',
  wikidata_id: '',
  keywords: [],
  is_anime: false,
  adult: false,
  clean_title: '',
};

export const canonicalMetadataValues = (content = {}) => {
  const tmdb = content.tmdb || {};
  const releaseDate = tmdb.release_date || content.release_date || '';
  const releaseYear = String(releaseDate).match(/^(\d{4})/)?.[1] || '';
  const primaryLanguage =
    tmdb.primary_language || tmdb.languages?.[0] || 'en-US';
  const secondaryLanguage =
    tmdb.secondary_language || tmdb.languages?.[1] || '';
  const primary = tmdb.localized?.[primaryLanguage] || {};
  const secondary = tmdb.localized?.[secondaryLanguage] || {};
  return {
    ...EMPTY_CANONICAL_METADATA_VALUES,
    title: primary.title || content.name || '',
    secondary_title: secondary.title || '',
    description: primary.overview || content.description || '',
    secondary_description: secondary.overview || '',
    year: content.year ? String(content.year) : releaseYear,
    release_date: releaseDate,
    duration_minutes: tmdb.runtime_minutes
      ? String(tmdb.runtime_minutes)
      : content.duration_secs
        ? String(Math.round(content.duration_secs / 60))
        : '',
    rating: String(tmdb.rating || content.rating || ''),
    genre:
      (tmdb.genres || [])
        .map((row) => row.name)
        .filter(Boolean)
        .join(', ') ||
      content.genre ||
      '',
    age_rating: tmdb.age_rating || content.age || '',
    director: tmdb.director || content.director || '',
    actors: tmdb.actors || content.actors || content.cast || '',
    crew: tmdb.crew || content.crew || '',
    country: tmdb.country || content.country || '',
    youtube_trailer: tmdb.youtube_trailer || content.youtube_trailer || '',
    poster_url:
      tmdb.poster_url ||
      content.movie_image ||
      content.series_image ||
      content.logo?.cache_url ||
      content.logo?.url ||
      '',
    backdrop_url: tmdb.backdrop_url || content.backdrop_path?.[0] || '',
    tmdb_id: String(tmdb.id || content.tmdb_id || ''),
    imdb_id: String(tmdb.external_ids?.imdb_id || content.imdb_id || ''),
    tvdb_id: String(tmdb.external_ids?.tvdb_id || ''),
    wikidata_id: String(tmdb.external_ids?.wikidata_id || ''),
    keywords: (tmdb.keywords || [])
      .map((row) => (typeof row === 'string' ? row : row?.name))
      .filter(Boolean),
    is_anime: Boolean(tmdb.is_anime),
    adult: Boolean(tmdb.adult || content.is_adult),
    clean_title: tmdb.clean_title || content.clean_title || '',
  };
};
