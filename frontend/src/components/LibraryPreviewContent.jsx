import { Fragment, useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Group,
  Image,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
  Tooltip,
  UnstyledButton,
} from '@mantine/core';
import { Copy, Pencil, Play } from 'lucide-react';
import {
  formatDuration,
  getTmdbUrlLink,
  imdbUrl,
  tmdbUrl,
} from '../utils/components/SeriesModalUtils.js';
import { metadataFieldItems } from '../utils/vodSourceMetadata';
import { ScreenshotText } from './SensitiveFields.jsx';
import ListPagination from './ListPagination.jsx';
import MetadataOriginBadges from './MetadataOriginBadges.jsx';
import { sourceMetadataOrigins } from '../utils/libraryMetadataOrigins.js';
import { formatRating } from '../utils/cards/VODCardUtils.js';
import classes from './LibraryPreviewModal.module.css';

export function PreviewAction({
  label,
  icon: IconComponent,
  onClick,
  disabled,
  color = 'blue',
  variant = 'subtle',
}) {
  const Glyph = IconComponent;
  return (
    <Tooltip label={label} withArrow>
      <ActionIcon
        aria-label={label}
        disabled={disabled}
        color={color}
        variant={variant}
        onClick={(event) => {
          event.stopPropagation();
          onClick();
        }}
      >
        <Glyph size={17} />
      </ActionIcon>
    </Tooltip>
  );
}

export function PreviewArtwork({ src, name }) {
  const [failed, setFailed] = useState(null);
  return src && failed !== src ? (
    <Image
      src={src}
      alt={name}
      w={200}
      h={300}
      fit="contain"
      radius="md"
      onError={() => setFailed(src)}
    />
  ) : (
    <div
      className={classes.posterPlaceholder}
      aria-label="No artwork available"
    >
      <Play size={48} aria-hidden="true" />
    </div>
  );
}

export function PreviewBackdrop({ src, name }) {
  const [failed, setFailed] = useState(null);
  if (!src || failed === src) return null;
  return (
    <>
      <Image
        src={src}
        alt={`${name} backdrop`}
        className={classes.backdrop}
        onError={() => setFailed(src)}
      />
      <div className={classes.backdropOverlay} aria-hidden="true" />
    </>
  );
}

export function PreviewSummary({
  title,
  display,
  metadata,
  description,
  localized,
  series,
  episodeCount = 0,
  poster,
  onTrailer,
}) {
  return (
    <div className={classes.summary}>
      <div className={classes.poster}>
        <PreviewArtwork src={poster} name={title} />
      </div>
      <Stack gap="md" className={classes.details}>
        <Title order={3}>{title}</Title>
        {metadata.original_title && metadata.original_title !== title && (
          <Text size="sm" c="dimmed" fs="italic">
            Original: {metadata.original_title}
          </Text>
        )}
        {localized?.tagline && (
          <Text size="sm" fs="italic">
            {localized.tagline}
          </Text>
        )}
        <Group gap="md">
          {display?.year && <Badge color="blue">{display.year}</Badge>}
          {display?.duration_secs > 0 && (
            <Badge color="gray">{formatDuration(display.duration_secs)}</Badge>
          )}
          {Number(display?.rating) > 0 && (
            <Badge color="yellow">{formatRating(display.rating)}</Badge>
          )}
          {metadata.age_rating && (
            <Badge color="orange">{metadata.age_rating}</Badge>
          )}
          <Badge color={series ? 'purple' : 'green'}>
            {series ? 'Series' : 'Movie'}
          </Badge>
          {series && episodeCount > 0 && (
            <Badge color="gray">{episodeCount} episodes</Badge>
          )}
          {metadata.is_anime && <Badge color="pink">Anime</Badge>}
          {(metadata.adult || display?.is_adult) && (
            <Badge color="red">Adult</Badge>
          )}
        </Group>
        <Group gap="xs" aria-label="External IDs">
          {display?.tmdb_id && (
            <Tooltip label="Open on TMDB" withArrow>
              <Badge
                component="a"
                href={tmdbUrl(display.tmdb_id, series ? 'tv' : 'movie')}
                target="_blank"
                rel="noopener noreferrer"
                className={classes.externalId}
              >
                TMDB {display.tmdb_id}
              </Badge>
            </Tooltip>
          )}
          {display?.imdb_id && (
            <Tooltip label="Open on IMDb" withArrow>
              <Badge
                color="yellow"
                component="a"
                href={imdbUrl(display.imdb_id)}
                target="_blank"
                rel="noopener noreferrer"
                className={classes.externalId}
              >
                IMDb {display.imdb_id}
              </Badge>
            </Tooltip>
          )}
        </Group>
        {[
          ['Release Date', metadata.release_date],
          ['Genre', display?.genre],
          [
            'Keywords',
            metadata.keywords?.map((value) => value.name || value).join(', '),
          ],
          [series ? 'Creator' : 'Director', metadata.director],
          ['Cast', metadata.actors],
          ['Crew', metadata.crew],
          ['Country', metadata.country],
        ]
          .filter(([, value]) => value)
          .map(([label, value]) => (
            <Text key={label} size="sm" c="dimmed">
              <strong>{label}:</strong>{' '}
              <ScreenshotText>{String(value)}</ScreenshotText>
            </Text>
          ))}
        <div>
          <Text size="sm" fw={500} mb={8}>
            Description
          </Text>
          <Text size="sm" className={classes.description}>
            <ScreenshotText>
              {description || 'No description available.'}
            </ScreenshotText>
          </Text>
        </div>
        {metadata.youtube_trailer && (
          <Button
            variant="outline"
            color="red"
            size="sm"
            onClick={onTrailer}
            style={{ alignSelf: 'flex-start' }}
          >
            Watch Trailer
          </Button>
        )}
      </Stack>
    </div>
  );
}

function Tags({ values, color = 'gray', language = false }) {
  return values?.length ? (
    <Group gap={4}>
      {values.map((value) => (
        <Badge
          key={value}
          color={color}
          variant="light"
          className={language ? classes.language : undefined}
        >
          {value}
        </Badge>
      ))}
    </Group>
  ) : (
    <Text c="dimmed">—</Text>
  );
}

function positive(value) {
  const result = Number.parseFloat(String(value ?? '').replace(',', '.'));
  return Number.isFinite(result) && result > 0 ? result : null;
}

function fileSize(value) {
  if (!value) return null;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  const index = Math.max(
    0,
    Math.min(Math.floor(Math.log(value) / Math.log(1000)), units.length - 1)
  );
  const amount = value / 1000 ** index;
  return `${amount >= 10 || index === 0 ? amount.toFixed(0) : amount.toFixed(1)} ${units[index]}`;
}

function sourceDetails(source) {
  const technical = source.provider?.technical || {};
  const values = source.effective_metadata?.values || {};
  const bitrate = positive(technical.bitrate);
  const bytes = positive(technical.file_size_bytes);
  const rawRate =
    technical.video?.avg_frame_rate || technical.video?.r_frame_rate;
  const [numerator, denominator] = String(rawRate || '')
    .split('/')
    .map(Number);
  const rate = positive(denominator ? numerator / denominator : numerator);
  return [
    source.container_extension?.toUpperCase(),
    bitrate &&
      (bitrate >= 1000
        ? `${(bitrate / 1000).toFixed(bitrate >= 10000 ? 1 : 2)} Mbps`
        : `${Math.round(bitrate)} kbps`),
    fileSize(bytes),
    technical.video?.codec_name?.toUpperCase(),
    technical.audio?.codec_name?.toUpperCase(),
    rate && `${Number.isInteger(rate) ? rate : rate.toFixed(2)} FPS`,
    ...metadataFieldItems(values, 'video_features'),
  ].filter(Boolean);
}

export function PreviewSources({
  sources,
  selected,
  series,
  accountId,
  disabled,
  blocked = false,
  admin,
  onSelect,
  onPlay,
  onCopy,
  onEdit,
}) {
  return (
    <div className={classes.tableFrame}>
      <Table
        striped
        highlightOnHover
        withTableBorder
        layout="fixed"
        miw={series ? 980 : 1120}
        aria-label="Exact VOD sources"
        className={classes.sources}
      >
        <Table.Thead>
          <Table.Tr>
            <Table.Th>
              <Text inherit fw={700}>
                Source
              </Text>
              <Text size="xs" c="dimmed">
                M3U account · Category · IDs
              </Text>
            </Table.Th>
            <Table.Th w={140}>DUB</Table.Th>
            <Table.Th w={140}>SUB</Table.Th>
            <Table.Th w={110}>Resolution</Table.Th>
            <Table.Th w={series ? 160 : 320}>
              {series ? 'Codec' : 'Details'}
            </Table.Th>
            <Table.Th w={series ? 88 : 132}>Actions</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {sources.map((source) => {
            const current = source.source_id === selected.source_id;
            const outside =
              !!accountId && String(source.account.id) !== String(accountId);
            const technical = source.provider?.technical || {};
            const origins = sourceMetadataOrigins(source, series);
            if (!origins.resolution && technical.video?.height)
              origins.resolution = {
                [`${technical.video.height}p`]: 'provider',
              };
            return (
              <Table.Tr
                key={source.source_id}
                aria-label={`Source ${source.account.name} #${source.source_id}`}
                aria-selected={current}
                aria-disabled={disabled || undefined}
                data-selected={current || undefined}
                data-outside-filter={outside || undefined}
                tabIndex={disabled ? -1 : 0}
                onClick={() => !disabled && onSelect(source)}
                onKeyDown={(event) => {
                  if (
                    event.target === event.currentTarget &&
                    ['Enter', ' '].includes(event.key)
                  ) {
                    event.preventDefault();
                    if (!disabled) onSelect(source);
                  }
                }}
              >
                <Table.Td>
                  <Stack gap={1}>
                    <Text size="sm" fw={500} lineClamp={1}>
                      <ScreenshotText>{source.provider_name}</ScreenshotText>
                    </Text>
                    <Tooltip
                      label="Outside current library filter"
                      disabled={!outside}
                      withArrow
                    >
                      <Text size="xs" c="dimmed">
                        {source.account.name} ·{' '}
                        {source.category.name || 'Uncategorized'}
                      </Text>
                    </Tooltip>
                    <Text size="xs" c="dimmed">
                      {series ? 'Provider series ID' : 'Stream ID'}:{' '}
                      {source.provider_id || '—'} · Relation ID:{' '}
                      {source.source_id}
                    </Text>
                  </Stack>
                </Table.Td>
                {['audio_languages', 'subtitle_languages', 'resolution'].map(
                  (field) => (
                    <Table.Td key={field}>
                      <MetadataOriginBadges
                        origins={origins}
                        field={field}
                        size="md"
                      />
                    </Table.Td>
                  )
                )}
                <Table.Td>
                  <Tags
                    values={
                      series
                        ? technical.episode_video_codecs ||
                          (technical.video?.codec_name
                            ? [technical.video.codec_name.toUpperCase()]
                            : [])
                        : sourceDetails(source)
                    }
                  />
                </Table.Td>
                <Table.Td>
                  <Group gap={5} wrap="nowrap">
                    {!series && (
                      <>
                        <PreviewAction
                          label={`Play source ${source.account.name} #${source.source_id}`}
                          icon={Play}
                          variant="filled"
                          disabled={disabled || blocked}
                          onClick={() => onPlay(source)}
                        />
                        <PreviewAction
                          label={`Copy source link ${source.account.name} #${source.source_id}`}
                          icon={Copy}
                          color="gray"
                          variant="light"
                          disabled={disabled || blocked}
                          onClick={() => onCopy(source)}
                        />
                      </>
                    )}
                    {admin && (
                      <PreviewAction
                        label={`Edit source metadata ${source.account.name} #${source.source_id}`}
                        icon={Pencil}
                        color="gray"
                        variant="light"
                        disabled={disabled}
                        onClick={() => onEdit(source)}
                      />
                    )}
                  </Group>
                </Table.Td>
              </Table.Tr>
            );
          })}
        </Table.Tbody>
      </Table>
    </div>
  );
}

function EpisodeDetails({ episode, canonical, source }) {
  const technical = episode.technical || {};
  const bitrate = positive(technical.bitrate);
  const video = technical.video || {};
  const audio = technical.audio || {};
  return (
    <Stack gap="sm">
      <Group align="flex-start" wrap="nowrap">
        {episode.poster_url && (
          <Image
            src={episode.poster_url}
            alt={episode.name}
            w={120}
            h={160}
            fit="cover"
            radius="sm"
            style={{ flexShrink: 0 }}
          />
        )}
        {episode.description && (
          <div className={classes.details}>
            <Text size="sm" fw={500} mb={4}>
              Description
            </Text>
            <Text size="sm" c="dimmed" className={classes.description}>
              <ScreenshotText>{episode.description}</ScreenshotText>
            </Text>
          </div>
        )}
      </Group>
      <Group gap="xl" align="flex-start">
        {positive(episode.rating) && (
          <div>
            <Text size="xs" fw={500} c="dimmed" mb={2}>
              Rating
            </Text>
            <Badge color="yellow" size="sm">
              {formatRating(episode.rating)}
            </Badge>
          </div>
        )}
        {(episode.imdb_id || canonical?.tmdb_id) && (
          <div>
            <Text size="xs" fw={500} c="dimmed" mb={2}>
              Links
            </Text>
            <Group gap={5}>
              {episode.imdb_id && (
                <Badge
                  color="yellow"
                  component="a"
                  href={imdbUrl(episode.imdb_id)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  IMDb
                </Badge>
              )}
              {canonical?.tmdb_id && (
                <Badge
                  color="cyan"
                  component="a"
                  href={getTmdbUrlLink(canonical, episode)}
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  TMDB
                </Badge>
              )}
            </Group>
          </div>
        )}
        {['director', 'actors'].map(
          (field) =>
            episode[field] && (
              <div key={field} className={classes.details}>
                <Text size="xs" fw={500} c="dimmed" mb={2}>
                  {field === 'director' ? 'Director' : 'Cast'}
                </Text>
                <Text size="sm">
                  <ScreenshotText>{episode[field]}</ScreenshotText>
                </Text>
              </div>
            )
        )}
      </Group>
      {(bitrate ||
        Object.keys(video).length > 0 ||
        Object.keys(audio).length > 0) && (
        <Stack gap={2}>
          <Text size="xs" fw={500} c="dimmed" mb={4}>
            Technical details
          </Text>
          {bitrate && (
            <Text size="xs" c="dimmed">
              <strong>Bitrate:</strong> {bitrate} kbps
            </Text>
          )}
          {Object.keys(video).length > 0 && (
            <Text size="xs" c="dimmed">
              <strong>Video:</strong>{' '}
              <ScreenshotText>
                {[
                  video.codec_long_name || video.codec_name,
                  video.width && video.height
                    ? `${video.width}x${video.height}`
                    : '',
                ]
                  .filter(Boolean)
                  .join(', ')}
              </ScreenshotText>
            </Text>
          )}
          {Object.keys(audio).length > 0 && (
            <Text size="xs" c="dimmed">
              <strong>Audio:</strong>{' '}
              <ScreenshotText>
                {[
                  audio.codec_long_name || audio.codec_name,
                  audio.channels ? `${audio.channels} channels` : '',
                ]
                  .filter(Boolean)
                  .join(', ')}
              </ScreenshotText>
            </Text>
          )}
        </Stack>
      )}
      {source?.account?.name && (
        <Group gap="md">
          <Text size="xs" fw={500} c="dimmed">
            Provider:
          </Text>
          <Badge color="blue" variant="light" size="sm">
            {source.account.name}
          </Badge>
        </Group>
      )}
    </Stack>
  );
}

export function PreviewEpisodes({
  data,
  source,
  season,
  onSeason,
  pageSize,
  onPage,
  onPageSize,
  disabled,
  blocked = false,
  onPlay,
  onCopy,
}) {
  const [expanded, setExpanded] = useState(null);
  const total =
    (data.seasons || []).reduce((count, row) => count + row.count, 0) ||
    data.episode_count;
  const seasons = data.seasons || [];
  const panelId = `library-source-episodes-${source?.source_id ?? 'preview'}`;
  const selectedSeason = String(
    data.selected_season ??
      season ??
      (seasons.length ? (seasons[0].number ?? -1) : '')
  );
  const toggle = (id) => setExpanded((current) => (current === id ? null : id));
  return (
    <Stack gap="md">
      <Title order={4}>Episodes{total > 0 ? ` (${total})` : ''}</Title>
      <Tabs id={panelId} value={selectedSeason} onChange={onSeason}>
        <Tabs.List>
          {seasons.map((row) => (
            <Tabs.Tab
              key={row.number ?? -1}
              value={String(row.number ?? -1)}
              disabled={disabled}
            >
              {row.number === null
                ? 'Unassigned'
                : row.number === 0
                  ? 'Specials'
                  : `Season ${row.number}`}{' '}
              ({row.count})
            </Tabs.Tab>
          ))}
        </Tabs.List>
      </Tabs>
      <div
        className={classes.tableFrame}
        role={seasons.length ? 'tabpanel' : undefined}
        id={seasons.length ? `${panelId}-panel-${selectedSeason}` : undefined}
        aria-labelledby={
          seasons.length ? `${panelId}-tab-${selectedSeason}` : undefined
        }
      >
        <Table
          striped
          highlightOnHover
          miw={920}
          className={classes.episodes}
          aria-label="Source episodes"
        >
          <Table.Thead>
            <Table.Tr>
              <Table.Th w={60}>Ep</Table.Th>
              <Table.Th>Title</Table.Th>
              <Table.Th w={80}>Duration</Table.Th>
              <Table.Th w={100}>Date</Table.Th>
              <Table.Th w={110}>Resolution</Table.Th>
              <Table.Th w={80}>Codec</Table.Th>
              <Table.Th w={70}>Format</Table.Th>
              <Table.Th w={100}>Actions</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(data.episodes || []).map((episode) => (
              <Fragment key={episode.id}>
                <Table.Tr
                  onClick={() => !disabled && toggle(episode.id)}
                  className={classes.episodeRow}
                >
                  <Table.Td>
                    <Badge size="sm" variant="outline">
                      {episode.episode_number ?? '—'}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <UnstyledButton
                      className={classes.episodeName}
                      aria-expanded={expanded === episode.id}
                      aria-controls={`library-episode-${episode.id}`}
                      disabled={disabled}
                      onClick={(event) => {
                        event.stopPropagation();
                        toggle(episode.id);
                      }}
                    >
                      <Text component="span" size="sm" fw={500}>
                        <ScreenshotText>{episode.name}</ScreenshotText>
                      </Text>
                    </UnstyledButton>
                    {episode.genre && (
                      <Text size="xs" c="dimmed">
                        <ScreenshotText>{episode.genre}</ScreenshotText>
                      </Text>
                    )}
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {formatDuration(episode.duration_secs) || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {episode.air_date || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {episode.resolution || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {episode.video_codec?.toUpperCase() || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Text size="xs" c="dimmed">
                      {episode.container_extension || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Group gap={4} wrap="nowrap">
                      <PreviewAction
                        label={`Play episode ${episode.name}`}
                        icon={Play}
                        disabled={disabled || blocked}
                        variant="filled"
                        onClick={() => onPlay(episode)}
                      />
                      <PreviewAction
                        label={`Copy episode link ${episode.name}`}
                        icon={Copy}
                        disabled={disabled || blocked}
                        variant="light"
                        color="gray"
                        onClick={() => onCopy(episode)}
                      />
                    </Group>
                  </Table.Td>
                </Table.Tr>
                {expanded === episode.id && (
                  <Table.Tr id={`library-episode-${episode.id}`}>
                    <Table.Td
                      colSpan={8}
                      p="md"
                      className={classes.episodeExpanded}
                    >
                      <EpisodeDetails
                        episode={episode}
                        canonical={data.canonical}
                        source={source}
                      />
                    </Table.Td>
                  </Table.Tr>
                )}
              </Fragment>
            ))}
            {!data.episodes?.length && (
              <Table.Tr>
                <Table.Td colSpan={8}>
                  <Text c="dimmed" size="sm">
                    No stored episodes for this source.
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
          </Table.Tbody>
        </Table>
      </div>
      {!!data.episode_count && (
        <ListPagination
          page={data.episode_page}
          pageSize={pageSize}
          total={data.episode_count}
          onPageChange={onPage}
          onPageSizeChange={onPageSize}
          disabled={disabled}
        />
      )}
    </Stack>
  );
}
