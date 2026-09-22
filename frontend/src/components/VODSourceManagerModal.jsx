import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import {
  ActionIcon,
  Box,
  Button,
  Checkbox,
  Group,
  Modal,
  NumberInput,
  ScrollArea,
  Select,
  Stack,
  Table,
  TableTbody,
  TableTd,
  TableTh,
  TableThead,
  TableTr,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { useDebouncedValue } from '@mantine/hooks';
import { Eye, Trash2, Wrench } from 'lucide-react';
import API from '../api';
import { showNotification } from '../utils/notificationUtils';
import { normalizeLanguageCodes } from '../utils/languageCodes.js';
import { VOD_METADATA_FIELDS } from '../utils/vodMetadataOptions.js';
import ConfirmationDialog from './ConfirmationDialog.jsx';
import ListPagination from './ListPagination.jsx';
import VODMetadataFields from './VODMetadataFields.jsx';
import { showVODProfileRebuildNotice } from '../utils/vodProfileUpdates.js';

const EMPTY_FILTERS = {
  search: '',
  user: '',
  m3u_account: '',
  category: '',
  status: '',
  mode: '',
  content_type: '',
  started_after: '',
  started_before: '',
};
const EMPTY_METADATA = {
  audio_languages: [],
  subtitle_languages: [],
  resolution: '',
  video_features: [],
};
const EMPTY_MODES = Object.fromEntries(
  VOD_METADATA_FIELDS.map((field) => [field, 'keep'])
);

const formatBytes = (value) => {
  const bytes = Math.max(0, Number(value || 0));
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
};
const formatDuration = (value) => {
  const seconds = Math.max(0, Math.round(Number(value || 0)));
  if (seconds < 60) return `${seconds}s`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainingSeconds = seconds % 60;
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  return `${minutes}m ${remainingSeconds}s`;
};
const metadataSummary = (playback) => {
  const metadata = playback.source_effective_metadata?.values || {};
  return [
    metadata.resolution || (metadata.height ? `${metadata.height}p` : null),
    (metadata.audio_languages || metadata.languages || []).length
      ? `Audio: ${(metadata.audio_languages || metadata.languages).join(', ')}`
      : null,
    (metadata.subtitle_languages || []).length
      ? `Subs: ${metadata.subtitle_languages.join(', ')}`
      : null,
    metadata.container_extension
      ? `Format: ${metadata.container_extension}`
      : null,
  ]
    .filter(Boolean)
    .join(' • ');
};
const apiDate = (value, endOfDay = false) =>
  value
    ? new Date(
        `${value}T${endOfDay ? '23:59:59.999' : '00:00:00'}`
      ).toISOString()
    : '';
const playbackDayKey = (value) => new Date(value).toLocaleDateString('en-CA');
const playbackDayLabel = (value) =>
  new Date(value).toLocaleDateString(undefined, {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
const VODSourceManagerModal = ({
  opened,
  onClose,
  onOpenContent,
  embedded = false,
}) => {
  const [playbacks, setPlaybacks] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [debouncedSearch] = useDebouncedValue(filters.search, 350);
  const [facets, setFacets] = useState({
    users: [],
    accounts: [],
    categories: [],
  });
  const [stats, setStats] = useState({});
  const [retentionDays, setRetentionDays] = useState(0);
  const [retentionDraft, setRetentionDraft] = useState(0);
  const [savingRetention, setSavingRetention] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [manualPlayback, setManualPlayback] = useState(null);
  const [manualMetadata, setManualMetadata] = useState(EMPTY_METADATA);
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkMetadata, setBulkMetadata] = useState(EMPTY_METADATA);
  const [bulkModes, setBulkModes] = useState(EMPTY_MODES);
  const [selectedIds, setSelectedIds] = useState(new Set());
  const [selectAllMatching, setSelectAllMatching] = useState(false);
  const [excludedIds, setExcludedIds] = useState(new Set());
  const [deleteRequest, setDeleteRequest] = useState(null);
  const requestSequence = useRef(0);

  const queryFilters = useMemo(
    () => ({
      search: debouncedSearch,
      user: filters.user,
      m3u_account: filters.m3u_account,
      category: filters.category,
      status: filters.status,
      mode: filters.mode,
      content_type: filters.content_type,
      started_after: apiDate(filters.started_after),
      started_before: apiDate(filters.started_before, true),
    }),
    [debouncedSearch, filters]
  );
  const activeQueryFilters = useMemo(
    () =>
      Object.fromEntries(
        Object.entries(queryFilters).filter(([, value]) => Boolean(value))
      ),
    [queryFilters]
  );
  const hasFilters = Object.keys(activeQueryFilters).length > 0;
  const selectedCount = selectAllMatching
    ? Math.max(0, totalCount - excludedIds.size)
    : selectedIds.size;
  const clearSelection = () => {
    setSelectedIds(new Set());
    setExcludedIds(new Set());
    setSelectAllMatching(false);
  };

  const load = useCallback(async () => {
    const sequence = ++requestSequence.current;
    setLoading(true);
    try {
      const [response, statsResponse] = await Promise.all([
        API.getVODPlaybackSessions({
          ...activeQueryFilters,
          page,
          page_size: pageSize,
        }),
        API.getVODPlaybackStats(activeQueryFilters).catch(() => ({})),
      ]);
      if (sequence !== requestSequence.current) return;
      const rows =
        response?.results || (Array.isArray(response) ? response : []);
      setPlaybacks(rows);
      setTotalCount(response?.count ?? rows.length);
      setStats(statsResponse || {});
    } catch (error) {
      if (sequence !== requestSequence.current) return;
      setPlaybacks([]);
      setTotalCount(0);
      showNotification({
        title: 'Playback history unavailable',
        message: error?.message || 'The playback history could not be loaded.',
        color: 'red',
      });
    } finally {
      if (sequence === requestSequence.current) setLoading(false);
    }
  }, [activeQueryFilters, page, pageSize]);

  useEffect(() => {
    if (opened) load();
  }, [opened, load]);

  useEffect(() => {
    if (!opened) return;
    API.getVODPlaybackFacets()
      .then((response) => {
        const next = response || {};
        const days = Number(next.retention_days || 0);
        setFacets(next);
        setRetentionDays(days);
        setRetentionDraft(days);
      })
      .catch(() => setFacets({ users: [], accounts: [], categories: [] }));
  }, [opened]);

  const categoryOptions = useMemo(
    () =>
      (facets.categories || []).filter(
        (option) =>
          !filters.m3u_account ||
          String(option.m3u_account) === String(filters.m3u_account)
      ),
    [facets.categories, filters.m3u_account]
  );

  useEffect(() => {
    clearSelection();
  }, [activeQueryFilters, pageSize]);

  const updateFilter = (field, value) => {
    setFilters((current) => ({ ...current, [field]: value }));
    setPage(1);
  };

  const selectionPayload = (override = null) => {
    if (override) return { ids: override, filters: activeQueryFilters };
    return {
      ids: [...selectedIds],
      select_all: selectAllMatching,
      exclude_ids: [...excludedIds],
      filters: activeQueryFilters,
    };
  };

  const isSelected = (id) =>
    selectAllMatching ? !excludedIds.has(id) : selectedIds.has(id);
  const toggleRow = (id, checked) => {
    if (selectAllMatching) {
      setExcludedIds((current) => {
        const next = new Set(current);
        if (checked) next.delete(id);
        else next.add(id);
        return next;
      });
      return;
    }
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) next.add(id);
      else next.delete(id);
      return next;
    });
  };

  const openManualEditor = (playback) => {
    const effective = playback.source_effective_metadata || {};
    const values = effective.values || {};
    setManualMetadata({
      ...EMPTY_METADATA,
      ...Object.fromEntries(
        Object.entries(values).filter(([field]) =>
          VOD_METADATA_FIELDS.includes(field)
        )
      ),
    });
    setManualPlayback(playback);
  };

  const saveRetention = async () => {
    const days = Math.max(0, Math.min(3650, Number(retentionDraft || 0)));
    if (
      !facets.can_manage_history ||
      days === Number(retentionDays) ||
      savingRetention
    ) {
      return;
    }
    setSavingRetention(true);
    try {
      const response = await API.updateVODPlaybackRetention(days);
      const savedDays = Number(response?.retention_days ?? days);
      setRetentionDays(savedDays);
      setRetentionDraft(savedDays);
      showNotification({
        title: 'Playback history retention saved',
        message:
          savedDays > 0
            ? `Entries older than ${savedDays} days are cleaned in the background.`
            : 'Automatic cleanup is disabled.',
        color: 'green',
      });
      await load();
    } finally {
      setSavingRetention(false);
    }
  };

  const saveManualMetadata = async () => {
    const metadata = Object.fromEntries(
      Object.entries(manualMetadata).filter(
        ([, value]) =>
          value !== '' &&
          value !== null &&
          value !== undefined &&
          (!Array.isArray(value) || value.length > 0)
      )
    );
    if (metadata.audio_languages) {
      metadata.audio_languages = normalizeLanguageCodes(
        metadata.audio_languages
      );
    }
    if (metadata.subtitle_languages) {
      metadata.subtitle_languages = normalizeLanguageCodes(
        metadata.subtitle_languages
      );
    }
    setSaving(true);
    try {
      const result = await API.updateVODRelationManualMetadata(
        manualPlayback.content_type,
        manualPlayback.relation_id,
        metadata,
        Object.keys(metadata)
      );
      showNotification({
        title: 'Source metadata saved',
        message: 'Manual values are locked against later observations.',
        color: 'green',
      });
      setManualPlayback(null);
      await load();
      showVODProfileRebuildNotice(result);
    } finally {
      setSaving(false);
    }
  };

  const openBulkEditor = () => {
    setBulkMetadata(EMPTY_METADATA);
    setBulkModes(EMPTY_MODES);
    setBulkOpen(true);
  };
  const saveBulkMetadata = async () => {
    const updates = Object.fromEntries(
      Object.entries(bulkModes)
        .filter(([, mode]) => mode !== 'keep')
        .map(([field, mode]) => [
          field,
          {
            mode,
            ...(mode === 'set'
              ? {
                  value:
                    field === 'audio_languages' ||
                    field === 'subtitle_languages'
                      ? normalizeLanguageCodes(bulkMetadata[field] || [])
                      : bulkMetadata[field] || '',
                }
              : {}),
          },
        ])
    );
    if (Object.keys(updates).length === 0) return;
    setSaving(true);
    try {
      const result = await API.bulkUpdateVODPlaybackMetadata(
        selectionPayload(),
        updates
      );
      showNotification({
        title: 'Source metadata updated',
        message: `${result.updated_sources || 0} distinct sources updated from ${result.selected_sessions || 0} history entries.`,
        color: 'green',
      });
      setBulkOpen(false);
      clearSelection();
      await load();
      showVODProfileRebuildNotice(result);
    } finally {
      setSaving(false);
    }
  };

  const executeDelete = async () => {
    if (!deleteRequest) return;
    setSaving(true);
    try {
      const result = await API.deleteVODPlaybackSessions(deleteRequest.payload);
      showNotification({
        title: 'Playback history deleted',
        message: `${result.deleted_sessions || 0} entries removed.`,
        color: 'green',
      });
      setDeleteRequest(null);
      clearSelection();
      if (page > 1 && playbacks.length <= (result.deleted_sessions || 0)) {
        setPage(page - 1);
      } else {
        await load();
      }
    } finally {
      setSaving(false);
    }
  };

  const Surface = embedded ? Box : Modal;
  const surfaceProps = embedded
    ? {
        p: 'md',
        h: '100%',
        style: {
          display: 'flex',
          flexDirection: 'column',
          minHeight: 0,
          overflow: 'hidden',
        },
      }
    : {
        opened,
        onClose,
        title: 'VOD playback history',
        size: '96vw',
        styles: {
          content: { height: '96vh' },
          body: { height: 'calc(96vh - 60px)' },
        },
      };

  return (
    <>
      <Surface {...surfaceProps}>
        <Stack h="100%" gap="sm">
          {embedded && <Title order={2}>Playback History</Title>}
          <Group justify="space-between" align="flex-end" wrap="wrap">
            <Text size="sm" c="dimmed">
              Metadata edits apply once to each distinct source represented by
              the selected history entries.
            </Text>
          </Group>
          <Group align="flex-end" wrap="wrap">
            <TextInput
              label="Search"
              placeholder="Title or provider ID"
              value={filters.search}
              onChange={(event) =>
                updateFilter('search', event.currentTarget.value)
              }
              style={{ flex: '1 1 260px' }}
            />
            <Select
              clearable
              searchable
              label="User"
              placeholder="All users"
              data={facets.users || []}
              value={filters.user || null}
              onChange={(value) => updateFilter('user', value || '')}
              style={{ flex: '1 1 180px' }}
            />
            <Select
              clearable
              searchable
              label="M3U account"
              placeholder="All accounts"
              data={facets.accounts || []}
              value={filters.m3u_account || null}
              onChange={(value) => {
                setFilters((current) => ({
                  ...current,
                  m3u_account: value || '',
                  category: '',
                }));
                setPage(1);
              }}
              style={{ flex: '1 1 180px' }}
            />
            <Select
              clearable
              searchable
              label="Category"
              placeholder="All categories"
              data={categoryOptions}
              value={filters.category || null}
              onChange={(value) => updateFilter('category', value || '')}
              style={{ flex: '1 1 180px' }}
            />
            <Select
              clearable
              label="Type"
              data={[
                { value: 'movie', label: 'Movies' },
                { value: 'series', label: 'Series' },
              ]}
              value={filters.content_type || null}
              onChange={(value) => updateFilter('content_type', value || '')}
              w={130}
            />
          </Group>
          <Group justify="space-between" align="flex-end" wrap="wrap">
            <Group align="flex-end" wrap="wrap">
              <TextInput
                type="date"
                label="Started from"
                value={filters.started_after}
                onChange={(event) =>
                  updateFilter('started_after', event.currentTarget.value)
                }
              />
              <TextInput
                type="date"
                label="Started through"
                value={filters.started_before}
                onChange={(event) =>
                  updateFilter('started_before', event.currentTarget.value)
                }
              />
            </Group>
            <Group align="flex-end" wrap="wrap">
              <NumberInput
                label="Auto-delete (days)"
                description="0 disables cleanup"
                min={0}
                max={3650}
                allowDecimal={false}
                value={retentionDraft}
                onChange={(value) => setRetentionDraft(Number(value || 0))}
                onBlur={saveRetention}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') event.currentTarget.blur();
                }}
                disabled={!facets.can_manage_history || savingRetention}
                w={150}
              />
              <Button
                variant="default"
                onClick={() => {
                  setFilters(EMPTY_FILTERS);
                  setPage(1);
                }}
                disabled={!hasFilters}
              >
                Reset filters
              </Button>
              <Button
                variant="default"
                leftSection={<Wrench size={15} />}
                disabled={selectedCount === 0}
                onClick={openBulkEditor}
              >
                Edit selected ({selectedCount})
              </Button>
              <Button
                color="red"
                variant="outline"
                leftSection={<Trash2 size={15} />}
                disabled={selectedCount === 0}
                onClick={() =>
                  setDeleteRequest({
                    title: 'Delete selected playback history',
                    message: `Delete ${selectedCount} selected history entries?`,
                    payload: selectionPayload(),
                  })
                }
              >
                Delete selected
              </Button>
            </Group>
          </Group>
          <Group justify="space-between">
            <Text size="sm">
              {selectedCount} selected · {totalCount} matching
            </Text>
            <Text size="sm" c="dimmed">
              {stats.sessions || 0} plays · {stats.failover_sessions || 0}{' '}
              failovers · {formatBytes(stats.bytes_sent || 0)} sent
            </Text>
          </Group>
          <ScrollArea style={{ flex: 1, minHeight: 0 }}>
            <Table stickyHeader striped withTableBorder>
              <TableThead>
                <TableTr>
                  <TableTh w={42}>
                    <Checkbox
                      aria-label="Select all matching history"
                      checked={selectAllMatching}
                      indeterminate={selectedCount > 0 && !selectAllMatching}
                      onChange={(event) => {
                        if (event.currentTarget.checked) {
                          setSelectAllMatching(true);
                          setSelectedIds(new Set());
                          setExcludedIds(new Set());
                        } else {
                          clearSelection();
                        }
                      }}
                    />
                  </TableTh>
                  <TableTh>Started</TableTh>
                  <TableTh>Title</TableTh>
                  <TableTh>User</TableTh>
                  <TableTh>Watch time</TableTh>
                  <TableTh>Data</TableTh>
                  <TableTh w={90}>Actions</TableTh>
                </TableTr>
              </TableThead>
              <TableTbody>
                {!loading && playbacks.length === 0 && (
                  <TableTr>
                    <TableTd colSpan={7}>
                      <Text c="dimmed" ta="center" py="lg">
                        No VOD playback matches the current filters.
                      </Text>
                    </TableTd>
                  </TableTr>
                )}
                {playbacks.map((playback, index) => {
                  const showDay =
                    index === 0 ||
                    playbackDayKey(playbacks[index - 1].started_at) !==
                      playbackDayKey(playback.started_at);
                  return (
                    <React.Fragment key={playback.id}>
                      {showDay && (
                        <TableTr>
                          <TableTd
                            colSpan={7}
                            py={5}
                            style={{
                              background: 'var(--mantine-color-dark-6)',
                              borderBottom:
                                '1px solid var(--mantine-color-dark-4)',
                            }}
                          >
                            <Text size="xs" fw={700} c="dimmed">
                              {playbackDayLabel(playback.started_at)}
                            </Text>
                          </TableTd>
                        </TableTr>
                      )}
                      <TableTr>
                        <TableTd>
                          <Checkbox
                            aria-label={`Select ${playback.content_name}`}
                            checked={isSelected(playback.id)}
                            onChange={(event) =>
                              toggleRow(
                                playback.id,
                                event.currentTarget.checked
                              )
                            }
                          />
                        </TableTd>
                        <TableTd>
                          {new Date(playback.started_at).toLocaleString()}
                        </TableTd>
                        <TableTd>
                          <Text size="sm">{playback.content_name}</Text>
                          <Text size="xs" c="dimmed">
                            {[playback.account_name, playback.category_name]
                              .filter(Boolean)
                              .join(' — ') || 'Source unknown'}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {metadataSummary(playback) ||
                              'Technical metadata unknown'}
                          </Text>
                        </TableTd>
                        <TableTd>{playback.username || '—'}</TableTd>
                        <TableTd>
                          {formatDuration(playback.watched_seconds)}
                        </TableTd>
                        <TableTd>{formatBytes(playback.bytes_sent)}</TableTd>
                        <TableTd>
                          <Group gap={4} wrap="nowrap">
                            <ActionIcon
                              aria-label={`Open details for ${playback.content_name}`}
                              variant="subtle"
                              disabled={!playback.detail_canonical_id}
                              onClick={() => {
                                onClose();
                                onOpenContent?.({
                                  id: playback.detail_canonical_id,
                                  content_type: playback.detail_content_type,
                                  contentType: playback.detail_content_type,
                                  relation_id: playback.detail_relation_id,
                                  name: playback.content_name,
                                });
                              }}
                            >
                              <Eye size={16} />
                            </ActionIcon>
                            <ActionIcon
                              aria-label="Edit source metadata"
                              variant="subtle"
                              disabled={!playback.relation_id}
                              onClick={() => openManualEditor(playback)}
                            >
                              <Wrench size={16} />
                            </ActionIcon>
                            <ActionIcon
                              aria-label={`Delete ${playback.content_name}`}
                              color="red"
                              variant="subtle"
                              onClick={() =>
                                setDeleteRequest({
                                  title: 'Delete playback history entry',
                                  message: `Delete the history entry for ${playback.content_name}?`,
                                  payload: selectionPayload([playback.id]),
                                })
                              }
                            >
                              <Trash2 size={16} />
                            </ActionIcon>
                          </Group>
                        </TableTd>
                      </TableTr>
                    </React.Fragment>
                  );
                })}
              </TableTbody>
            </Table>
          </ScrollArea>
          <ListPagination
            page={page}
            pageSize={pageSize}
            total={totalCount}
            onPageChange={setPage}
            onPageSizeChange={(value) => {
              setPageSize(value);
              setPage(1);
            }}
          />
        </Stack>
      </Surface>

      <Modal
        opened={Boolean(manualPlayback)}
        onClose={() => setManualPlayback(null)}
        title="Manual source metadata"
      >
        <Stack>
          <Text size="sm" c="dimmed">
            Current effective values are prefilled. Saving confirms and locks
            every displayed value so later playback observations cannot
            overwrite it.
          </Text>
          <VODMetadataFields
            value={manualMetadata}
            onChange={setManualMetadata}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setManualPlayback(null)}>
              Cancel
            </Button>
            <Button loading={saving} onClick={saveManualMetadata}>
              Save and lock
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={bulkOpen}
        onClose={() => setBulkOpen(false)}
        title="Edit source metadata"
      >
        <Stack>
          <Text size="sm" c="dimmed">
            The update applies once to every distinct source represented by the
            {` ${selectedCount} selected history entries.`}
          </Text>
          <VODMetadataFields
            value={bulkMetadata}
            onChange={setBulkMetadata}
            modes={bulkModes}
            onModesChange={setBulkModes}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setBulkOpen(false)}>
              Cancel
            </Button>
            <Button
              loading={saving}
              disabled={
                !Object.values(bulkModes).some((mode) => mode !== 'keep')
              }
              onClick={saveBulkMetadata}
            >
              Apply metadata
            </Button>
          </Group>
        </Stack>
      </Modal>

      <ConfirmationDialog
        opened={Boolean(deleteRequest)}
        onClose={() => setDeleteRequest(null)}
        onConfirm={executeDelete}
        loading={saving}
        title={deleteRequest?.title}
        message={deleteRequest?.message}
        confirmLabel="Delete"
      />
    </>
  );
};

export default VODSourceManagerModal;
