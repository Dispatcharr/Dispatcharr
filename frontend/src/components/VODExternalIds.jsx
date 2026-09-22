import React from 'react';
import { Badge, Group, Text } from '@mantine/core';
import { imdbUrl, tmdbUrl } from '../utils/components/SeriesModalUtils.js';

const LinkedBadge = ({ color, href, children }) => (
  <Badge
    color={color}
    component="a"
    href={href}
    target="_blank"
    rel="noopener noreferrer"
    style={{ cursor: 'pointer' }}
  >
    {children}
  </Badge>
);

const VODExternalIds = ({ contentType, tmdb, tmdbId = '', imdbId = '' }) => {
  const effectiveTmdbId = String(tmdb?.id || tmdbId || '');
  const effectiveImdbId = String(tmdb?.external_ids?.imdb_id || imdbId || '');
  const tvdbId = String(tmdb?.external_ids?.tvdb_id || '');
  const wikidataId = String(tmdb?.external_ids?.wikidata_id || '');

  return (
    <Group gap="xs" wrap="wrap">
      {effectiveTmdbId && (
        <LinkedBadge
          color="cyan"
          href={tmdbUrl(
            effectiveTmdbId,
            contentType === 'series' ? 'tv' : 'movie'
          )}
        >
          TMDB {effectiveTmdbId}
        </LinkedBadge>
      )}
      {effectiveImdbId && (
        <LinkedBadge color="yellow" href={imdbUrl(effectiveImdbId)}>
          IMDb {effectiveImdbId}
        </LinkedBadge>
      )}
      {tvdbId && (
        <LinkedBadge
          color="grape"
          href={`https://thetvdb.com/search?query=${encodeURIComponent(tvdbId)}`}
        >
          TVDB {tvdbId}
        </LinkedBadge>
      )}
      {wikidataId && (
        <LinkedBadge
          color="violet"
          href={`https://www.wikidata.org/wiki/${encodeURIComponent(wikidataId)}`}
        >
          Wikidata {wikidataId}
        </LinkedBadge>
      )}
      {!effectiveTmdbId && !effectiveImdbId && !tvdbId && !wikidataId && (
        <Text size="xs" c="dimmed">
          No external metadata ID
        </Text>
      )}
    </Group>
  );
};

export default VODExternalIds;
