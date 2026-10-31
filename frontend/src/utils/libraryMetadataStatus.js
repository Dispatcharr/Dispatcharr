export function libraryMetadataStatus(item) {
  switch (item.metadata_status) {
    case 'not_checked':
      return {
        label:
          item.metadata?._lookup_skip_reason === 'year_missing'
            ? 'TMDB search skipped: release year missing'
            : 'TMDB search skipped: title search disabled',
        color: 'dimmed',
      };
    case 'ambiguous':
      return { label: 'Multiple TMDB matches', color: 'orange' };
    case 'not_found':
      return { label: 'No TMDB match found', color: 'orange' };
    case 'failed':
      return { label: 'TMDB lookup failed', color: 'red' };
    default:
      return {
        label: item.tmdb_id ? `TMDB ${item.tmdb_id}` : 'No TMDB ID',
        color: 'dimmed',
      };
  }
}

export function libraryRowTitle(item, sources = false) {
  return (sources ? item.provider_name : item.name) || item.name;
}
