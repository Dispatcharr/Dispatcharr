export function librarySearch(query, contentType) {
  const value = query.trim();
  const explicit = value.match(/^tmdb\s*:\s*([1-9][0-9]{0,14})$/i);
  if (explicit) return { tmdb_id: explicit[1] };
  if (/^tmdb\s*:/i.test(value))
    throw new Error('Use a positive numeric ID, for example tmdb:123.');
  if (/^https?:\/\//i.test(value)) {
    const url = new URL(value);
    const match = url.pathname.match(
      /^\/(movie|tv)\/([1-9][0-9]{0,14})(?:-[^/]*)?\/?$/
    );
    if (
      !['www.themoviedb.org', 'themoviedb.org'].includes(url.hostname) ||
      url.username ||
      url.password ||
      !match ||
      match[1] !== (contentType === 'series' ? 'tv' : 'movie')
    )
      throw new Error('Use a title, tmdb:123, or a matching TMDB title link.');
    return { tmdb_id: match[2] };
  }
  if (!value) throw new Error('Enter a title or TMDB ID.');
  return { query: value };
}
