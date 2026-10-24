import MEDIA_LANGUAGE_OPTIONS from '../../../apps/vod/media_languages.json';

export const VOD_METADATA_FIELDS = [
  'audio_languages',
  'subtitle_languages',
  'resolution',
  'video_features',
];

export const VOD_METADATA_LABELS = {
  audio_languages: 'DUB',
  subtitle_languages: 'SUB',
  resolution: 'Resolution',
  video_features: 'Features',
};

export const metadataFieldItems = (values, field) => {
  const value = values?.[field];
  if (field !== 'video_features')
    return Array.isArray(value) ? value : value ? [value] : [];
  return (value || []).map((feature) =>
    feature === 'dv'
      ? 'Dolby Vision'
      : feature.startsWith('custom:')
        ? feature.slice(7)
        : feature.toUpperCase()
  );
};

export const metadataFieldText = (values, field) =>
  metadataFieldItems(values, field).join(', ');

export const VOD_RESOLUTIONS = [
  '4320p',
  '2160p',
  '1440p',
  '1080p',
  '720p',
  '576p',
  '480p',
  '360p',
];

export const categoryMetadata = (category) => {
  const props = category.custom_properties || {};
  return {
    audio_languages: Object.hasOwn(props, 'audio_languages')
      ? props.audio_languages || []
      : props.language
        ? [
            MEDIA_LANGUAGE_OPTIONS.find(
              (option) => option.legacyValue === props.language
            )?.value || props.language,
          ]
        : [],
    subtitle_languages: props.subtitle_languages || [],
    resolution: Object.hasOwn(props, 'resolution')
      ? props.resolution || ''
      : { '4K': '2160p', FHD: '1080p', HD: '720p' }[props.quality] ||
        props.quality ||
        '',
    video_features: props.video_features || [],
  };
};

export const metadataSummary = (values = {}) =>
  [
    values.audio_languages?.length &&
      `DUB: ${values.audio_languages.join(', ')}`,
    values.subtitle_languages?.length &&
      `SUB: ${values.subtitle_languages.join(', ')}`,
    values.resolution,
    values.video_features?.length &&
      values.video_features
        .map((feature) =>
          feature === 'dv'
            ? 'Dolby Vision'
            : feature.startsWith('custom:')
              ? feature.slice(7)
              : feature.toUpperCase()
        )
        .join(', '),
  ]
    .filter(Boolean)
    .join(' · ');

export const categoryMetadataPatch = (draft) => ({
  ...draft,
  resolution: draft.resolution || null,
});
