import { describe, expect, it } from 'vitest';
import { librarySearch } from '../librarySearch.js';
import { libraryFieldError } from '../libraryFeedback.js';

describe('Library title and ID lookup', () => {
  it('preserves numeric titles such as 2012', () => {
    expect(librarySearch(' 2012 ', 'movie')).toEqual({ query: '2012' });
    expect(librarySearch('Blade Runner 2049', 'movie')).toEqual({
      query: 'Blade Runner 2049',
    });
  });
  it('accepts explicit IDs and official matching title links', () => {
    expect(librarySearch('TMDB: 123', 'movie')).toEqual({ tmdb_id: '123' });
    expect(
      librarySearch('https://www.themoviedb.org/movie/123-title', 'movie')
    ).toEqual({ tmdb_id: '123' });
    expect(
      librarySearch('https://www.themoviedb.org/tv/456', 'series')
    ).toEqual({ tmdb_id: '456' });
  });
  it.each([
    '',
    'tmdb:0',
    'tmdb:no',
    'https://example.com/movie/123',
    'https://www.themoviedb.org/tv/123',
    'https://name:secret@www.themoviedb.org/movie/123',
  ])('rejects malformed or mismatched identifiers: %s', (query) => {
    expect(() => librarySearch(query, 'movie')).toThrow();
  });
  it('marks the rejected field without marking unrelated fields', () => {
    const error = { body: { metadata: { release_date: ['Invalid date.'] } } };
    expect(libraryFieldError(error, 'metadata.release_date')).toBe(true);
    expect(libraryFieldError(error, 'display_name')).toBe(false);
    expect(libraryFieldError(new Error('Unavailable'), 'display_name')).toBe(
      true
    );
    expect(libraryFieldError(null, 'display_name')).toBe(false);
  });
});
