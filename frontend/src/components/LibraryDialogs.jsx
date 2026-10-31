import { useState } from 'react';
import {
  ActionIcon,
  Badge,
  Button,
  Checkbox,
  Group,
  Image,
  NumberInput,
  Paper,
  Stack,
  Table,
  Text,
  Textarea,
  TextInput,
  Tabs,
  TagsInput,
  SimpleGrid,
  Switch,
  ScrollArea,
  Tooltip,
} from '@mantine/core';
import { ExternalLink } from 'lucide-react';
import api from '../api';
import { formatApiError } from '../utils';
import StackedModal from './StackedModal.jsx';
import ConfirmationDialog from './ConfirmationDialog.jsx';
import VODCategoryMetadataEditor from './forms/VODCategoryMetadataEditor.jsx';
import MetadataOriginBadges from './MetadataOriginBadges.jsx';
import { sourceMetadataOrigins } from '../utils/libraryMetadataOrigins.js';
import MEDIA_LANGUAGES from '../../../apps/vod/media_languages.json';
import {
  VOD_METADATA_FIELDS,
  VOD_METADATA_LABELS,
  VOD_RESOLUTIONS,
} from '../utils/vodSourceMetadata';
import CategoryCleanupFields from './CategoryCleanupFields.jsx';
import { SensitiveTextInput } from './SensitiveFields.jsx';
import {
  notifyLibraryError,
  notifyLibrarySuccess,
  libraryFieldError,
} from '../utils/libraryFeedback.js';
import { librarySearch } from '../utils/librarySearch.js';
import { tmdbUrl } from '../utils/components/SeriesModalUtils.js';
import { showNotification } from '../utils/notificationUtils.js';
import classes from './LibraryWorkspace.module.css';

export function LibraryDialog({
  title,
  dirty = false,
  busy = false,
  onClose,
  children,
  size = 'lg',
  classNames,
}) {
  const [discard, setDiscard] = useState(false);
  return (
    <>
      <StackedModal
        opened
        keepVisibleInStack
        onClose={() => !busy && (dirty ? setDiscard(true) : onClose())}
        title={title}
        size={size}
        centered
        classNames={classNames}
        closeButtonProps={{ 'aria-label': `Close ${title}` }}
        closeOnClickOutside={!busy}
        closeOnEscape={!busy}
      >
        {children}
      </StackedModal>
      <ConfirmationDialog
        opened={discard}
        onClose={() => setDiscard(false)}
        onConfirm={onClose}
        title="Discard unsaved changes?"
        message="Your changes have not been saved."
        confirmLabel="Discard"
        cancelLabel="Continue editing"
      />
    </>
  );
}

function contentEditorValues(item, languages) {
  const metadata = item.metadata || {};
  return {
    display_name: item.display_name || item.name || '',
    clean_title: item.clean_title || '',
    description: item.description || '',
    year: item.year ?? '',
    genre: item.genre || '',
    rating: item.rating || '',
    metadata: {
      localized: Object.fromEntries(
        languages.map((language) => [
          language,
          {
            title: '',
            overview: '',
            tagline: '',
            ...metadata.localized?.[language],
          },
        ])
      ),
      release_date: metadata.release_date || '',
      runtime_minutes:
        metadata.runtime_minutes ??
        (item.duration_secs ? Math.round(item.duration_secs / 60) : ''),
      age_rating: metadata.age_rating || '',
      country: metadata.country || '',
      director: metadata.director || '',
      actors: metadata.actors || '',
      crew: metadata.crew || '',
      youtube_trailer: metadata.youtube_trailer || '',
      poster_url: metadata.poster_url || '',
      backdrop_url: metadata.backdrop_url || '',
      keywords: (metadata.keywords || [])
        .map((value) => (typeof value === 'string' ? value : value.name))
        .filter(Boolean),
      is_anime: !!metadata.is_anime,
      adult: !!(metadata.adult || item.is_adult),
      external_ids: Object.fromEntries(
        ['imdb_id', 'tvdb_id', 'wikidata_id'].map((key) => [
          key,
          metadata.external_ids?.[key] ||
            metadata[key] ||
            (key === 'imdb_id' ? item.imdb_id : '') ||
            '',
        ])
      ),
    },
  };
}

export function LibraryContentEditor({ item, onClose, onSaved }) {
  const languages = [
    ...new Set([
      ...(item.metadata_languages || ['en-US']),
      ...Object.keys(item.metadata?.localized || {}),
    ]),
  ];
  const initial = contentEditorValues(item, languages);
  const [draft, setDraft] = useState(initial);
  const [matchId, setMatchId] = useState(null);
  const [loadedTitle, setLoadedTitle] = useState(null);
  const [confirmMatch, setConfirmMatch] = useState(false);
  const [lookupBusy, setLookupBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const dirty = !!matchId || JSON.stringify(draft) !== JSON.stringify(initial);
  const loadMatch = (metadata) => {
    // Show the title the Library will use: the first configured translation.
    const title =
      languages
        .map((language) => metadata.localized?.[language]?.title)
        .find(Boolean) ||
      metadata.original_title ||
      item.name;
    const date = metadata.release_date || '';
    // The cleanup title is derived from the provider title, not from TMDB.
    setDraft((current) =>
      contentEditorValues(
        {
          name: title,
          clean_title: current.clean_title,
          description: metadata.overview || '',
          year: /^\d{4}/.test(date) ? Number(date.slice(0, 4)) : '',
          genre: (metadata.genres || [])
            .map((value) => value.name)
            .filter(Boolean)
            .join(', '),
          rating: metadata.rating == null ? '' : String(metadata.rating),
          metadata,
        },
        languages
      )
    );
    setMatchId(String(metadata.id));
    setLoadedTitle(title);
  };
  const update = (name, value) =>
    setDraft((current) => ({ ...current, [name]: value }));
  const updateMetadata = (name, value) =>
    setDraft((current) => ({
      ...current,
      metadata: { ...current.metadata, [name]: value },
    }));
  const changed = (values, original) =>
    Object.fromEntries(
      Object.entries(values).filter(
        ([key, value]) =>
          JSON.stringify(value) !== JSON.stringify(original[key])
      )
    );
  const save = async () => {
    if (busy || !dirty) return;
    setBusy(true);
    setError(null);
    // An unchanged loaded title follows the translations instead of being
    // stored as a manual title; an empty value also clears an earlier one.
    const patch = matchId
      ? {
          ...draft,
          display_name:
            draft.display_name === loadedTitle ? '' : draft.display_name,
          tmdb_id: matchId,
        }
      : changed(draft, initial);
    if (patch.metadata) {
      patch.metadata = matchId
        ? { ...draft.metadata }
        : changed(draft.metadata, initial.metadata);
      if (patch.metadata.localized && !matchId)
        patch.metadata.localized = Object.fromEntries(
          Object.entries(draft.metadata.localized)
            .map(([language, fields]) => [
              language,
              changed(fields, initial.metadata.localized[language] || {}),
            ])
            .filter(([, fields]) => Object.keys(fields).length)
        );
      if (patch.metadata.external_ids && !matchId)
        patch.metadata.external_ids = changed(
          draft.metadata.external_ids,
          initial.metadata.external_ids
        );
      if ('release_date' in patch.metadata)
        patch.metadata.release_date ||= null;
      if ('runtime_minutes' in patch.metadata)
        patch.metadata.runtime_minutes =
          patch.metadata.runtime_minutes === ''
            ? null
            : patch.metadata.runtime_minutes;
    }
    if ('year' in patch) patch.year ||= null;
    try {
      const result = await api.vodLibraryAction(
        'content',
        { content_type: item.content_type, id: item.content_id, ...patch },
        'PATCH'
      );
      notifyLibrarySuccess('Title metadata saved.');
      onSaved(result);
      onClose();
    } catch (err) {
      setError(err);
      notifyLibraryError(err);
      setConfirmMatch(false);
    } finally {
      setBusy(false);
    }
  };
  const section = (title, children) => (
    <Paper withBorder p="md">
      <Stack gap="sm">
        <Text fw={600}>{title}</Text>
        {children}
      </Stack>
    </Paper>
  );
  return (
    <LibraryDialog
      title="Edit title metadata"
      dirty={dirty}
      busy={busy || lookupBusy}
      onClose={onClose}
      size="xl"
    >
      <Stack gap="sm">
        <ScrollArea.Autosize mah="65dvh" offsetScrollbars>
          <Stack gap="sm">
            <LibraryMatchDialog
              item={{ ...item, source_id: null }}
              embedded
              onLoad={loadMatch}
              onBusyChange={setLookupBusy}
            />
            {section(
              'General',
              <>
                <TextInput
                  label="Title"
                  error={libraryFieldError(error, 'display_name')}
                  value={draft.display_name}
                  onChange={(event) =>
                    update('display_name', event.currentTarget.value)
                  }
                  maxLength={255}
                />
                <TextInput
                  label="Cleanup title"
                  error={libraryFieldError(error, 'clean_title')}
                  value={draft.clean_title}
                  onChange={(event) =>
                    update('clean_title', event.currentTarget.value)
                  }
                  maxLength={255}
                />
                <Textarea
                  label="Description"
                  error={libraryFieldError(error, 'description')}
                  value={draft.description}
                  onChange={(event) =>
                    update('description', event.currentTarget.value)
                  }
                  minRows={3}
                  maxRows={7}
                  autosize
                  maxLength={20000}
                />
                <SimpleGrid cols={{ base: 1, sm: 2 }}>
                  <NumberInput
                    label="Year"
                    error={libraryFieldError(error, 'year')}
                    value={draft.year}
                    min={1800}
                    max={2200}
                    allowDecimal={false}
                    onChange={(value) => update('year', value)}
                  />
                  <NumberInput
                    label="Rating"
                    value={draft.rating === '' ? '' : Number(draft.rating)}
                    min={0}
                    max={10}
                    decimalScale={2}
                    onChange={(value) => update('rating', String(value))}
                  />
                </SimpleGrid>
                <TextInput
                  label="Genres"
                  error={libraryFieldError(error, 'genre')}
                  value={draft.genre}
                  onChange={(event) =>
                    update('genre', event.currentTarget.value)
                  }
                  maxLength={255}
                />
              </>
            )}
            {section(
              'Translations',
              <Tabs defaultValue={languages[0]}>
                <Tabs.List>
                  {languages.map((language) => (
                    <Tabs.Tab key={language} value={language}>
                      {language}
                    </Tabs.Tab>
                  ))}
                </Tabs.List>
                {languages.map((language) => (
                  <Tabs.Panel key={language} value={language} pt="sm">
                    <Stack gap="sm">
                      {[
                        ['title', 'Title'],
                        ['overview', 'Description'],
                        ['tagline', 'Tagline'],
                      ].map(([field, label]) => {
                        const props = {
                          label: language + ' · ' + label,
                          error: libraryFieldError(
                            error,
                            `metadata.localized.${language}.${field}`
                          ),
                          value:
                            draft.metadata.localized[language][field] || '',
                          maxLength:
                            field === 'overview'
                              ? 20000
                              : field === 'title'
                                ? 255
                                : 2000,
                          onChange: (event) =>
                            updateMetadata('localized', {
                              ...draft.metadata.localized,
                              [language]: {
                                ...draft.metadata.localized[language],
                                [field]: event.currentTarget.value,
                              },
                            }),
                        };
                        return field === 'overview' ? (
                          <Textarea
                            key={field}
                            {...props}
                            minRows={3}
                            autosize
                            maxRows={7}
                          />
                        ) : (
                          <TextInput key={field} {...props} />
                        );
                      })}
                    </Stack>
                  </Tabs.Panel>
                ))}
              </Tabs>
            )}
            {section(
              'Details',
              <>
                <SimpleGrid cols={{ base: 1, sm: 2 }}>
                  <TextInput
                    label="Release date"
                    type="date"
                    error={libraryFieldError(error, 'metadata.release_date')}
                    value={draft.metadata.release_date}
                    onChange={(event) =>
                      updateMetadata('release_date', event.currentTarget.value)
                    }
                  />
                  <NumberInput
                    label="Runtime (minutes)"
                    min={0}
                    max={144000}
                    allowDecimal={false}
                    error={libraryFieldError(error, 'metadata.runtime_minutes')}
                    value={draft.metadata.runtime_minutes}
                    onChange={(value) =>
                      updateMetadata('runtime_minutes', value)
                    }
                  />
                </SimpleGrid>
                {[
                  ['age_rating', 'Age rating'],
                  ['country', 'Country'],
                  ['director', 'Director / creator'],
                  ['actors', 'Cast'],
                  ['crew', 'Crew'],
                ].map(([field, label]) => (
                  <TextInput
                    key={field}
                    label={label}
                    value={draft.metadata[field]}
                    error={libraryFieldError(error, `metadata.${field}`)}
                    maxLength={
                      field === 'age_rating'
                        ? 50
                        : field === 'actors' || field === 'crew'
                          ? 4000
                          : 2000
                    }
                    onChange={(event) =>
                      updateMetadata(field, event.currentTarget.value)
                    }
                  />
                ))}
                <TagsInput
                  label="Keywords"
                  error={libraryFieldError(error, 'metadata.keywords')}
                  value={draft.metadata.keywords}
                  onChange={(value) => updateMetadata('keywords', value)}
                  maxTags={100}
                />
                <Switch
                  label="Anime"
                  checked={draft.metadata.is_anime}
                  onChange={(event) =>
                    updateMetadata('is_anime', event.currentTarget.checked)
                  }
                />
                <Switch
                  label="Adult content"
                  checked={draft.metadata.adult}
                  onChange={(event) =>
                    updateMetadata('adult', event.currentTarget.checked)
                  }
                />
              </>
            )}
            {section(
              'Artwork and trailer',
              <>
                {[
                  ['poster_url', 'Poster URL'],
                  ['backdrop_url', 'Backdrop URL'],
                  ['youtube_trailer', 'YouTube trailer ID or URL'],
                ].map(([field, label]) => (
                  <SensitiveTextInput
                    key={field}
                    label={label}
                    value={draft.metadata[field]}
                    error={libraryFieldError(error, `metadata.${field}`)}
                    maxLength={field === 'youtube_trailer' ? 2048 : 500}
                    onChange={(event) =>
                      updateMetadata(field, event.currentTarget.value)
                    }
                  />
                ))}
              </>
            )}
            {section(
              'External IDs',
              <>
                <TextInput
                  label="TMDB ID"
                  readOnly
                  value={matchId || item.tmdb_id || ''}
                />
                {[
                  ['imdb_id', 'IMDb ID'],
                  ['tvdb_id', 'TVDB ID'],
                  ['wikidata_id', 'Wikidata ID'],
                ].map(([field, label]) => (
                  <TextInput
                    key={field}
                    label={label}
                    value={draft.metadata.external_ids[field]}
                    error={libraryFieldError(
                      error,
                      `metadata.external_ids.${field}`
                    )}
                    maxLength={50}
                    onChange={(event) =>
                      updateMetadata('external_ids', {
                        ...draft.metadata.external_ids,
                        [field]: event.currentTarget.value,
                      })
                    }
                  />
                ))}
              </>
            )}
          </Stack>
        </ScrollArea.Autosize>
        <Group justify="flex-end">
          <Button
            disabled={!dirty || lookupBusy}
            loading={busy}
            onClick={() => (matchId ? setConfirmMatch(true) : save())}
          >
            Save
          </Button>
        </Group>
      </Stack>
      <ConfirmationDialog
        opened={confirmMatch}
        onClose={() => setConfirmMatch(false)}
        onConfirm={save}
        loading={busy}
        title="Save this TMDB match?"
        message="Save these metadata changes and combine identical canonical titles? Existing public IDs remain valid."
        confirmLabel="Save"
        confirmColor="blue"
      />
    </LibraryDialog>
  );
}

export function LibrarySourceEditor({
  items,
  selection,
  selectionCount = items.length,
  onClose,
  onSaved,
}) {
  const [metadataDirty, setMetadataDirty] = useState(false);
  const [target, setTarget] = useState(null);
  const [query, setQuery] = useState(
    items[0]?.clean_title || items[0]?.name || ''
  );
  const [year, setYear] = useState(items[0]?.year || '');
  const [targets, setTargets] = useState(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState(
    items[0]?.clean_title || items[0]?.name || ''
  );
  const [newYear, setNewYear] = useState(items[0]?.year || '');
  const [currentName, setCurrentName] = useState(items[0]?.name || '');
  const [currentId, setCurrentId] = useState(items[0]?.content_id);
  const dirty = metadataDirty;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const item = !selection?.all_matching && items.length === 1 ? items[0] : null;
  const itemOrigins = item?.effective_metadata
    ? sourceMetadataOrigins(item, item.content_type === 'series')
    : item?.metadata_origins || {};
  const search = async () => {
    if (searching || !item) return;
    setSearching(true);
    setSearchError(false);
    try {
      const params = librarySearch(query, items[0].content_type);
      const response = await api.getVODCanonicalTargets(
        new URLSearchParams({
          content_type: items[0].content_type,
          ...params,
          ...(!params.tmdb_id && year ? { year } : {}),
        })
      );
      let matches = response.results;
      if (!matches.length && params.tmdb_id) {
        const lookup = await api.vodLibraryAction('tmdb-lookup', {
          content_type: items[0].content_type,
          tmdb_id: params.tmdb_id,
        });
        matches = [
          {
            id: `tmdb:${params.tmdb_id}`,
            tmdb_id: params.tmdb_id,
            external: true,
            name:
              lookup.metadata.original_title ||
              lookup.metadata.title ||
              `TMDB ${params.tmdb_id}`,
            year: lookup.metadata.release_date?.slice(0, 4),
          },
        ];
      }
      setTargets(matches);
      if (!matches.length)
        showNotification({
          title: 'Move to title',
          message: 'No matching Library titles found.',
          color: 'orange',
        });
    } catch (err) {
      setSearchError(true);
      notifyLibraryError(err, 'Move to title');
    } finally {
      setSearching(false);
    }
  };
  const save = async (manual_metadata) => {
    if (!Object.keys(manual_metadata).length) return;
    await apply(manual_metadata);
  };
  const apply = async (manual_metadata, assignment = null) => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.vodLibraryAction(
        'source-metadata',
        {
          ...(selection || {
            items: items.map((row) => ({
              content_type: row.content_type,
              id: row.source_id,
            })),
          }),
          ...(assignment ? {} : { manual_metadata }),
          ...(assignment?.create
            ? {
                create_from_provider: true,
                title_name: assignment.name,
                title_year: assignment.year || null,
              }
            : assignment
              ? assignment.external
                ? { tmdb_id: assignment.tmdb_id }
                : { target_id: assignment.id }
              : {}),
        },
        'PATCH'
      );
      notifyLibrarySuccess(
        assignment ? 'Source moved to title.' : 'Source metadata saved.'
      );
      setCurrentName(result.metadata?.name || assignment?.name || currentName);
      setCurrentId(result.metadata?.id || currentId);
      setTarget(null);
      setCreating(false);
      onSaved(result);
      if (!assignment || !metadataDirty) onClose();
    } catch (err) {
      setError(err);
      setTarget(null);
      notifyLibraryError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <LibraryDialog
      title={item ? 'Edit source metadata' : `Edit ${selectionCount} sources`}
      dirty={dirty}
      busy={busy || searching}
      onClose={onClose}
      size="lg"
    >
      <Stack gap="sm">
        {item && (
          <Paper withBorder p="md">
            <Stack gap="xs">
              <Text fw={600}>{item.provider_name}</Text>
              <Text size="sm" c="dimmed">
                {item.account?.name} · {item.category?.name}
              </Text>
              <Group gap="md">
                {VOD_METADATA_FIELDS.map((field) => (
                  <Group key={field} gap={6} wrap="nowrap">
                    <Text size="xs" c="dimmed">
                      {VOD_METADATA_LABELS[field]}
                    </Text>
                    <MetadataOriginBadges
                      origins={itemOrigins}
                      field={field}
                      size="xs"
                    />
                  </Group>
                ))}
              </Group>
            </Stack>
          </Paper>
        )}
        {item && (
          <Paper
            withBorder
            p="md"
            style={error && { borderColor: 'var(--mantine-color-red-6)' }}
          >
            <Stack gap="sm">
              <Text fw={600}>Move to title</Text>
              {item && (
                <Text size="sm" c="dimmed">
                  Current: {currentName}
                </Text>
              )}
              <Group align="flex-end" gap="xs">
                <TextInput
                  label="Search Library title or TMDB ID"
                  placeholder="Title or tmdb:123"
                  value={query}
                  error={searchError}
                  onChange={(e) => {
                    setQuery(e.currentTarget.value);
                    setSearchError(false);
                    setTargets(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
                      e.preventDefault();
                      search();
                    }
                  }}
                  style={{ flex: 1 }}
                  disabled={busy || searching}
                />
                <NumberInput
                  label="Search year"
                  value={year}
                  onChange={(value) => {
                    setYear(value);
                    setTargets(null);
                  }}
                  min={1800}
                  max={2200}
                  allowDecimal={false}
                  w={110}
                  disabled={busy || searching}
                />
                <Button
                  onClick={search}
                  loading={searching}
                  disabled={busy || !query.trim()}
                >
                  Search
                </Button>
              </Group>
              {targets !== null && (
                <Stack gap="xs">
                  {targets.map((row) => {
                    const current = currentId === row.id;
                    return (
                      <Paper withBorder p="sm" key={row.id}>
                        <Group justify="space-between" wrap="nowrap">
                          <Stack gap={2} style={{ minWidth: 0 }}>
                            <Text fw={500} lineClamp={2}>
                              {row.name}
                              {row.year ? ` (${row.year})` : ''}
                            </Text>
                            <Text size="xs" c="dimmed">
                              {row.external
                                ? 'TMDB'
                                : `${row.source_count} sources`}
                              {row.tmdb_id ? ` · TMDB ${row.tmdb_id}` : ''}
                            </Text>
                          </Stack>
                          <Button
                            size="compact-sm"
                            variant="light"
                            disabled={current || busy}
                            onClick={() => setTarget(row)}
                          >
                            {current ? 'Current' : 'Move'}
                          </Button>
                        </Group>
                      </Paper>
                    );
                  })}
                </Stack>
              )}
              <Button
                variant="light"
                disabled={busy || searching}
                onClick={() => {
                  setNewName(item.clean_title || item.name || '');
                  setNewYear(item.year || '');
                  setCreating(true);
                }}
              >
                Create title from this source
              </Button>
            </Stack>
          </Paper>
        )}
        <VODCategoryMetadataEditor
          value={item?.manual_metadata || {}}
          languages={MEDIA_LANGUAGES}
          resolutions={VOD_RESOLUTIONS}
          bulk
          sourceMode
          invalidFields={[
            'audio_languages',
            'subtitle_languages',
            'resolution',
            'video_features',
          ].filter((field) =>
            libraryFieldError(error, `manual_metadata.${field}`)
          )}
          onDirtyChange={setMetadataDirty}
          onApply={save}
          applyLabel="Save"
          disabled={!dirty || busy || searching}
        />
        {creating && (
          <LibraryDialog
            title="Create title from source"
            onClose={() => setCreating(false)}
            busy={busy}
            dirty={
              newName !== (item.clean_title || item.name || '') ||
              newYear !== (item.year || '')
            }
          >
            <Stack gap="sm">
              <TextInput
                label="Title name"
                value={newName}
                maxLength={255}
                error={libraryFieldError(error, 'title_name')}
                onChange={(event) => {
                  setNewName(event.currentTarget.value);
                  setError(null);
                }}
              />
              <NumberInput
                label="Year"
                value={newYear}
                onChange={setNewYear}
                error={libraryFieldError(error, 'title_year')}
                min={1800}
                max={2200}
                allowDecimal={false}
              />
              <Group justify="flex-end">
                <Button
                  disabled={!newName.trim() || busy}
                  onClick={() =>
                    setTarget({
                      create: true,
                      name: newName.trim(),
                      year: newYear,
                    })
                  }
                >
                  Create
                </Button>
              </Group>
            </Stack>
          </LibraryDialog>
        )}
        <ConfirmationDialog
          opened={!!target}
          onClose={() => setTarget(null)}
          onConfirm={() => apply(null, target)}
          title={
            target?.create ? 'Create title and move source?' : 'Move to title?'
          }
          message={`Move this source to “${target?.name || ''}”${target?.year ? ` (${target.year})` : ''}? Other sources and provider data remain unchanged.${metadataDirty ? ' Unsaved source metadata will be kept in this editor, not saved.' : ''}`}
          confirmLabel={target?.create ? 'Create and move' : 'Move'}
          confirmColor="blue"
          loading={busy}
        />
      </Stack>
    </LibraryDialog>
  );
}

export function LibraryMatchDialog({
  item,
  onClose,
  onSaved,
  embedded = false,
  onLoad,
  onBusyChange,
}) {
  const [query, setQuery] = useState(item.clean_title || item.name);
  const [year, setYear] = useState(item.year || '');
  const [results, setResults] = useState([]);
  const [metadata, setMetadata] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [confirm, setConfirm] = useState(false);
  const lookup = async (id = null) => {
    if (busy || (!id && !query.trim())) return;
    setBusy(true);
    onBusyChange?.(true);
    setError('');
    try {
      const search = id
        ? { tmdb_id: String(id) }
        : librarySearch(query, item.content_type);
      const response = await api.vodLibraryAction('tmdb-lookup', {
        content_type: item.content_type,
        ...search,
        ...(!search.tmdb_id ? { year: year || null } : {}),
      });
      if (search.tmdb_id) {
        setMetadata(response.metadata);
        onLoad?.(response.metadata);
      } else {
        setResults(response.results || []);
        setMetadata(null);
        if (!response.results?.length)
          showNotification({
            title: 'TMDB search',
            message:
              'No matching titles found. Adjust the title or year and search again.',
            color: 'orange',
          });
      }
    } catch (err) {
      setError(formatApiError(err));
      notifyLibraryError(err, 'TMDB search');
    } finally {
      setBusy(false);
      onBusyChange?.(false);
    }
  };
  const match = async () => {
    setBusy(true);
    setError('');
    try {
      const result = await api.vodLibraryAction('tmdb-match', {
        content_type: item.content_type,
        id: item.source_id || item.content_id,
        source: !!item.source_id,
        tmdb_id: String(metadata.id),
      });
      notifyLibrarySuccess('TMDB match saved.');
      onSaved(result);
      onClose();
    } catch (err) {
      setError(formatApiError(err));
      notifyLibraryError(err);
      setConfirm(false);
    } finally {
      setBusy(false);
    }
  };
  const localized = metadata?.localized || {};
  const title = metadata?.original_title || item.name || '';
  const content = (
    <Stack gap="sm">
      <Paper withBorder p="md">
        <Stack gap="sm">
          {embedded && <Text fw={600}>Find the correct TMDB title</Text>}
          <Group align="flex-end">
            <TextInput
              label="Search title or TMDB ID"
              placeholder="Title or tmdb:123"
              value={query}
              error={!!error}
              onChange={(e) => {
                setQuery(e.currentTarget.value);
                setError('');
              }}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  lookup();
                }
              }}
              style={{ flex: 1 }}
            />
            <NumberInput
              label={embedded ? 'Search year' : 'Year'}
              value={year}
              onChange={setYear}
              min={1800}
              max={2200}
              allowDecimal={false}
              w={110}
            />
            <Button
              onClick={() => lookup()}
              disabled={!query.trim()}
              loading={busy}
            >
              {embedded ? 'Search TMDB' : 'Search'}
            </Button>
          </Group>
          {!!results.length && (
            <div className={classes.tableFrame}>
              <Table.ScrollContainer minWidth={400}>
                <Table
                  highlightOnHover
                  className={classes.cleanupTable}
                  aria-label="TMDB search results"
                >
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>Title</Table.Th>
                      <Table.Th>Year</Table.Th>
                      <Table.Th style={{ textAlign: 'center', width: 140 }}>
                        Actions
                      </Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {results.map((row) => (
                      <Table.Tr key={row.id}>
                        <Table.Td>
                          <Tooltip label={row.title || row.name}>
                            <Text size="sm" lineClamp={2}>
                              {row.title || row.name}
                            </Text>
                          </Tooltip>
                        </Table.Td>
                        <Table.Td>
                          {row.year ||
                            row.release_date?.slice(0, 4) ||
                            row.first_air_date?.slice(0, 4) ||
                            '—'}
                        </Table.Td>
                        <Table.Td style={{ textAlign: 'center' }}>
                          <Group gap="xs" justify="center" wrap="nowrap">
                            <Button
                              size="compact-sm"
                              variant="light"
                              onClick={() => lookup(row.id)}
                              disabled={busy}
                            >
                              {embedded ? 'Load' : 'Preview'}
                            </Button>
                            <Tooltip label="Open on TMDB">
                              <ActionIcon
                                component="a"
                                href={tmdbUrl(
                                  row.id,
                                  item.content_type === 'series'
                                    ? 'tv'
                                    : 'movie'
                                )}
                                target="_blank"
                                rel="noopener noreferrer"
                                aria-label={`Open ${row.title || row.name} on TMDB`}
                                variant="subtle"
                              >
                                <ExternalLink size={16} />
                              </ActionIcon>
                            </Tooltip>
                          </Group>
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </Table.ScrollContainer>
            </div>
          )}
        </Stack>
      </Paper>
      {metadata && !embedded && (
        <Paper withBorder p="md">
          <Stack gap="sm">
            <Group align="flex-start" wrap="nowrap">
              {metadata.poster_url && (
                <Image
                  src={metadata.poster_url}
                  w={100}
                  radius="md"
                  alt={title}
                />
              )}
              <Stack gap="xs">
                <Text fw={600}>{title}</Text>
                <Group gap="xs">
                  <Badge color="gray">TMDB {metadata.id}</Badge>
                  {metadata.release_date && (
                    <Badge color="gray">
                      {metadata.release_date.slice(0, 4)}
                    </Badge>
                  )}
                </Group>
              </Stack>
            </Group>
            {Object.entries(localized).map(([language, values]) => (
              <Paper withBorder p="sm" key={language}>
                <Stack gap={4}>
                  <Group gap="xs">
                    <Badge color="gray">{language}</Badge>
                    <Text size="sm" fw={500}>
                      {values.title || '—'}
                    </Text>
                  </Group>
                  {values.overview && <Text size="sm">{values.overview}</Text>}
                </Stack>
              </Paper>
            ))}
            <Group justify="flex-end">
              <Button onClick={() => setConfirm(true)} disabled={busy}>
                Use match
              </Button>
            </Group>
          </Stack>
        </Paper>
      )}
    </Stack>
  );
  if (embedded) return content;
  return (
    <LibraryDialog
      title="Match with TMDB"
      busy={busy}
      onClose={onClose}
      size="xl"
    >
      {content}
      <ConfirmationDialog
        opened={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={match}
        loading={busy}
        title="Use this TMDB match?"
        message={
          item.source_id
            ? 'Assign this provider source to the selected title? Other sources stay unchanged.'
            : 'Match this title and combine identical canonical titles? Existing public IDs remain valid.'
        }
        confirmLabel="Use match"
        confirmColor="blue"
      />
    </LibraryDialog>
  );
}

export function LibraryCategoryCleanup({ item, onClose, onSaved }) {
  const initial = {
    pattern: item.title_cleanup?.pattern || '',
    case_sensitive: !!item.title_cleanup?.case_sensitive,
  };
  const [draft, setDraft] = useState(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  const [valid, setValid] = useState(true);
  const dirty = JSON.stringify(draft) !== JSON.stringify(initial);
  const save = async () => {
    setBusy(true);
    setError(false);
    try {
      await api.vodLibraryAction(
        'category-cleanup',
        {
          account: item.account.id,
          category: item.category.id,
          title_cleanup: draft,
        },
        'PATCH'
      );
      notifyLibrarySuccess('Category title cleanup saved.');
      onSaved();
      onClose();
    } catch (err) {
      setError(true);
      notifyLibraryError(err);
    } finally {
      setBusy(false);
    }
  };
  return (
    <LibraryDialog
      title="Category title cleanup"
      dirty={dirty}
      busy={busy}
      onClose={onClose}
    >
      <Stack gap="sm">
        <Paper withBorder p="md">
          <Stack gap="sm">
            <Text size="sm">
              {item.account.name} · {item.category.name}
            </Text>
          </Stack>
        </Paper>
        <CategoryCleanupFields
          accountId={item.account.id}
          categoryId={item.category.id}
          value={draft}
          onChange={setDraft}
          onValidityChange={setValid}
          saveError={error}
        />
        <Text size="xs" c="dimmed">
          Used for title cleanup and TMDB search. Provider names are not
          rewritten.
        </Text>
        <Group justify="flex-end">
          <Button disabled={!dirty || !valid} loading={busy} onClick={save}>
            Save
          </Button>
        </Group>
      </Stack>
    </LibraryDialog>
  );
}
