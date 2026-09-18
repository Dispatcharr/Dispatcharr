import React from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Group,
  ScrollArea,
  Stack,
  Table,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  Text,
  Tooltip,
  Loader,
} from '@mantine/core';
import { Copy, Play, Wrench } from 'lucide-react';
import { videoFeatureLabel } from '../utils/vodMetadataOptions.js';

const valuesFor = (provider, selectedProvider, selectedSourceMetadata) => {
  const stored = provider?.source_metadata?.values || {};
  if (selectedProvider?.id === provider?.id && selectedSourceMetadata?.values) {
    return { ...stored, ...selectedSourceMetadata.values };
  }
  return stored;
};

const metadataLanguages = (values, field) => {
  const raw = values[field];
  const languages = Array.isArray(raw) ? raw : raw ? [raw] : [];
  return languages.map((value) => String(value).toUpperCase());
};

const positiveNumber = (value) => {
  const number = Number.parseFloat(String(value ?? '').replace(',', '.'));
  return Number.isFinite(number) && number > 0 ? number : null;
};

const formatBitrate = (values) => {
  const bitrate = positiveNumber(values.bitrate_kbps ?? values.bitrate);
  if (!bitrate) return null;
  if (bitrate >= 1000) {
    const mbps = bitrate / 1000;
    return `${mbps >= 10 ? mbps.toFixed(1) : mbps.toFixed(2)} Mbps`;
  }
  return `${Math.round(bitrate)} kbps`;
};

const formatFileSize = (value) => {
  const bytes = positiveNumber(value);
  if (!bytes) return null;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const unitIndex = Math.min(
    Math.floor(Math.log(bytes) / Math.log(1000)),
    units.length - 1
  );
  const amount = bytes / 1000 ** unitIndex;
  return `${amount >= 10 || unitIndex === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[unitIndex]}`;
};

const formatFrameRate = (value) => {
  if (!value) return null;
  const [numerator, denominator] = String(value).split('/').map(Number);
  const fps = denominator ? numerator / denominator : Number(value);
  if (!Number.isFinite(fps) || fps <= 0) return null;
  return `${Number.isInteger(fps) ? fps : fps.toFixed(2)} FPS`;
};

const LanguageBadges = ({ values, field, color }) => {
  const languages = metadataLanguages(values, field);
  if (!languages.length) return <Text c="dimmed">—</Text>;
  return (
    <Group gap={4} wrap="wrap">
      {languages.map((language) => (
        <Badge key={language} color={color} variant="light">
          {language}
        </Badge>
      ))}
    </Group>
  );
};

const valueList = (value) => {
  if (Array.isArray(value)) return value.filter(Boolean).map(String);
  return value ? [String(value)] : [];
};

const ResolutionBadges = ({ values, contentType }) => {
  const resolutions =
    contentType === 'series' && values.episode_resolutions?.length
      ? valueList(values.episode_resolutions)
      : valueList(
          values.resolution || (values.height ? `${values.height}p` : '')
        );
  if (!resolutions.length) return <Text c="dimmed">—</Text>;
  return (
    <Group gap={4} wrap="wrap">
      {resolutions.map((resolution) => (
        <Badge key={resolution} color="teal" variant="light">
          {resolution}
        </Badge>
      ))}
    </Group>
  );
};

const SeriesEpisodeDetails = ({ values }) => {
  const codecs = valueList(values.episode_video_codecs);
  if (!codecs.length) return <Text c="dimmed">—</Text>;
  return (
    <Group gap={4} wrap="wrap">
      {codecs.map((codec) => (
        <Badge key={codec} color="gray" variant="light">
          {codec.toUpperCase()}
        </Badge>
      ))}
    </Group>
  );
};

const MovieDetails = ({ values, provider }) => {
  const details = [
    {
      value: values.container_extension || provider.container_extension,
      uppercase: true,
    },
    { value: formatBitrate(values) },
    { value: formatFileSize(values.file_size_bytes) },
    {
      value: values.video_codec || values.video?.codec_name,
      uppercase: true,
    },
    {
      value: values.audio_codec || values.audio?.codec_name,
      uppercase: true,
    },
    {
      value: formatFrameRate(
        values.frame_rate ||
          values.video?.avg_frame_rate ||
          values.video?.r_frame_rate
      ),
    },
    ...(values.video_features || []).map((value) => ({
      value: videoFeatureLabel(value),
      uppercase: true,
    })),
  ];
  const visibleDetails = details.filter(({ value }) => Boolean(value));
  if (!visibleDetails.length) return <Text c="dimmed">—</Text>;
  return (
    <Group gap={4} wrap="wrap">
      {visibleDetails.map(({ value, uppercase }, index) => (
        <Badge key={`${value}-${index}`} color="gray" variant="light">
          {uppercase ? String(value).toUpperCase() : value}
        </Badge>
      ))}
    </Group>
  );
};

const sourceName = (provider, contentType) => {
  const properties = provider?.custom_properties || {};
  const detail = properties.detailed_info || {};
  const basic = properties.basic_data || properties.movie_data || {};
  return (
    provider?.stream_name ||
    detail.name ||
    basic.name ||
    provider?.movie?.name ||
    provider?.series?.name ||
    (contentType === 'series'
      ? `Series ${provider?.external_series_id || provider?.id}`
      : `Stream ${provider?.stream_id || provider?.id}`)
  );
};

const VODSourceList = ({
  providers,
  selectedProvider,
  selectedSourceMetadata,
  contentType,
  disabled = false,
  onSelect,
  onEdit,
  onPlay,
  onCopy,
  profileCandidates,
  profileCandidatesLoading = false,
  profileCandidatesError = '',
}) => {
  const candidateRows = profileCandidates?.results || [];
  const candidateByRelation = new Map(
    candidateRows.map((row) => [String(row.relation_id), row])
  );
  const candidateOrder = new Map(
    candidateRows.map((row, index) => [String(row.relation_id), index])
  );
  const visibleProviders = candidateRows.length
    ? [...providers].sort(
        (left, right) =>
          (candidateOrder.get(String(left.id)) ?? Number.MAX_SAFE_INTEGER) -
          (candidateOrder.get(String(right.id)) ?? Number.MAX_SAFE_INTEGER)
      )
    : providers;

  return (
    <Stack gap="xs">
      {profileCandidatesLoading && (
        <Group gap="xs">
          <Loader size="xs" />
          <Text size="sm" c="dimmed">
            Loading profile selection…
          </Text>
        </Group>
      )}
      {profileCandidatesError && (
        <Alert color="red">{profileCandidatesError}</Alert>
      )}
      {profileCandidates && (
        <Alert color="blue" variant="light">
          Profile order and exclusions are shown on the same source rows. The
          first eligible source is tried first; availability is checked again
          when playback starts.
        </Alert>
      )}
      <ScrollArea type="auto">
        <Table
          striped
          highlightOnHover
          withTableBorder
          layout="fixed"
          miw={contentType === 'movie' ? 1120 : 980}
          aria-label="Exact VOD sources"
        >
          <TableThead>
            <TableTr>
              {profileCandidates && <TableTh w={125}>Order</TableTh>}
              <TableTh>
                <Stack gap={0}>
                  <Text inherit fw={700}>
                    Source
                  </Text>
                  <Group gap={4} wrap="nowrap">
                    <Text size="xs" c="dimmed">
                      M3U account
                    </Text>
                    <Text size="xs" c="dimmed">
                      ·
                    </Text>
                    <Text size="xs" c="dimmed">
                      Category
                    </Text>
                    <Text size="xs" c="dimmed">
                      · IDs
                    </Text>
                  </Group>
                </Stack>
              </TableTh>
              <TableTh w={140}>DUB</TableTh>
              <TableTh w={140}>SUB</TableTh>
              <TableTh w={110}>Resolution</TableTh>
              <TableTh w={contentType === 'movie' ? 320 : 160}>
                {contentType === 'movie' ? 'Details' : 'Codec'}
              </TableTh>
              <TableTh w={contentType === 'movie' ? 132 : 88}>Actions</TableTh>
            </TableTr>
          </TableThead>
          <TableTbody>
            {visibleProviders.map((provider) => {
              const values = valuesFor(
                provider,
                selectedProvider,
                selectedSourceMetadata
              );
              const selected = selectedProvider?.id === provider.id;
              const profileRow = candidateByRelation.get(String(provider.id));
              return (
                <TableTr
                  key={provider.id}
                  data-selected={selected || undefined}
                  onClick={() => onSelect?.(provider)}
                  style={{
                    cursor: 'pointer',
                    opacity: profileRow && !profileRow.allowed ? 0.48 : 1,
                    backgroundColor: selected
                      ? 'var(--mantine-color-blue-light)'
                      : undefined,
                    boxShadow: selected
                      ? 'inset 3px 0 var(--mantine-color-blue-6)'
                      : undefined,
                  }}
                >
                  {profileCandidates && (
                    <TableTd>
                      <Stack gap={2}>
                        {profileRow?.position ? (
                          <Badge variant="light">#{profileRow.position}</Badge>
                        ) : (
                          <Badge color="gray" variant="outline">
                            Excluded
                          </Badge>
                        )}
                        {profileRow?.reason &&
                          profileRow.reason !== 'eligible' && (
                            <Text size="xs" c="dimmed">
                              {profileRow.reason.replaceAll('_', ' ')}
                            </Text>
                          )}
                      </Stack>
                    </TableTd>
                  )}
                  <TableTd>
                    <Stack gap={1}>
                      <Text size="sm" fw={500} lineClamp={1}>
                        {sourceName(provider, contentType)}
                      </Text>
                      <Group gap={4} wrap="wrap">
                        <Text size="xs" c="dimmed">
                          {provider.m3u_account?.name || 'Unknown'}
                        </Text>
                        <Text size="xs" c="dimmed">
                          ·
                        </Text>
                        <Text size="xs" c="dimmed">
                          {provider.category?.name || 'Uncategorized'}
                        </Text>
                      </Group>
                      <Text size="xs" c="dimmed">
                        {contentType === 'movie'
                          ? `Stream ID: ${provider.stream_id || '—'}`
                          : `Provider series ID: ${provider.external_series_id || '—'}`}
                        {' · '}Relation ID: {provider.id}
                      </Text>
                    </Stack>
                  </TableTd>
                  <TableTd>
                    <LanguageBadges
                      values={values}
                      field="audio_languages"
                      color="blue"
                    />
                  </TableTd>
                  <TableTd>
                    <LanguageBadges
                      values={values}
                      field="subtitle_languages"
                      color="cyan"
                    />
                  </TableTd>
                  <TableTd>
                    <ResolutionBadges
                      values={values}
                      contentType={contentType}
                    />
                  </TableTd>
                  <TableTd>
                    {contentType === 'movie' ? (
                      <MovieDetails values={values} provider={provider} />
                    ) : (
                      <SeriesEpisodeDetails values={values} />
                    )}
                  </TableTd>
                  <TableTd>
                    <Group gap={5} wrap="nowrap">
                      {contentType === 'movie' && (
                        <>
                          <Tooltip label="Play this exact source">
                            <ActionIcon
                              aria-label="Play exact source"
                              variant="filled"
                              color="blue"
                              disabled={disabled}
                              onClick={(event) => {
                                event.stopPropagation();
                                onPlay?.(provider);
                              }}
                            >
                              <Play size={15} />
                            </ActionIcon>
                          </Tooltip>
                          <Tooltip label="Copy link for this exact source">
                            <ActionIcon
                              aria-label="Copy exact source link"
                              variant="light"
                              color="gray"
                              disabled={disabled}
                              onClick={(event) => {
                                event.stopPropagation();
                                onCopy?.(provider);
                              }}
                            >
                              <Copy size={15} />
                            </ActionIcon>
                          </Tooltip>
                        </>
                      )}
                      {onEdit && (
                        <Tooltip label="Edit this exact source">
                          <ActionIcon
                            aria-label="Edit exact source metadata"
                            variant="light"
                            color="gray"
                            disabled={disabled}
                            onClick={(event) => {
                              event.stopPropagation();
                              onEdit(provider);
                            }}
                          >
                            <Wrench size={15} />
                          </ActionIcon>
                        </Tooltip>
                      )}
                    </Group>
                  </TableTd>
                </TableTr>
              );
            })}
          </TableTbody>
        </Table>
      </ScrollArea>
    </Stack>
  );
};

export default VODSourceList;
