export const imdbUrl = (imdb_id) =>
  imdb_id ? `https://www.imdb.com/title/${imdb_id}` : '';

export const tmdbUrl = (tmdb_id, type = 'movie') =>
  tmdb_id ? `https://www.themoviedb.org/${type}/${tmdb_id}` : '';

export const formatDuration = (seconds) => {
  if (!seconds) return '';
  const hours = Math.floor(seconds / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  return hours > 0 ? `${hours}h ${mins}m` : `${mins}m ${secs}s`;
};

export const formatStreamLabel = (relation) => {
  const provider = relation.m3u_account.name;
  const streamId = relation.stream_id;
  const quality = extractQuality(relation);

  return `${provider}${quality ?? ''}${streamId ? ` (Stream ${streamId})` : ''}`;
};

const extractQuality = (relation) => {
  // 1. Primary: Backend quality_info field
  const fromQualityInfo = getQualityFromBackend(relation.quality_info);
  if (fromQualityInfo) return fromQualityInfo;

  // 2. Secondary: Custom properties detailed_info
  if (relation.custom_properties?.detailed_info) {
    const fromDetailedInfo = getQualityFromDetailedInfo(relation.custom_properties.detailed_info);
    if (fromDetailedInfo) return fromDetailedInfo;
  }

  // 3. Fallback: Stream name
  if (relation.stream_name) {
    return getQualityFromStreamName(relation.stream_name);
  }

  return '';
};

const getQualityFromBackend = (qualityInfo) => {
  if (!qualityInfo) return '';

  if (qualityInfo.quality) {
    return ` - ${qualityInfo.quality}`;
  } else if (qualityInfo.resolution) {
    return ` - ${qualityInfo.resolution}`;
  } else if (qualityInfo.bitrate) {
    return ` - ${qualityInfo.bitrate}`;
  }
  return '';
};

const getQualityFromDetailedInfo = (detailedInfo) => {
  // Check video dimensions first
  if (detailedInfo.video?.width && detailedInfo.video?.height) {
    return getQualityInfoFromDimensions(detailedInfo.video.width, detailedInfo.video.height);
  }

  // Check name field
  if (detailedInfo.name) {
    return parseQualityFromText(detailedInfo.name);
  }

  return '';
};

const getQualityFromStreamName = (streamName) => {
  return parseQualityFromText(streamName);
};

const parseQualityFromText = (text) => {
  if (text.includes('4K') || text.includes('2160p')) return ' - 4K';
  if (text.includes('1080p') || text.includes('FHD')) return ' - 1080p';
  if (text.includes('720p') || text.includes('HD')) return ' - 720p';
  if (text.includes('480p')) return ' - 480p';
  return '';
};

const getQualityInfoFromDimensions = (width, height) => {
  // Prioritize width for quality detection (handles ultrawide/cinematic aspect ratios)
  if (width >= 3840) {
    return ' - 4K';
  } else if (width >= 1920) {
    return ' - 1080p';
  } else if (width >= 1280) {
    return ' - 720p';
  } else if (width >= 854) {
    return ' - 480p';
  } else {
    return ` - ${width}x${height}`;
  }
}

export const sortEpisodesList = (episodesList) => {
  return episodesList.sort((a, b) => {
    if (a.season_number !== b.season_number) {
      return (a.season_number || 0) - (b.season_number || 0);
    }
    return (a.episode_number || 0) - (b.episode_number || 0);
  });
};

export const groupEpisodesBySeason = (seriesEpisodes) => {
  const grouped = {};
  seriesEpisodes.forEach((episode) => {
    const season = episode.season_number || 1;
    if (!grouped[season]) {
      grouped[season] = [];
    }
    grouped[season].push(episode);
  });
  return grouped;
};

export const sortBySeasonNumber = (episodesBySeason) => {
  return Object.keys(episodesBySeason)
    .map(Number)
    .sort((a, b) => a - b);
};

export const getEpisodeStreamUrl = (episode, selectedProvider, env_mode) => {
  let streamUrl = `/proxy/vod/episode/${episode.uuid}`;

  // Add selected provider as query parameter if available
  if (selectedProvider) {
    // Use stream_id for most specific selection, fallback to account_id
    if (selectedProvider.stream_id) {
      streamUrl += `?stream_id=${encodeURIComponent(selectedProvider.stream_id)}`;
    } else {
      streamUrl += `?m3u_account_id=${selectedProvider.m3u_account.id}`;
    }
  }

  if (env_mode === 'dev') {
    streamUrl = `${window.location.protocol}//${window.location.hostname}:5656${streamUrl}`;
  } else {
    streamUrl = `${window.location.origin}${streamUrl}`;
  }
  return streamUrl;
};

// Helper to get embeddable YouTube URL
export const getYouTubeEmbedUrl = (url) => {
  if (!url) return '';
  // Accepts full YouTube URLs or just IDs
  const match = url.match(/(?:youtube\.com\/watch\?v=|youtu\.be\/)([\w-]+)/);
  const videoId = match ? match[1] : url;
  return `https://www.youtube.com/embed/${videoId}`;
};

export const getEpisodeAirdate = (episode) => {
  return episode.air_date
    ? new Date(episode.air_date).toLocaleDateString()
    : 'N/A';
};

export const getTmdbUrlLink = (displaySeries, episode) => {
  return (
    tmdbUrl(displaySeries.tmdb_id, 'tv') +
    (episode.season_number && episode.episode_number
      ? `/season/${episode.season_number}/episode/${episode.episode_number}`
      : '')
  );
};
