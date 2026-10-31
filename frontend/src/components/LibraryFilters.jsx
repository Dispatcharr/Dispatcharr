import {
  ActionIcon,
  Button,
  Indicator,
  Popover,
  Paper,
  ScrollArea,
  Select,
  SimpleGrid,
  Stack,
  TagsInput,
  Text,
  Tooltip,
} from '@mantine/core';
import { DatePickerInput } from '@mantine/dates';
import { Filter } from 'lucide-react';
import MEDIA_LANGUAGES from '../../../apps/vod/media_languages.json';
import { useDateTimeFormat } from '../utils/dateTimeUtils.js';

const LIBRARY_EXTRA_FILTERS = [
  'account',
  'category',
  'content_id',
  'metadata_status',
  'locked',
  'blocked',
  'audio_language',
  'subtitle_language',
  'resolution',
  'video_feature',
  'container_extension',
  'genre',
  'anime_mode',
  'adult_mode',
  'added_since',
  'added_until',
  'released_since',
  'released_until',
];

const languageLabel = (value) =>
  MEDIA_LANGUAGES.find((option) => option.value === value)?.label || value;
const featureLabel = (value) =>
  ({ hdr: 'HDR', dv: 'Dolby Vision', '3d': '3D' })[value] ||
  value.replace(/^custom:/, '');

export default function LibraryFilters({
  filters,
  onChange,
  options = {},
  moviesEnabled = true,
  seriesEnabled = true,
  admin = false,
}) {
  const { dateYearFormat } = useDateTimeFormat();
  const bothTypes = moviesEnabled && seriesEnabled;
  const activeCount =
    LIBRARY_EXTRA_FILTERS.filter(
      (field) => filters[field] !== '' && filters[field] != null
    ).length + (bothTypes && filters.type && filters.type !== 'all' ? 1 : 0);
  const activeLabel = `${activeCount} ${activeCount === 1 ? 'filter' : 'filters'} active`;
  const select = (field, label, data, placeholder = 'Any') => (
    <Select
      key={field}
      label={label}
      placeholder={placeholder}
      clearable
      searchable
      comboboxProps={{ withinPortal: false }}
      data={data}
      value={filters[field] || null}
      onChange={(value) => onChange({ [field]: value || '' })}
    />
  );
  const actual = (field, key, label = (value) => value) =>
    [
      ...new Set([
        ...(options[key] || []),
        ...(filters[field] ? [filters[field]] : []),
      ]),
    ].map((value) => ({ value, label: label(value) }));
  const group = (title, children) => (
    <Paper
      component="section"
      aria-label={`${title} filters`}
      withBorder
      p="sm"
    >
      <Stack gap="xs">
        <Text size="sm" fw={600}>
          {title}
        </Text>
        <SimpleGrid cols={{ base: 1, xs: 2 }} spacing="sm">
          {children}
        </SimpleGrid>
      </Stack>
    </Paper>
  );
  const date = (field, label, props = {}) => (
    <DatePickerInput
      label={label}
      placeholder="Any date"
      clearable
      valueFormat={dateYearFormat}
      popoverProps={{ withinPortal: false }}
      value={filters[field] || null}
      onChange={(value) => onChange({ [field]: value || '' })}
      {...props}
    />
  );
  const dateRange = (label, start, end) => (
    <>
      {date(start, `${label} from`)}
      {date(end, `${label} to`, {
        minDate: filters[start] || undefined,
        error:
          filters[start] && filters[end] && filters[start] > filters[end]
            ? 'End date precedes start date.'
            : undefined,
      })}
    </>
  );
  const genres = filters.genre ? filters.genre.split(',') : [];
  return (
    <Popover
      width={460}
      position="bottom-start"
      shadow="md"
      withArrow
      arrowPosition="center"
      withinPortal
      trapFocus
      returnFocus
    >
      <Indicator
        inline
        color="red"
        size={10}
        offset={1}
        withBorder
        disabled={!activeCount}
        zIndex={1}
      >
        <Popover.Target>
          <Tooltip label={activeCount ? activeLabel : 'Library filters'}>
            <ActionIcon
              size="input-sm"
              variant={activeCount ? 'light' : 'default'}
              aria-label="Filter library"
              aria-description={activeCount ? activeLabel : undefined}
              data-filter-active={activeCount ? true : undefined}
            >
              <Filter size={17} aria-hidden="true" />
            </ActionIcon>
          </Tooltip>
        </Popover.Target>
      </Indicator>
      <Popover.Dropdown style={{ maxWidth: 'calc(100vw - 24px)' }}>
        <Stack gap="sm">
          <Text size="sm" fw={600}>
            Filters
          </Text>
          <ScrollArea.Autosize
            mah="min(500px, calc(100dvh - 240px))"
            type="auto"
            offsetScrollbars
          >
            <Stack gap="sm">
              {(bothTypes || admin) &&
                group(
                  'Content',
                  <>
                    {bothTypes && (
                      <Select
                        label="Content type"
                        allowDeselect={false}
                        comboboxProps={{ withinPortal: false }}
                        value={filters.type || 'all'}
                        data={[
                          { value: 'all', label: 'All' },
                          { value: 'movie', label: 'Movies' },
                          { value: 'series', label: 'Series' },
                        ]}
                        onChange={(value) =>
                          onChange({
                            type: value,
                            category: '',
                            content_id: '',
                          })
                        }
                      />
                    )}
                    {admin &&
                      select('blocked', 'Availability', [
                        { value: 'false', label: 'Available' },
                        { value: 'true', label: 'Blocked' },
                      ])}
                  </>
                )}
              {group(
                'Provider',
                <>
                  {select(
                    'account',
                    'Provider account',
                    (options.accounts || []).map((row) => ({
                      value: String(row.id),
                      label: row.name,
                    })),
                    'All accounts'
                  )}
                  {select(
                    'category',
                    'Provider category',
                    (options.categories || [])
                      .filter(
                        (row) =>
                          !filters.type ||
                          filters.type === 'all' ||
                          row.category_type === filters.type
                      )
                      .map((row) => ({
                        value: String(row.id),
                        label: row.name,
                      })),
                    'All categories'
                  )}
                  {dateRange('Added', 'added_since', 'added_until')}
                  {!!filters.content_id && (
                    <Button
                      variant="light"
                      size="compact-sm"
                      onClick={() => onChange({ content_id: '' })}
                    >
                      Clear title filter
                    </Button>
                  )}
                </>
              )}
              {group(
                'File data',
                <>
                  {select(
                    'audio_language',
                    'DUB',
                    actual('audio_language', 'audio_languages', languageLabel)
                  )}
                  {select(
                    'subtitle_language',
                    'SUB',
                    actual(
                      'subtitle_language',
                      'subtitle_languages',
                      languageLabel
                    )
                  )}
                  {select(
                    'resolution',
                    'Resolution',
                    actual('resolution', 'resolution')
                  )}
                  {select(
                    'video_feature',
                    'Feature',
                    actual('video_feature', 'video_features', featureLabel)
                  )}
                  {select(
                    'container_extension',
                    'Format',
                    actual('container_extension', 'container_extensions')
                  )}
                </>
              )}
              {group(
                'Metadata',
                <>
                  <TagsInput
                    label="Genre contains"
                    placeholder={
                      genres.length
                        ? undefined
                        : 'Enter a genre and press Enter'
                    }
                    clearable
                    splitChars={[',']}
                    maxTags={10}
                    style={{ gridColumn: '1 / -1' }}
                    styles={{ input: { minHeight: 72 } }}
                    value={genres}
                    onChange={(value) =>
                      onChange({
                        genre: value
                          .map((term) => term.trim())
                          .filter(Boolean)
                          .join(','),
                      })
                    }
                  />
                  {select('adult_mode', 'Adult content', [
                    { value: 'only', label: 'Only adult content' },
                    { value: 'exclude', label: 'Exclude adult content' },
                  ])}
                  {select('anime_mode', 'Anime', [
                    { value: 'only', label: 'Only anime' },
                    { value: 'exclude', label: 'Exclude anime' },
                  ])}
                  {select(
                    'metadata_status',
                    'Metadata',
                    [
                      { value: 'enriched', label: 'Enriched' },
                      {
                        value: 'missing_metadata',
                        label: 'Not enriched',
                      },
                      { value: 'missing_id', label: 'No TMDB ID' },
                      {
                        value: 'missing_external_ids',
                        label: 'No external ID',
                      },
                    ],
                    'Any'
                  )}
                  {select(
                    'locked',
                    'Metadata protection',
                    [
                      { value: 'true', label: 'Protected' },
                      { value: 'false', label: 'Unlocked' },
                    ],
                    'Protection'
                  )}
                  {dateRange('Released', 'released_since', 'released_until')}
                </>
              )}
            </Stack>
          </ScrollArea.Autosize>
          <Button
            size="compact-xs"
            variant="subtle"
            disabled={!activeCount}
            onClick={() =>
              onChange({
                ...Object.fromEntries(
                  LIBRARY_EXTRA_FILTERS.map((field) => [field, ''])
                ),
                ...(bothTypes ? { type: 'all' } : {}),
              })
            }
          >
            Reset filters
          </Button>
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}
