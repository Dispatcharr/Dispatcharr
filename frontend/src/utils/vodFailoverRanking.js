const DEFAULT_VOD_FAILOVER_RANKING = [
  'audio_language',
  'subtitle_language',
  'provider',
  'resolution_desc',
  'metadata_completeness',
];

const normalizeVODFailoverRanking = (ranking = []) => {
  const normalized = ranking.map((key) =>
    key === 'resolution' ? 'resolution_desc' : key
  );
  const resolutionDirection = normalized.find(
    (key) => key === 'resolution_desc' || key === 'resolution_asc'
  );
  const supported = new Set([
    ...DEFAULT_VOD_FAILOVER_RANKING,
    'resolution_asc',
  ]);
  const defaults = DEFAULT_VOD_FAILOVER_RANKING.map((key) =>
    key === 'resolution_desc' && resolutionDirection
      ? resolutionDirection
      : key
  );

  return [...new Set([...normalized, ...defaults])].filter(
    (key) =>
      supported.has(key) &&
      (key !== 'resolution_desc' || resolutionDirection !== 'resolution_asc') &&
      (key !== 'resolution_asc' || resolutionDirection === 'resolution_asc')
  );
};

export { DEFAULT_VOD_FAILOVER_RANKING, normalizeVODFailoverRanking };
