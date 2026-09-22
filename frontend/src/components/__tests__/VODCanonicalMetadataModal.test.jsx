import { describe, expect, it } from 'vitest';
import { canonicalMetadataValues } from '../../utils/vodCanonicalMetadata.js';

describe('VODCanonicalMetadataModal metadata values', () => {
  it('derives the editable year from a loaded TMDB release date', () => {
    expect(
      canonicalMetadataValues({
        tmdb: {
          release_date: '2021-02-05',
          localized: { 'en-US': { title: 'Bliss' } },
          languages: ['en-US'],
        },
      })
    ).toMatchObject({
      title: 'Bliss',
      year: '2021',
      release_date: '2021-02-05',
    });
  });

  it('keeps an explicitly stored canonical year', () => {
    expect(
      canonicalMetadataValues({
        year: 2020,
        tmdb: { release_date: '2021-02-05' },
      }).year
    ).toBe('2020');
  });

  it('uses the language order included in the canonical detail response', () => {
    expect(
      canonicalMetadataValues({
        tmdb: {
          primary_language: 'de-DE',
          secondary_language: 'en-US',
          localized: {
            'de-DE': { title: 'Deutscher Titel' },
            'en-US': { title: 'English title' },
          },
        },
      })
    ).toMatchObject({
      title: 'Deutscher Titel',
      secondary_title: 'English title',
    });
  });
});
