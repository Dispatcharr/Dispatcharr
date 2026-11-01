import React, { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Flex,
  Group,
  Indicator,
  MultiSelect,
  Paper,
  Popover,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Table,
  Tabs,
  TabsList,
  TabsPanel,
  TabsTab,
  TagsInput,
  Text,
  TextInput,
  Tooltip,
} from '@mantine/core';
import {
  ArrowDown,
  ArrowUp,
  Ban,
  Eye,
  Filter,
  Trash2,
  Undo2,
} from 'lucide-react';
import API from '../../api';
import ConfirmationDialog from '../ConfirmationDialog.jsx';
import { LibraryDialog } from '../LibraryDialogs.jsx';
import LibraryPreviewModal from '../LibraryPreviewModal.jsx';
import ListPagination from '../ListPagination.jsx';
import { SensitiveValue } from '../SensitiveFields.jsx';
import { formatApiError } from '../../utils';
import { showNotification } from '../../utils/notificationUtils.js';
import { metadataLanguageLabel } from '../../utils/vodMetadataLanguages.js';
import {
  CONTENT_MODES,
  METADATA_SOURCES,
  NAME_PLACEHOLDERS,
  OUTPUT_GROUPS,
  OUTPUT_MODES,
  exampleName,
  featureOptions,
  fieldError,
  generalError,
  isBlankEdition,
  languageOptions,
  newProfile,
  profileErrors,
  profilePayload,
  profileValidation,
  resolutionOptions,
  tabHasError,
} from '../../utils/vodProfiles';
import {
  DragHandle,
  EditionRulesEditor,
  SortableItem,
  SortableList,
} from './VODProfileRuleEditors.jsx';
import VODProfileCategories from './VODProfileCategories.jsx';
import editorClasses from './AccountEditor.module.css';

const initialValues = (profile) => ({ ...newProfile(), ...profile });

const helpLabel = (label, help) => (
  <Group gap={5} wrap="nowrap">
    <Text span inherit>
      {label}
    </Text>
    <Tooltip
      label={help}
      multiline
      maw={360}
      withArrow
      events={{ hover: true, focus: true, touch: true }}
    >
      <Text
        span
        size="xs"
        c="dimmed"
        tabIndex={0}
        aria-label={`${label} help`}
        style={{ cursor: 'help' }}
      >
        ⓘ
      </Text>
    </Tooltip>
  </Group>
);

function Section({ title, action, children }) {
  return (
    <Paper withBorder p="sm">
      <Stack gap={4} style={{ minWidth: 0 }} role="group" aria-label={title}>
        <Group justify="space-between" wrap="nowrap">
          <Text fw={600}>{title}</Text>
          {action}
        </Group>
        {children}
      </Stack>
    </Paper>
  );
}

function GeneralTab({ values, saved, options, errors, set }) {
  const insert = (placeholder) =>
    set('name_template', `${values.name_template} {${placeholder}}`.trim());
  return (
    <Stack gap="md">
      <Section
        title="Profile"
        action={
          <Tooltip
            label={
              saved.is_default
                ? 'Make another profile the default to change this.'
                : 'Users without an active VOD profile receive the default profile. There is only one default.'
            }
            multiline
            maw={320}
            withArrow
            events={{ hover: true, focus: true, touch: true }}
          >
            <span style={{ display: 'inline-flex' }}>
              <Switch
                size="sm"
                label="Default"
                labelPosition="left"
                checked={values.is_default}
                disabled={saved.is_default}
                error={errors.is_default}
                onChange={(event) =>
                  set('is_default', event.currentTarget.checked)
                }
              />
            </span>
          </Tooltip>
        }
      >
        <TextInput
          label="Name"
          withAsterisk
          value={values.name}
          error={errors.name}
          onChange={(event) => set('name', event.currentTarget.value)}
        />
      </Section>
      <Section title="Output">
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md" verticalSpacing="xs">
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              {helpLabel(
                'Entries',
                'Compact offers one entry per title plus its editions; the failover order picks the source and its fallbacks. Sources offers every provider source as its own entry, as the provider does; add {provider} to the format to tell similar sources apart. Editions and failover only apply to Compact, but are kept when you switch.'
              )}
            </Text>
            <SegmentedControl
              aria-label="Entries"
              value={values.output_mode}
              onChange={(value) => set('output_mode', value)}
              data={OUTPUT_MODES}
            />
          </Stack>
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              {helpLabel(
                'Categories',
                'Provider keeps the categories of the providers. Movie & Series offers all movies in one category and all series in another.'
              )}
            </Text>
            <SegmentedControl
              aria-label="Categories"
              value={values.output_groups}
              onChange={(value) => set('output_groups', value)}
              data={OUTPUT_GROUPS}
            />
          </Stack>
          <Select
            label={helpLabel(
              'Title',
              'Provider keeps the titles of the providers. Clean title uses the titles cleaned up in the Library. A language uses the Library title in that language, falling back to the Library language order. Titles edited in the Library win except for Provider.'
            )}
            aria-label="Title"
            value={values.title_source}
            allowDeselect={false}
            error={errors.title_source}
            onChange={(value) => set('title_source', value || 'provider')}
            data={[
              { value: 'provider', label: 'Provider' },
              { value: 'clean', label: 'Clean title' },
              ...options.metadata_languages.map((language) => ({
                value: language,
                label: metadataLanguageLabel(language),
              })),
            ]}
          />
          <Stack gap={4}>
            <Text size="sm" fw={500}>
              {helpLabel(
                'Metadata',
                'Provider keeps the description, genres, rating, cast and artwork of the source. Enriched uses the Library metadata including your edits. Descriptions follow the Title language; with Provider or Clean title they use the first Library language. TMDB only translates titles and descriptions, so genres and cast stay in English. Lists get description, genre, rating and year; details get everything.'
              )}
            </Text>
            <SegmentedControl
              aria-label="Metadata"
              value={values.metadata_source}
              onChange={(value) => set('metadata_source', value)}
              data={METADATA_SOURCES}
            />
          </Stack>
        </SimpleGrid>
        <TextInput
          label={helpLabel(
            'Format',
            'How titles are named in clients. {title} is required; empty placeholders and their separators are left out.'
          )}
          aria-label="Format"
          value={values.name_template}
          error={errors.name_template}
          onChange={(event) => set('name_template', event.currentTarget.value)}
        />
        <Group gap={6}>
          {NAME_PLACEHOLDERS.map((placeholder) => (
            <Tooltip key={placeholder.value} label={placeholder.help}>
              <Badge
                component="button"
                type="button"
                variant="light"
                color="gray"
                style={{ cursor: 'pointer', textTransform: 'none' }}
                aria-label={`Insert ${placeholder.value}`}
                onClick={() => insert(placeholder.value)}
              >
                {`{${placeholder.value}}`}
              </Badge>
            </Tooltip>
          ))}
        </Group>
        <Text size="sm" c="dimmed">
          Example: {exampleName(values.name_template)}
        </Text>
      </Section>
    </Stack>
  );
}

function ContentTab({ values, options, errors, set }) {
  const filters = values.content_filters;
  const setFilter = (key, value) =>
    set('content_filters', { ...filters, [key]: value });
  const languages = useMemo(
    () => languageOptions(options.languages),
    [options.languages]
  );
  const features = featureOptions(options.video_features);
  const resolutions = resolutionOptions(options.resolutions);
  return (
    <Stack gap="md">
      <Section title="Filters">
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="sm">
          <MultiSelect
            label={helpLabel(
              'DUB languages',
              'Sources need at least one of these audio languages. Unknown languages never match.'
            )}
            aria-label="DUB languages"
            searchable
            clearable
            value={filters.audio_languages || []}
            onChange={(value) => setFilter('audio_languages', value)}
            data={languages}
          />
          <MultiSelect
            label={helpLabel(
              'SUB languages',
              'Sources need at least one of these subtitle languages. Unknown languages never match.'
            )}
            aria-label="SUB languages"
            searchable
            clearable
            value={filters.subtitle_languages || []}
            onChange={(value) => setFilter('subtitle_languages', value)}
            data={languages}
          />
          <Select
            label="Minimum resolution"
            value={String(filters.resolution_min || 0)}
            allowDeselect={false}
            onChange={(value) => setFilter('resolution_min', Number(value))}
            data={resolutions}
          />
          <Select
            label="Maximum resolution"
            value={String(filters.resolution_max || 0)}
            allowDeselect={false}
            error={fieldError(errors, 'content_filters', 'resolution_max')}
            onChange={(value) => setFilter('resolution_max', Number(value))}
            data={resolutions}
          />
          <MultiSelect
            label="Required features"
            value={filters.required_features || []}
            onChange={(value) => setFilter('required_features', value)}
            data={features}
          />
          <MultiSelect
            label="Excluded features"
            value={filters.excluded_features || []}
            error={fieldError(errors, 'content_filters', 'excluded_features')}
            onChange={(value) => setFilter('excluded_features', value)}
            data={features}
          />
          <TagsInput
            label={helpLabel(
              'Exclude genres',
              'Titles whose genre contains one of these terms.'
            )}
            aria-label="Exclude genres"
            clearable
            value={filters.excluded_genres || []}
            onChange={(value) => setFilter('excluded_genres', value)}
          />
          <SimpleGrid cols={3} spacing="sm">
            <Select
              label="Anime"
              value={filters.anime_mode || ''}
              allowDeselect={false}
              onChange={(value) => setFilter('anime_mode', value)}
              data={CONTENT_MODES}
            />
            <Select
              label="Adult content"
              value={filters.adult_mode || ''}
              allowDeselect={false}
              onChange={(value) => setFilter('adult_mode', value)}
              data={CONTENT_MODES}
            />
            <Select
              label={helpLabel(
                'No TMDB ID',
                'Titles without a TMDB ID, as the Library metadata filter counts them: neither matched in the Library nor identified by the provider. With Enriched metadata, clients also receive the TMDB and IMDb IDs matched in the Library.'
              )}
              aria-label="No TMDB ID"
              value={filters.missing_tmdb_mode || ''}
              allowDeselect={false}
              onChange={(value) => setFilter('missing_tmdb_mode', value)}
              data={CONTENT_MODES}
            />
          </SimpleGrid>
        </SimpleGrid>
        {generalError(errors, 'content_filters') && (
          <Text size="sm" c="red">
            {generalError(errors, 'content_filters')}
          </Text>
        )}
      </Section>
    </Stack>
  );
}

const FAILOVER_CRITERIA = [
  { value: 'provider', label: 'Provider order' },
  { value: 'audio_language', label: 'DUB language order' },
  { value: 'subtitle_language', label: 'SUB language order' },
  { value: 'resolution', label: 'Resolution' },
  { value: 'metadata_completeness', label: 'Most complete metadata' },
];

const criterionOf = (value) =>
  value.startsWith('resolution_') ? 'resolution' : value;

function Criterion({
  index,
  criterion,
  enabled,
  direction,
  onToggle,
  onDirection,
}) {
  return (
    <SortableItem index={index}>
      {(sortable) => (
        <Paper
          ref={sortable.setNodeRef}
          withBorder
          px="sm"
          py={8}
          style={{ ...sortable.style, opacity: enabled ? 1 : 0.55 }}
        >
          <Group justify="space-between" wrap="nowrap">
            <Group gap="sm" wrap="nowrap">
              <DragHandle label={criterion.label} sortable={sortable} />
              <Text size="sm" fw={600}>
                {criterion.label}
              </Text>
            </Group>
            <Group gap="sm" wrap="nowrap">
              {criterion.value === 'resolution' && enabled && (
                <Select
                  size="xs"
                  w={140}
                  aria-label="Resolution preference"
                  value={direction}
                  allowDeselect={false}
                  onChange={onDirection}
                  data={[
                    { value: 'resolution_desc', label: 'Highest first' },
                    { value: 'resolution_asc', label: 'Lowest first' },
                  ]}
                />
              )}
              <Switch
                aria-label={`Use ${criterion.label}`}
                checked={enabled}
                onChange={(event) => onToggle(event.currentTarget.checked)}
              />
            </Group>
          </Group>
        </Paper>
      )}
    </SortableItem>
  );
}

function OrderList({ title, help, value, data, onChange }) {
  const labels = new Map(data.map((item) => [item.value, item.label]));
  const move = (index, offset) => {
    const next = [...value];
    const [item] = next.splice(index, 1);
    next.splice(index + offset, 0, item);
    onChange(next);
  };
  return (
    <Stack gap={6}>
      <Text size="sm" fw={500}>
        {helpLabel(title, help)}
      </Text>
      {value.map((item, index) => (
        <Paper key={item} withBorder px="sm" py={4}>
          <Group justify="space-between" wrap="nowrap">
            <Text size="sm" truncate>
              {index + 1}. {labels.get(item) || `Unavailable (${item})`}
            </Text>
            <Group gap={2} wrap="nowrap">
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label={`Move ${labels.get(item) || item} up`}
                disabled={index === 0}
                onClick={() => move(index, -1)}
              >
                <ArrowUp size={16} />
              </ActionIcon>
              <ActionIcon
                variant="subtle"
                color="gray"
                aria-label={`Move ${labels.get(item) || item} down`}
                disabled={index === value.length - 1}
                onClick={() => move(index, 1)}
              >
                <ArrowDown size={16} />
              </ActionIcon>
              <ActionIcon
                variant="subtle"
                color="red"
                aria-label={`Remove ${labels.get(item) || item}`}
                onClick={() =>
                  onChange(value.filter((entry) => entry !== item))
                }
              >
                <Trash2 size={15} />
              </ActionIcon>
            </Group>
          </Group>
        </Paper>
      ))}
      <Select
        aria-label={`Add to ${title}`}
        placeholder="Add"
        searchable
        value={null}
        onChange={(item) => item && onChange([...value, item])}
        data={data.filter((item) => !value.includes(item.value))}
      />
    </Stack>
  );
}

function FailoverTab({ values, options, errors, set }) {
  const [order, setOrder] = useState(() => {
    const active = values.ranking.map(criterionOf);
    return [
      ...active,
      ...FAILOVER_CRITERIA.map((item) => item.value).filter(
        (item) => !active.includes(item)
      ),
    ];
  });
  const [direction, setDirection] = useState(
    values.ranking.includes('resolution_asc')
      ? 'resolution_asc'
      : 'resolution_desc'
  );
  const enabled = new Set(values.ranking.map(criterionOf));
  const publish = (nextOrder, nextEnabled, nextDirection = direction) =>
    set(
      'ranking',
      nextOrder
        .filter((item) => nextEnabled.has(item))
        .map((item) => (item === 'resolution' ? nextDirection : item))
    );
  const languages = languageOptions(options.languages);
  return (
    <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
      <Section title="Failover order">
        <SortableList
          items={order}
          onChange={(next) => {
            setOrder(next);
            publish(next, enabled);
          }}
        >
          <Stack gap="xs">
            {order.map((value, index) => (
              <Criterion
                key={value}
                index={index}
                criterion={FAILOVER_CRITERIA.find(
                  (item) => item.value === value
                )}
                enabled={enabled.has(value)}
                direction={direction}
                onDirection={(next) => {
                  setDirection(next);
                  publish(order, enabled, next);
                }}
                onToggle={(checked) => {
                  const next = new Set(enabled);
                  if (checked) next.add(value);
                  else next.delete(value);
                  publish(order, next);
                }}
              />
            ))}
          </Stack>
        </SortableList>
        {errors.ranking && (
          <Text size="sm" c="red">
            {errors.ranking}
          </Text>
        )}
      </Section>
      <Section title="Preferences">
        <Stack gap="md">
          <OrderList
            title="DUB language order"
            help="Used by DUB language order; the first language is preferred."
            value={values.audio_language_order}
            onChange={(value) => set('audio_language_order', value)}
            data={languages}
          />
          <OrderList
            title="SUB language order"
            help="Used by SUB language order; the first language is preferred."
            value={values.subtitle_language_order}
            onChange={(value) => set('subtitle_language_order', value)}
            data={languages}
          />
          <OrderList
            title="Provider order"
            help="Used by provider order. Providers that are not listed follow by account priority."
            value={values.provider_order.map(String)}
            onChange={(value) => set('provider_order', value.map(Number))}
            data={options.accounts.map((account) => ({
              value: String(account.id),
              label: account.name,
            }))}
          />
        </Stack>
      </Section>
    </SimpleGrid>
  );
}

function UsersTab({ values, saved, options, profiles }) {
  const active = new Map(
    profiles
      .filter((profile) => profile.is_active)
      .flatMap((profile) => profile.users.map((user) => [user, profile]))
  );
  const rows = options.users.flatMap((user) => {
    if ((saved.users || []).includes(user.id))
      return [{ ...user, reason: 'Assigned in the user settings' }];
    if (saved.is_default && !active.has(user.id))
      return [{ ...user, reason: 'No active profile assigned' }];
    return [];
  });
  return (
    <Stack gap="sm">
      {!values.is_active && !saved.is_default && rows.length > 0 && (
        <Alert color="yellow">
          This profile is disabled, so these users receive the default profile.
        </Alert>
      )}
      <Table striped verticalSpacing={6} fz="sm">
        <Table.Thead>
          <Table.Tr>
            <Table.Th>User</Table.Th>
            <Table.Th>Receives this profile because</Table.Th>
          </Table.Tr>
        </Table.Thead>
        <Table.Tbody>
          {rows.map((user) => (
            <Table.Tr key={user.id}>
              <Table.Td>
                <SensitiveValue component="span" inherit>
                  {user.name}
                </SensitiveValue>
              </Table.Td>
              <Table.Td c="dimmed">{user.reason}</Table.Td>
            </Table.Tr>
          ))}
          {!rows.length && (
            <Table.Tr>
              <Table.Td colSpan={2} c="dimmed">
                No users have this profile yet. Assign it in the user settings.
              </Table.Td>
            </Table.Tr>
          )}
        </Table.Tbody>
      </Table>
    </Stack>
  );
}

const EMPTY_PREVIEW_FILTERS = {
  contentType: 'movie',
  excluded: false,
  account: null,
  category: null,
};

const titleName = (row) => `${row.title}${row.year ? ` (${row.year})` : ''}`;

// Built like the category filter of the account dialogs.
function PreviewFilters({ value, onChange, options }) {
  const active = !!(value.excluded || value.account || value.category);
  const categories = [
    ...new Map(
      options.categories
        .filter(
          (category) =>
            category.category_type === value.contentType &&
            (!value.account || String(category.account) === value.account)
        )
        .map((category) => [
          String(category.category),
          { value: String(category.category), label: category.name },
        ])
    ).values(),
  ].sort((a, b) => a.label.localeCompare(b.label));
  const update = (patch) => onChange({ ...value, ...patch });
  return (
    <Popover position="bottom-end" withArrow trapFocus returnFocus>
      <Indicator
        inline
        color="red"
        size={10}
        offset={1}
        withBorder
        disabled={!active}
        zIndex={1}
      >
        <Popover.Target>
          <Tooltip label={active ? 'Title filter active' : 'Filter titles'}>
            <ActionIcon
              size="input-xs"
              variant={active ? 'light' : 'default'}
              aria-label="Filter titles"
            >
              <Filter size={16} aria-hidden="true" />
            </ActionIcon>
          </Tooltip>
        </Popover.Target>
      </Indicator>
      <Popover.Dropdown data-mantine-stop-propagation="true">
        <Stack gap="xs" w={260}>
          <Text size="sm" fw={600}>
            Show titles
          </Text>
          <SegmentedControl
            size="xs"
            fullWidth
            aria-label="Preview content"
            value={value.contentType}
            onChange={(contentType) => update({ contentType, category: null })}
            data={[
              { value: 'movie', label: 'Movies' },
              { value: 'series', label: 'Series' },
            ]}
          />
          <Select
            size="xs"
            label="Excluded"
            value={value.excluded ? 'yes' : 'no'}
            allowDeselect={false}
            comboboxProps={{ withinPortal: false }}
            onChange={(excluded) => update({ excluded: excluded === 'yes' })}
            data={[
              { value: 'no', label: 'No' },
              { value: 'yes', label: 'Yes' },
            ]}
          />
          <Select
            size="xs"
            label="M3U account"
            placeholder="Any"
            clearable
            value={value.account}
            comboboxProps={{ withinPortal: false }}
            onChange={(account) => update({ account, category: null })}
            data={options.accounts.map((account) => ({
              value: String(account.id),
              label: account.name,
            }))}
          />
          <Select
            size="xs"
            label="Category"
            placeholder="Any"
            clearable
            searchable
            value={value.category}
            comboboxProps={{ withinPortal: false }}
            onChange={(category) => update({ category })}
            data={categories}
          />
          <Button
            size="compact-xs"
            variant="subtle"
            data-mantine-stop-propagation="true"
            onClick={() =>
              onChange({
                ...EMPTY_PREVIEW_FILTERS,
                contentType: value.contentType,
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

function PreviewTab({
  values,
  saved,
  options,
  set,
  active,
  invalid,
  paginationContainer,
}) {
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [filters, setFilters] = useState(EMPTY_PREVIEW_FILTERS);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const [opened, setOpened] = useState(null);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);
  const { contentType } = filters;
  useEffect(() => setPage(1), [query, filters, pageSize]);

  const run = async (profile = values) => {
    setLoading(true);
    setFailed(false);
    try {
      setResult(
        await API.previewVODProfile({
          profile: profilePayload(profile),
          profile_id: saved.id ?? null,
          content_type: contentType,
          search: query,
          excluded: filters.excluded,
          account: filters.account ? Number(filters.account) : null,
          category: filters.category ? Number(filters.category) : null,
          page,
          page_size: pageSize,
        })
      );
    } catch {
      setResult(null);
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };

  // Refresh whenever the tab is shown or the filters change; settings
  // only change on the other tabs.
  useEffect(() => {
    if (active && !invalid) run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, invalid, query, filters, page, pageSize]);

  const toggleExcluded = (row) => {
    const excluded = row.excluded
      ? values.excluded_titles.filter(
          (title) =>
            !(title.content_type === contentType && title.id === row.id)
        )
      : [...values.excluded_titles, { content_type: contentType, id: row.id }];
    set('excluded_titles', excluded);
    run({ ...values, excluded_titles: excluded });
  };

  // The Library preview numbers this entry's sources in failover order and
  // greys out the rest with the reason, like the production source list.
  const openPreview = (row, entry) => {
    const order = entry?.fallbacks || [];
    const note = (source) => {
      if (order.includes(source.id))
        return { order: order.indexOf(source.id) + 1 };
      if (source.state === 'skipped')
        return { label: 'Excluded', reason: source.reason };
      if (source.entry && source.entry !== entry?.name)
        return { label: 'Other entry', reason: `Used by ${source.entry}.` };
      return {
        label: 'Not used',
        reason: entry
          ? 'Does not match the version of this entry.'
          : row.reason,
      };
    };
    setOpened({
      item: {
        content_type: contentType,
        content_id: row.id,
        source_id: entry?.source_id || null,
        name: row.title,
      },
      notes: Object.fromEntries(
        row.sources.map((source) => [source.id, note(source)])
      ),
    });
  };

  const rows = (result?.results || []).flatMap((row) =>
    row.entries.length
      ? row.entries.map((entry, index) => ({ row, entry, index }))
      : [{ row, entry: null, index: 0 }]
  );
  const empty = invalid
    ? 'Fix the highlighted fields to update the preview.'
    : failed
      ? 'The preview could not be loaded.'
      : loading && !result
        ? 'Loading…'
        : 'No titles match the current filters.';
  const pagination = (
    <ListPagination
      page={page}
      pageSize={pageSize}
      total={invalid ? 0 : result?.count || 0}
      onPageChange={setPage}
      onPageSizeChange={setPageSize}
    />
  );

  return (
    <Stack gap="xs" style={{ height: '100%', minHeight: 0 }}>
      <Flex gap="sm" align="center" wrap="wrap">
        <TextInput
          size="xs"
          aria-label="Search titles"
          placeholder="Search titles..."
          className={editorClasses.categorySearch}
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          onKeyDown={(event) => {
            // The dialog is a form; Enter must not save it.
            if (event.key === 'Enter') event.preventDefault();
          }}
        />
        <PreviewFilters
          value={filters}
          onChange={setFilters}
          options={options}
        />
        <Text size="xs" c="dimmed" ml="auto">
          {!invalid && result
            ? `${result.count.toLocaleString()} ${
                filters.excluded ? 'excluded ' : ''
              }${
                contentType === 'series'
                  ? 'series'
                  : result.count === 1
                    ? 'movie'
                    : 'movies'
              }`
            : ''}
        </Text>
      </Flex>

      <ScrollArea className={editorClasses.categoryTableFrame}>
        <Table
          striped
          stickyHeader
          highlightOnHover
          miw={680}
          className={editorClasses.categoryTable}
          style={{ opacity: loading && result ? 0.6 : 1 }}
        >
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Title</Table.Th>
              <Table.Th w="25%">Category</Table.Th>
              <Table.Th w={80} ta="center">
                Sources
              </Table.Th>
              <Table.Th w={90} ta="center">
                Actions
              </Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {(invalid || !rows.length) && (
              <Table.Tr>
                <Table.Td colSpan={4} ta="center" py="xl">
                  <Text size="sm" c="dimmed">
                    {empty}
                  </Text>
                </Table.Td>
              </Table.Tr>
            )}
            {!invalid &&
              rows.map(({ row, entry, index }) => (
                <Table.Tr
                  key={`${row.id}-${index}`}
                  aria-disabled={entry ? undefined : true}
                  style={{ opacity: entry ? 1 : 0.5 }}
                >
                  <Table.Td>
                    <Tooltip
                      label={row.reason}
                      disabled={!row.reason}
                      withArrow
                    >
                      <Text size="sm" truncate>
                        {entry ? entry.name : titleName(row)}
                      </Text>
                    </Tooltip>
                  </Table.Td>
                  <Table.Td>
                    <Text size="sm" truncate>
                      {entry?.category || '—'}
                    </Text>
                  </Table.Td>
                  <Table.Td ta="center">{entry ? entry.sources : 0}</Table.Td>
                  <Table.Td>
                    <Group gap={2} justify="center" wrap="nowrap">
                      <Tooltip label="Open title and profile sources">
                        <ActionIcon
                          variant="subtle"
                          aria-label={`Open ${titleName(row)}`}
                          onClick={() => openPreview(row, entry)}
                        >
                          <Eye size={16} />
                        </ActionIcon>
                      </Tooltip>
                      <Tooltip
                        label={
                          row.excluded
                            ? 'Include again'
                            : 'Exclude from this profile'
                        }
                      >
                        <ActionIcon
                          variant="subtle"
                          color={row.excluded ? 'gray' : 'red'}
                          aria-label={`${row.excluded ? 'Include' : 'Exclude'} ${titleName(row)}`}
                          onClick={() => toggleExcluded(row)}
                        >
                          {row.excluded ? (
                            <Undo2 size={16} />
                          ) : (
                            <Ban size={16} />
                          )}
                        </ActionIcon>
                      </Tooltip>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
          </Table.Tbody>
        </Table>
      </ScrollArea>
      {active &&
        (paginationContainer
          ? createPortal(pagination, paginationContainer)
          : pagination)}
      {opened && (
        <LibraryPreviewModal
          item={opened.item}
          sourceNotes={opened.notes}
          inStack
          onClose={() => setOpened(null)}
        />
      )}
    </Stack>
  );
}

const ruleInfo = (profile) => ({
  states: profile.category_rule_states || {},
  counts: profile.category_rule_counts || {},
});

export default function VODProfileDialog({
  profile,
  profiles,
  options,
  onClose,
  onSaved,
}) {
  const initial = useMemo(() => initialValues(profile), [profile]);
  const [values, setValues] = useState(initial);
  const [serverErrors, setServerErrors] = useState({});
  const [submitted, setSubmitted] = useState(false);
  const [detail, setDetail] = useState('');
  const [tab, setTab] = useState('general');
  const [saving, setSaving] = useState(false);
  const [rules, setRules] = useState(() => ruleInfo(profile));
  const [paginationContainer, setPaginationContainer] = useState(null);
  const dirty = JSON.stringify(values) !== JSON.stringify(initial);
  const [discarding, setDiscarding] = useState(null);
  const clientErrors = profileValidation(values, { submitted });
  const errors = { ...serverErrors, ...clientErrors };

  const set = (field, value) => {
    setValues((current) => ({ ...current, [field]: value }));
    setServerErrors((current) => {
      if (!(field in current)) return current;
      const next = { ...current };
      delete next[field];
      return next;
    });
  };

  // Import rules are saved on their own; refresh what they decide.
  const refreshRules = async () => {
    try {
      setRules(ruleInfo(await API.getVODProfile(profile.id)));
    } catch {
      // The table keeps the previous rule results.
    }
  };
  const applyRules = (result) => {
    const applied = new Set(
      (result.category_updates || []).map((update) => update.target_id)
    );
    set(
      'category_choices',
      values.category_choices.filter((choice) => !applied.has(choice.relation))
    );
    refreshRules();
  };

  const firstTab = (found) =>
    [
      'general',
      'categories',
      'content',
      'editions',
      'failover',
      'preview',
    ].find((name) => tabHasError(name, found));

  const fail = (found) => {
    const next = firstTab(found);
    if (next) setTab(next);
    showNotification({
      title: 'Profile not saved',
      message: 'Check the highlighted fields.',
      color: 'red',
    });
  };

  // Blank editions are discarded only after asking, like unsaved M3U rules.
  const unlessBlankEditions = (proceed) => {
    if (!values.edition_rules.some(isBlankEdition)) return proceed(values);
    setTab('editions');
    setDiscarding(() => proceed);
  };
  const discardBlankEditions = () => {
    const kept = {
      ...values,
      edition_rules: values.edition_rules.filter(
        (rule) => !isBlankEdition(rule)
      ),
    };
    set('edition_rules', kept.edition_rules);
    setDiscarding(null);
    discarding(kept);
  };

  const save = (event) => {
    event.preventDefault();
    unlessBlankEditions(submit);
  };

  const submit = async (values) => {
    setSubmitted(true);
    const found = profileValidation(values, { submitted: true });
    if (Object.keys(found).length) {
      fail(found);
      return;
    }
    setSaving(true);
    setDetail('');
    try {
      const result = await API.saveVODProfile(
        profilePayload(values),
        profile.id
      );
      showNotification({ title: `Saved ${result.name}`, color: 'green' });
      onSaved(result);
    } catch (err) {
      const parsed = profileErrors(err.body);
      setServerErrors(parsed.errors);
      if (Object.keys(parsed.errors).length) fail(parsed.errors);
      else setDetail(parsed.detail || formatApiError(err));
    } finally {
      setSaving(false);
    }
  };

  const changeTab = (next) => {
    if (tab === 'editions') unlessBlankEditions(() => setTab(next));
    else setTab(next);
  };

  const sources = values.output_mode === 'variants';
  // Editions and failover shape Compact entries only; settings are kept.
  const compactOnly = (name, label) =>
    sources ? (
      <Tooltip
        label={`${label} only apply to Compact entries. Your settings are kept.`}
        withArrow
      >
        <span style={{ display: 'inline-flex' }}>
          <TabsTab value={name} disabled>
            {label}
          </TabsTab>
        </span>
      </Tooltip>
    ) : (
      tabLabel(name, label)
    );
  const tabLabel = (name, label) => (
    <TabsTab value={name} c={tabHasError(name, errors) ? 'red' : undefined}>
      {label}
    </TabsTab>
  );
  const props = { values, saved: initial, options, errors, set };

  return (
    <LibraryDialog
      title={profile.id ? `Edit ${profile.name}` : 'Add profile'}
      dirty={dirty}
      busy={saving}
      onClose={onClose}
      size="72vw"
      classNames={{
        content: editorClasses.content,
        body: editorClasses.body,
        header: editorClasses.header,
      }}
    >
      <form onSubmit={save} className={editorClasses.form}>
        <Tabs value={tab} onChange={changeTab} className={editorClasses.tabs}>
          <TabsList className={editorClasses.tabList}>
            {tabLabel('general', 'General')}
            {tabLabel('categories', 'Categories')}
            {tabLabel('content', 'Content')}
            {compactOnly('editions', 'Editions')}
            {compactOnly('failover', 'Failover')}
            {tabLabel('users', 'Users')}
            {tabLabel('preview', 'Preview')}
          </TabsList>
          <TabsPanel value="general" className={editorClasses.panel}>
            <GeneralTab {...props} />
          </TabsPanel>
          <TabsPanel
            value="categories"
            className={`${editorClasses.panel} ${editorClasses.categoryPanel}`}
          >
            <VODProfileCategories
              {...props}
              ruleStates={rules.states}
              ruleCounts={rules.counts}
              onRulesChanged={refreshRules}
              onApplied={applyRules}
              active={tab === 'categories'}
              paginationContainer={paginationContainer}
            />
          </TabsPanel>
          <TabsPanel value="content" className={editorClasses.panel}>
            <ContentTab {...props} />
          </TabsPanel>
          <TabsPanel value="editions" className={editorClasses.panel}>
            <EditionRulesEditor
              rules={values.edition_rules}
              options={options}
              errors={errors}
              onChange={(rules) => set('edition_rules', rules)}
            />
            <ConfirmationDialog
              opened={!!discarding}
              onClose={() => setDiscarding(null)}
              onConfirm={discardBlankEditions}
              title="Unsaved changes"
              message="Discard unsaved changes? The affected rows are highlighted."
              cancelLabel="Keep editing"
              confirmLabel="Discard"
              zIndex={300}
            />
          </TabsPanel>
          <TabsPanel value="failover" className={editorClasses.panel}>
            <FailoverTab {...props} />
          </TabsPanel>
          <TabsPanel value="users" className={editorClasses.panel}>
            <UsersTab {...props} profiles={profiles} />
          </TabsPanel>
          <TabsPanel
            value="preview"
            className={`${editorClasses.panel} ${editorClasses.categoryPanel}`}
          >
            <PreviewTab
              values={values}
              saved={initial}
              options={options}
              set={set}
              active={tab === 'preview'}
              invalid={Object.keys(clientErrors).length > 0}
              paginationContainer={paginationContainer}
            />
          </TabsPanel>
        </Tabs>
        {detail && (
          <Alert color="red" mb="sm">
            {detail}
          </Alert>
        )}
        <Flex
          component="footer"
          className={`${editorClasses.footer} ${editorClasses.plainFooter} ${editorClasses.categoryFooter}`}
          mih={50}
          gap="xs"
          align="center"
        >
          <div
            ref={setPaginationContainer}
            className={editorClasses.paginationSlot}
          />
          <div className={editorClasses.categoryFooterActions}>
            <Button type="submit" loading={saving}>
              Save
            </Button>
          </div>
        </Flex>
      </form>
    </LibraryDialog>
  );
}
