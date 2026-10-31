// Ordered by precedence, matching the backend source metadata resolution.
export const METADATA_ORIGINS = {
  category: { label: 'Category default', color: 'gray' },
  series: { label: 'Series source', color: 'gray' },
  provider: { label: 'Provider', color: 'teal' },
  observed: { label: 'Detected during playback', color: 'violet' },
  manual: { label: 'Manual', color: 'blue' },
};
const RANK = Object.keys(METADATA_ORIGINS);

export const metadataFeatureLabel = (value) =>
  value === 'dv'
    ? 'Dolby Vision'
    : value.startsWith('custom:')
      ? value.slice(7)
      : value.toUpperCase();

/** Provider episode resolutions replace an inherited value of a series source. */
export function sourceMetadataOrigins(source, series = false) {
  const metadata = source?.effective_metadata || {};
  const values = metadata.values || {};
  const provenance = metadata.provenance || {};
  const episodes = series
    ? source?.provider?.technical?.episode_resolutions || []
    : [];
  const origins = {};
  for (const [field, raw] of Object.entries(values)) {
    origins[field] = Object.fromEntries(
      (Array.isArray(raw) ? raw : [raw])
        .filter(Boolean)
        .map((value) => [value, provenance[field]])
    );
  }
  if (
    episodes.length &&
    RANK.indexOf(provenance.resolution) < RANK.indexOf('provider')
  )
    origins.resolution = Object.fromEntries(
      episodes.map((value) => [value, 'provider'])
    );
  return origins;
}
