export const imdbUrl = (id) => (id ? `https://www.imdb.com/title/${id}` : '');

const TMDB_MEDIA_TYPES = new Set(['movie', 'tv', 'person']);

export const tmdbUrl = (id, mediaType = 'movie') => {
  const type = TMDB_MEDIA_TYPES.has(mediaType) ? mediaType : 'movie';
  return id ? `https://www.themoviedb.org/${type}/${id}` : '';
};
