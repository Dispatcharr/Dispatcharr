import API from '../../api.js';

export const getFilteredLogos = (logos, debouncedNameFilter, filtersUsed) => {
  // Apply filters
  let filteredLogos = Object.values(logos || {});

  if (debouncedNameFilter) {
    filteredLogos = filteredLogos.filter((logo) =>
      logo.name.toLowerCase().includes(debouncedNameFilter.toLowerCase())
    );
  }

  if (filtersUsed === 'used') {
    filteredLogos = filteredLogos.filter((logo) => logo.is_used);
  } else if (filtersUsed === 'unused') {
    filteredLogos = filteredLogos.filter((logo) => !logo.is_used);
  }

  return filteredLogos.sort((a, b) => a.id - b.id);
};

export const deleteLogo = (id, deleteFile) => {
  return API.deleteLogo(id, deleteFile);
};
export const deleteLogos = (ids, deleteFiles) => {
  return API.deleteLogos(ids, deleteFiles);
};
export const cleanupUnusedLogos = (deleteFiles) => {
  return API.cleanupUnusedLogos(deleteFiles);
};

// Generate smart label based on usage
const categorizeUsage = (names) => {
  const types = { channels: 0, movies: 0, series: 0 };

  names.forEach((name) => {
    if (name.startsWith('Channel:')) types.channels++;
    else if (name.startsWith('Movie:')) types.movies++;
    else if (name.startsWith('Series:')) types.series++;
  });

  return types;
};

// Analyze channel_names to categorize types
export const generateUsageLabel = (channelNames, channelCount) => {
  const types = categorizeUsage(channelNames);
  const typeCount = Object.values(types).filter(
    (count) => count > 0
  ).length;
  if (typeCount === 1) {
    // Only one type - be specific
    if (types.channels > 0)
      return `${types.channels} ${types.channels !== 1 ? 'channels' : 'channel'}`;
    if (types.movies > 0)
      return `${types.movies} ${types.movies !== 1 ? 'movies' : 'movie'}`;
    if (types.series > 0) return `${types.series} series`;
  } else {
    // Multiple types - use generic "items"
    return `${channelCount} ${channelCount !== 1 ? 'items' : 'item'}`;
  }
};