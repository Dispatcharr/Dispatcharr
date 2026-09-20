import React, { useMemo } from 'react';
import { Select } from '@mantine/core';
import useVODFilterOptions from '../hooks/useVODFilterOptions.js';
import { LANGUAGE_OPTIONS } from '../utils/languageCodes.js';
import { videoFeatureLabel } from '../utils/vodMetadataOptions.js';

const languageLabel = (code) =>
  LANGUAGE_OPTIONS.find((option) => option.value === code)?.label ||
  String(code || '').toUpperCase();

const textOptions = (values, labelFor = (value) => value) =>
  (values || []).map((value) => ({ value, label: labelFor(value) }));

const VODTechnicalFilterFields = ({
  filters,
  onChange,
  type = 'all',
  m3uAccount = '',
  category = '',
  enabled = true,
  featureLabel = 'Feature',
}) => {
  const { options, loading } = useVODFilterOptions({
    enabled,
    type,
    m3uAccount,
    category,
  });
  const data = useMemo(
    () => ({
      audio: textOptions(options.audio_languages, languageLabel),
      subtitles: textOptions(options.subtitle_languages, languageLabel),
      resolutions: textOptions(
        [...(options.resolutions || [])].sort(
          (left, right) => parseInt(left, 10) - parseInt(right, 10)
        )
      ),
      containers: textOptions(options.container_extensions),
      features: textOptions(options.video_features, videoFeatureLabel),
    }),
    [options]
  );

  const selectProps = {
    placeholder: 'Any',
    clearable: true,
    searchable: true,
    disabled: loading,
    nothingFoundMessage: 'No values in this selection',
  };

  return (
    <>
      <Select
        {...selectProps}
        label="DUB"
        data={data.audio}
        value={filters.audio_language || null}
        onChange={(value) => onChange('audio_language', value || '')}
      />
      <Select
        {...selectProps}
        label="SUB"
        data={data.subtitles}
        value={filters.subtitle_language || null}
        onChange={(value) => onChange('subtitle_language', value || '')}
      />
      <Select
        {...selectProps}
        label="Resolution"
        data={data.resolutions}
        value={filters.resolution || null}
        onChange={(value) => onChange('resolution', value || '')}
      />
      <Select
        {...selectProps}
        label="Format"
        data={data.containers}
        value={filters.container_extension || null}
        onChange={(value) => onChange('container_extension', value || '')}
      />
      <Select
        {...selectProps}
        label={featureLabel}
        data={data.features}
        value={filters.video_feature || null}
        onChange={(value) => onChange('video_feature', value || '')}
      />
    </>
  );
};

export default VODTechnicalFilterFields;
