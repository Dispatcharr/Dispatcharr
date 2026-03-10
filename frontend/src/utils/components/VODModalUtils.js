const hasValidTechnicalDetails = (obj) => {
  return obj?.bitrate || obj?.video || obj?.audio;
};

const extractFromDetailedInfo = (customProperties) => {
  const detailedInfo = customProperties?.detailed_info;
  if (!detailedInfo) return null;

  return {
    bitrate: detailedInfo.bitrate || null,
    video: detailedInfo.video || null,
    audio: detailedInfo.audio || null,
  };
};

export const getTechnicalDetails = (selectedProvider, defaultVOD) => {
  if (!selectedProvider) {
    return {
      bitrate: defaultVOD?.bitrate,
      video: defaultVOD?.video,
      audio: defaultVOD?.audio,
    };
  }

  // Try movie/episode content first
  const content = selectedProvider.movie || selectedProvider.episode;
  if (content && hasValidTechnicalDetails(content)) {
    return {
      bitrate: content.bitrate,
      video: content.video,
      audio: content.audio,
    };
  }

  // Try provider object directly
  if (hasValidTechnicalDetails(selectedProvider)) {
    return {
      bitrate: selectedProvider.bitrate,
      video: selectedProvider.video,
      audio: selectedProvider.audio,
    };
  }

  // Try custom_properties.detailed_info
  const detailedInfo = extractFromDetailedInfo(
    selectedProvider.custom_properties
  );
  if (detailedInfo && hasValidTechnicalDetails(detailedInfo)) {
    return detailedInfo;
  }

  // Fallback to defaultVOD
  return {
    bitrate: defaultVOD?.bitrate,
    video: defaultVOD?.video,
    audio: defaultVOD?.audio,
  };
};

export const getMovieStreamUrl = (vod, selectedProvider, env_mode) => {
  let streamUrl = `/proxy/vod/movie/${vod.uuid}`;

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

export const formatVideoDetails = (video) => {
  const parts = [];

  const codec =
    video.codec_long_name && video.codec_long_name !== 'unknown'
      ? video.codec_long_name
      : video.codec_name;
  parts.push(codec);

  if (video.profile) parts.push(`(${video.profile})`);
  if (video.width && video.height) parts.push(`${video.width}x${video.height}`);
  if (video.display_aspect_ratio)
    parts.push(`Aspect Ratio: ${video.display_aspect_ratio}`);
  if (video.bit_rate)
    parts.push(`Bitrate: ${Math.round(Number(video.bit_rate) / 1000)} kbps`);
  if (video.r_frame_rate) parts.push(`Frame Rate: ${video.r_frame_rate} fps`);
  if (video.tags?.encoder) parts.push(`Encoder: ${video.tags.encoder}`);

  return parts.join(', ');
};

export const formatAudioDetails = (audio) => {
  const parts = [];

  const codec =
    audio.codec_long_name && audio.codec_long_name !== 'unknown'
      ? audio.codec_long_name
      : audio.codec_name;
  parts.push(codec);

  if (audio.profile) parts.push(`(${audio.profile})`);

  const channels =
    audio.channel_layout || (audio.channels ? `${audio.channels}` : null);
  if (channels) parts.push(`Channels: ${channels}`);

  if (audio.sample_rate) parts.push(`Sample Rate: ${audio.sample_rate} Hz`);
  if (audio.bit_rate)
    parts.push(`Bitrate: ${Math.round(Number(audio.bit_rate) / 1000)} kbps`);
  if (audio.tags?.handler_name)
    parts.push(`Handler: ${audio.tags.handler_name}`);

  return parts.join(', ');
};
