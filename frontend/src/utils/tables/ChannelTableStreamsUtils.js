import API from '../../api.js';
import { formatBytes } from '../networkUtils.js';
import { formatDuration } from '../dateTimeUtils.js';

const categoryMapping = {
  basic: [
    'resolution',
    'video_codec',
    'source_fps',
    'audio_codec',
    'audio_channels',
  ],
  video: [
    'video_bitrate',
    'pixel_format',
    'width',
    'height',
    'aspect_ratio',
    'frame_rate',
  ],
  audio: [
    'audio_bitrate',
    'sample_rate',
    'audio_format',
    'audio_channels_layout',
  ],
  technical: [
    'stream_type',
    'container_format',
    'duration',
    'file_size',
    'ffmpeg_output_bitrate',
    'input_bitrate',
  ],
  other: [],
};

export const categorizeStreamStats = (stats) => {
  if (!stats)
    return { basic: {}, video: {}, audio: {}, technical: {}, other: {} };

  const categories = {
    basic: {},
    video: {},
    audio: {},
    technical: {},
    other: {},
  };

  Object.entries(stats).forEach(([key, value]) => {
    let categorized = false;
    for (const [category, keys] of Object.entries(categoryMapping)) {
      if (keys.includes(key)) {
        categories[category][key] = value;
        categorized = true;
        break;
      }
    }
    if (!categorized) {
      categories.other[key] = value;
    }
  });

  return categories;
};

export const formatStatValue = (key, value) => {
  if (value === null || value === undefined) return 'N/A';

  switch (key) {
    case 'video_bitrate':
    case 'audio_bitrate':
    case 'ffmpeg_output_bitrate':
      return `${value} kbps`;
    case 'source_fps':
    case 'frame_rate':
      return `${value} fps`;
    case 'sample_rate':
      return `${value} Hz`;
    case 'file_size':
      return typeof value === 'number' ? formatBytes(value) : value;
    case 'duration':
      return typeof value === 'number'
        ? formatDuration(value, { alwaysShowHours: true })
        : value;
    default:
      return value.toString();
  }
};

export const formatStatKey = (key) => {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (l) => l.toUpperCase());
};

export const getChannelStreamStats = (channelId, since, ids) => {
  return API.getChannelStreamStats(channelId, since, ids);
};
export const reorderChannelStreams = (channelId, streamIds) => {
  return API.reorderChannelStreams(channelId, streamIds);
};
