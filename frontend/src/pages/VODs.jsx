import React, { Suspense, useEffect, useMemo, useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import {
  ActionIcon,
  Alert,
  Box,
  Button,
  Checkbox,
  Flex,
  Group,
  Image,
  Loader,
  LoadingOverlay,
  Modal,
  Pagination,
  Popover,
  PopoverDropdown,
  PopoverTarget,
  SegmentedControl,
  Select,
  SimpleGrid,
  ScrollArea,
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
  Tooltip,
} from '@mantine/core';
import {
  Eye,
  Filter,
  LayoutGrid,
  List,
  LockKeyhole,
  Play,
  Search,
  Wrench,
} from 'lucide-react';
import { useDebouncedValue, useDisclosure } from '@mantine/hooks';
import API from '../api';
import useVODStore from '../store/useVODStore';
import useAuthStore from '../store/auth';
import usePlaylistsStore from '../store/playlists';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
import { showNotification } from '../utils/notificationUtils';
import {
  filterCategoriesToEnabled,
  getCategoryOptions,
} from '../utils/pages/VODsUtils.js';
import { normalizeLanguageCodes } from '../utils/languageCodes.js';
import VODMetadataFields from '../components/VODMetadataFields.jsx';
import VODProfileRebuildNotice from '../components/VODProfileRebuildNotice.jsx';
import { useWebSocket } from '../WebSocket.jsx';
import VODMetadataModal from '../components/VODMetadataModal.jsx';
import { showVODProfileRebuildNotice } from '../utils/vodProfileUpdates.js';
import VODTechnicalFilterFields from '../components/VODTechnicalFilterFields.jsx';
import { videoFeatureLabel } from '../utils/vodMetadataOptions.js';
import {
  canViewVod,
  isVodMoviesEnabled,
  isVodSeriesEnabled,
} from '../utils/vodAccess';

const SeriesModal = React.lazy(() => import('../components/SeriesModal'));
const VODModal = React.lazy(() => import('../components/VODModal'));
const itemKey = (item) => `${item.contentType}:${item.relation_id || item.id}`;
const logoUrl = (item) =>
  item.artwork_url ||
  item.logo?.cache_url ||
  item.logo?.url ||
  item.logo_url ||
  null;
const sourceMetadataValue = (item, field) => {
  const values = item.source_metadata?.[field] || [];
  return Array.isArray(values) && values.length ? values.join(', ') : '—';
};
const sourceCount = (item) =>
  item.source_count ?? item.source_metadata?.source_count ?? 0;
const EMPTY_TECHNICAL_FILTERS = {
  audio_language: '',
  subtitle_language: '',
  resolution: '',
  container_extension: '',
  video_feature: '',
};
const ClampedCellText = ({ value }) => {
  const text =
    value === null || value === undefined || value === '' ? '—' : String(value);
  return (
    <Tooltip label={text} multiline maw={420} withArrow>
      <Text size="sm" lineClamp={3} style={{ overflowWrap: 'anywhere' }}>
        {text}
      </Text>
    </Tooltip>
  );
};

const VODsPage = () => {
  const navigate = useNavigate();
  const user = useAuthStore((state) => state.user);
  const moviesEnabled = isVodMoviesEnabled(user);
  const seriesEnabled = isVodSeriesEnabled(user);
  const vodAllowed = canViewVod(user);
  const currentPageContent = useVODStore((s) => s.currentPageContent);
  const allCategories = useVODStore((s) => s.categories);
  const filters = useVODStore((s) => s.filters);
  const currentPage = useVODStore((s) => s.currentPage);
  const totalCount = useVODStore((s) => s.totalCount);
  const pageSize = useVODStore((s) => s.pageSize);
  const setFilters = useVODStore((s) => s.setFilters);
  const setPage = useVODStore((s) => s.setPage);
  const setPageSize = useVODStore((s) => s.setPageSize);
  const fetchContent = useVODStore((s) => s.fetchContent);
  const fetchCategories = useVODStore((s) => s.fetchCategories);
  const playlists = usePlaylistsStore((state) => state.playlists);
  const fetchPlaylists = usePlaylistsStore((state) => state.fetchPlaylists);
  const [, , websocketEvent] = useWebSocket();

  const [selectedSeries, setSelectedSeries] = useState(null);
  const [selectedVOD, setSelectedVOD] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [selectAllMatching, setSelectAllMatching] = useState(false);
  const [bulkMetadata, setBulkMetadata] = useState({
    audio_languages: [],
    subtitle_languages: [],
    resolution: '',
    video_features: [],
  });
  const [bulkSaving, setBulkSaving] = useState(false);
  const [bulkTmdbId, setBulkTmdbId] = useState('');
  const [bulkConfirmation, setBulkConfirmation] = useState(null);
  const [initialLoad, setInitialLoad] = useState(true);
  const [viewMode, setViewMode] = useState(() =>
    localStorage.getItem('vodsViewMode') === 'posters' ? 'posters' : 'list'
  );
  const [searchInput, setSearchInput] = useState(filters.search || '');
  const [debouncedSearch] = useDebouncedValue(searchInput, 350);
  const [categories, setCategories] = useState({});
  const [seriesModalOpened, seriesModalHandlers] = useDisclosure(false);
  const [vodModalOpened, vodModalHandlers] = useDisclosure(false);
  const [metadataOpened, metadataHandlers] = useDisclosure(false);
  const [metadataStatus, setMetadataStatus] = useState(null);
  const [metadataStatusLoading, setMetadataStatusLoading] = useState(false);
  const [bulkEditorOpened, bulkEditorHandlers] = useDisclosure(false);

  const items = useMemo(
    () =>
      (currentPageContent || []).map((item) => ({
        ...item,
        contentType: item.contentType || item.content_type,
      })),
    [currentPageContent]
  );
  const visibleKeys = items.map(itemKey);
  const allVisibleSelected =
    visibleKeys.length > 0 &&
    visibleKeys.every((key) =>
      selectAllMatching ? !selected.has(key) : selected.has(key)
    );
  const selectedCount = selectAllMatching
    ? Math.max(0, totalCount - selected.size)
    : selected.size;
  const canonicalSelectionContext = useMemo(() => {
    if (filters.representation !== 'canonical' || !selectedCount) return null;
    const rows = [...selected].map((key) => {
      const [content_type, id] = key.split(':');
      return { content_type, id: Number(id) };
    });
    return {
      count: selectedCount,
      selections: selectAllMatching ? [] : rows,
      select_all: selectAllMatching,
      exclude_selections: selectAllMatching ? rows : [],
      filters: {
        ...filters,
      },
    };
  }, [filters, selectAllMatching, selected, selectedCount]);

  // Hydrate page size from localStorage before the first content fetch so a
  // stored size that differs from the store default does not cause a refetch.
  const [pageSizeReady, setPageSizeReady] = useState(false);
  useEffect(() => {
    const stored = localStorage.getItem('vodsPageSize');
    if (stored && !isNaN(Number(stored)) && Number(stored) !== pageSize) {
      setPageSize(Number(stored));
    }
    setPageSizeReady(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only hydrate
  }, []);

  const typeOptions = useMemo(() => {
    const options = [];
    if (moviesEnabled && seriesEnabled) {
      options.push({ label: 'All', value: 'all' });
    }
    if (moviesEnabled) {
      options.push({ label: 'Movies', value: 'movies' });
    }
    if (seriesEnabled) {
      options.push({ label: 'Series', value: 'series' });
    }
    return options;
  }, [moviesEnabled, seriesEnabled]);

  // When only one content type is allowed, lock the store filter to it.
  // Fetch waits until the lock matches so we do not load the unified
  // "all" catalog first and then immediately refetch.
  const requiredType =
    moviesEnabled && !seriesEnabled
      ? 'movies'
      : seriesEnabled && !moviesEnabled
        ? 'series'
        : null;

  useEffect(() => {
    if (!vodAllowed || !requiredType || filters.type === requiredType) return;
    setFilters({ type: requiredType, category: '' });
  }, [vodAllowed, requiredType, filters.type, setFilters]);
  useEffect(() => {
    setCategories(filterCategoriesToEnabled(allCategories));
  }, [allCategories]);

  useEffect(() => {
    if (!vodAllowed) return;
    fetchCategories();
  }, [vodAllowed, fetchCategories]);

  useEffect(() => {
    if (!playlists.length) fetchPlaylists();
  }, [fetchPlaylists, playlists.length]);

  // Keep fast typing local. Updating the shared filters for every character
  // used to launch overlapping full-catalog PostgreSQL searches ("b", "bl",
  // "bli", ...), only for all but the last result to be discarded by the UI.
  useEffect(() => {
    if (debouncedSearch !== filters.search) {
      setFilters({ search: debouncedSearch });
    }
  }, [debouncedSearch, filters.search, setFilters]);

  useEffect(() => {
    if (!vodAllowed || !pageSizeReady) return;
    if (requiredType && filters.type !== requiredType) return;
    fetchContent().finally(() => setInitialLoad(false));
  }, [
    vodAllowed,
    pageSizeReady,
    requiredType,
    filters,
    currentPage,
    pageSize,
    fetchContent,
  ]);

  useEffect(() => {
    if (websocketEvent?.type !== 'vod_library_updated') return;
    fetchContent();
  }, [fetchContent, websocketEvent]);

  useEffect(() => {
    // A global selection always tracks the current filtered result set.
    // Explicit selections are cleared because their previous rows may no
    // longer be part of the visible filter universe.
    setSelected(new Set());
  }, [
    filters.type,
    filters.search,
    filters.category,
    filters.m3u_account,
    filters.audio_language,
    filters.subtitle_language,
    filters.resolution,
    filters.container_extension,
    filters.video_feature,
    filters.metadata_status,
    filters.genre,
    filters.anime_mode,
    filters.adult_mode,
    filters.library_added_after,
    filters.representation,
  ]);

  const toggleItem = (key, checked) => {
    setSelected((current) => {
      const next = new Set(current);
      if (selectAllMatching) {
        if (checked) next.delete(key);
        else next.add(key);
      } else if (checked) next.add(key);
      else next.delete(key);
      return next;
    });
  };

  const toggleAllMatching = (checked) => {
    setSelectAllMatching(checked);
    setSelected(new Set());
  };

  const openMetadata = async () => {
    if (!metadataStatus) {
      setMetadataStatusLoading(true);
      try {
        const status = await API.getVODMetadataStatus(true);
        setMetadataStatus(status);
      } catch (error) {
        showNotification({
          title: 'TMDB settings could not be loaded',
          message: error?.message || 'Please retry.',
          color: 'red',
        });
        return;
      } finally {
        setMetadataStatusLoading(false);
      }
    }
    metadataHandlers.open();
  };

  const openItem = (item) => {
    if (item.contentType === 'series') {
      setSelectedSeries(item);
      seriesModalHandlers.open();
    } else {
      setSelectedVOD(item);
      vodModalHandlers.open();
    }
  };

  const saveBulkMetadata = async ({ confirmed = false } = {}) => {
    const selections = [...selected].map((key) => {
      const [content_type, relation_id] = key.split(':');
      return { content_type, relation_id: Number(relation_id) };
    });
    const metadata = Object.fromEntries(
      Object.entries(bulkMetadata).filter(
        ([, value]) =>
          value !== '' && (!Array.isArray(value) || value.length > 0)
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
    setBulkSaving(true);
    try {
      const selectionOptions = selectAllMatching
        ? {
            select_all: true,
            filters,
            exclude_selections: selections,
          }
        : { filters };
      let movedSources = 0;
      let movedResponse = null;
      if (bulkTmdbId.trim()) {
        try {
          const moved = await API.updateVODRelationTmdbMatch(
            bulkTmdbId.trim(),
            selectAllMatching ? [] : selections,
            { ...selectionOptions, confirmed }
          );
          movedResponse = moved;
          movedSources = moved.moved_sources || 0;
        } catch (error) {
          if (error?.status === 409 && error?.body?.requires_confirmation) {
            setBulkConfirmation(error.body);
            return;
          }
          throw error;
        }
      }
      const result = Object.keys(metadata).length
        ? await API.bulkUpdateVODSourceMetadata(
            selectAllMatching ? [] : selections,
            metadata,
            selectionOptions
          )
        : { updated_sources: 0 };
      const profilesAffected = Math.max(
        Number(movedResponse?.profiles_affected || 0),
        Number(result?.profiles_affected || 0)
      );
      showVODProfileRebuildNotice({
        profile_update: profilesAffected ? 'outdated' : 'not_required',
        profiles_affected: profilesAffected,
      });
      showNotification({
        title: 'Source metadata updated',
        message: `${result.updated_sources || 0} source editions updated${movedSources ? `; ${movedSources} moved to the selected TMDB title` : ''}.`,
        color: 'green',
      });
      setBulkConfirmation(null);
      bulkEditorHandlers.close();
      setSelected(new Set());
      setSelectAllMatching(false);
      await fetchContent();
    } catch (error) {
      showNotification({
        title: 'Provider sources were not updated',
        message: error?.body?.tmdb_id || error?.message || 'Please retry.',
        color: 'red',
      });
    } finally {
      setBulkSaving(false);
    }
  };

  const categoryOptions = getCategoryOptions(categories, filters);
  const m3uOptions = playlists
    .filter(
      (playlist) =>
        playlist.account_type === 'XC' &&
        playlist.is_active &&
        playlist.enable_vod
    )
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((playlist) => ({ value: String(playlist.id), label: playlist.name }));
  const totalPages = Math.ceil(totalCount / pageSize);
  const showTypeControl = typeOptions.length > 1;
  const advancedFilterCount = [
    filters.audio_language,
    filters.subtitle_language,
    filters.resolution,
    filters.container_extension,
    filters.video_feature,
    filters.metadata_status,
    filters.genre,
    filters.anime_mode,
    filters.adult_mode,
    filters.library_added_after,
  ].filter(Boolean).length;

  const clearAdvancedFilters = () => {
    setFilters({
      audio_language: '',
      subtitle_language: '',
      resolution: '',
      container_extension: '',
      video_feature: '',
      metadata_status: '',
      genre: '',
      anime_mode: '',
      adult_mode: '',
      library_added_after: '',
    });
    setPage(1);
  };

  if (!vodAllowed) {
    return <Navigate to="/channels" replace />;
  }
  return (
    <Box
      p="md"
      id="vods-container"
      h="100%"
      style={{
        display: 'flex',
        minHeight: 0,
        minWidth: 0,
        width: '100%',
        overflow: 'hidden',
      }}
    >
      <Stack
        gap="md"
        h="100%"
        style={{ flex: 1, minHeight: 0, minWidth: 0, width: '100%' }}
      >
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Group gap="md" wrap="wrap">
            <Title order={2}>VOD Library</Title>
            <Text c="dimmed">
              {viewMode === 'list' ? `${selectedCount} selected · ` : ''}
              {totalCount} matching
            </Text>
          </Group>
          <Group wrap="wrap" justify="flex-end">
            <SegmentedControl
              aria-label="VOD representation"
              value={filters.representation}
              onChange={(representation) => {
                setFilters({ representation });
                setSelectAllMatching(false);
                setPage(1);
              }}
              data={[
                { value: 'canonical', label: 'Canonical' },
                { value: 'variants', label: 'Variants' },
              ]}
            />
            <SegmentedControl
              aria-label="VOD view"
              value={viewMode}
              onChange={(value) => {
                setViewMode(value);
                setSelected(new Set());
                setSelectAllMatching(false);
                localStorage.setItem('vodsViewMode', value);
              }}
              data={[
                {
                  value: 'list',
                  label: <List aria-label="List view" size={16} />,
                },
                {
                  value: 'posters',
                  label: <LayoutGrid aria-label="Poster wall" size={16} />,
                },
              ]}
            />
            {user?.user_level >= 10 && (
              <>
                {filters.representation === 'canonical' &&
                  viewMode === 'list' && (
                    <Button
                      variant="default"
                      leftSection={<Wrench size={16} />}
                      disabled={selectedCount === 0}
                      loading={metadataStatusLoading}
                      onClick={openMetadata}
                    >
                      Edit selected ({selectedCount})
                    </Button>
                  )}
                {filters.representation === 'variants' &&
                  viewMode === 'list' && (
                    <Button
                      variant="default"
                      leftSection={<Wrench size={16} />}
                      disabled={selectedCount === 0}
                      onClick={bulkEditorHandlers.open}
                    >
                      Edit selected ({selectedCount})
                    </Button>
                  )}
              </>
            )}
          </Group>
        </Group>

        <Group gap="md" align="end" wrap="wrap">
          {showTypeControl && (
            <SegmentedControl
              value={filters.type}
              onChange={(value) => {
                setFilters({
                  type: value,
                  category: '',
                  ...EMPTY_TECHNICAL_FILTERS,
                });
                setPage(1);
              }}
              data={typeOptions}
            />
          )}
          <TextInput
            placeholder="Search VODs..."
            leftSection={<Search size={16} />}
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            miw={240}
          />
          <Select
            placeholder="M3U account"
            data={m3uOptions}
            value={filters.m3u_account || null}
            onChange={(value) => {
              setFilters({
                m3u_account: value || '',
                category: '',
                ...EMPTY_TECHNICAL_FILTERS,
              });
              setPage(1);
            }}
            searchable
            clearable
            miw={180}
          />
          <Select
            placeholder="Category"
            data={categoryOptions}
            value={filters.category}
            onChange={(value) => {
              setFilters({
                category: value || '',
                ...EMPTY_TECHNICAL_FILTERS,
              });
              setPage(1);
            }}
            clearable
            miw={180}
          />
          <Popover
            width={470}
            position="bottom-end"
            shadow="md"
            withArrow
            withinPortal
          >
            <PopoverTarget>
              <Button
                variant={advancedFilterCount ? 'light' : 'default'}
                aria-label="Additional VOD filters"
                leftSection={<Filter size={17} />}
              >
                Filters{advancedFilterCount ? ` (${advancedFilterCount})` : ''}
              </Button>
            </PopoverTarget>
            <PopoverDropdown>
              <Stack gap="sm">
                <SimpleGrid cols={2}>
                  <VODTechnicalFilterFields
                    filters={filters}
                    type={filters.type}
                    m3uAccount={filters.m3u_account}
                    category={filters.category}
                    onChange={(field, value) => {
                      setFilters({ [field]: value });
                      setPage(1);
                    }}
                  />
                  <Select
                    label="Metadata"
                    placeholder="Any"
                    data={[
                      { value: 'missing_tmdb', label: 'No TMDB ID' },
                      {
                        value: 'missing_external_ids',
                        label: 'No external ID',
                      },
                      {
                        value: 'missing_metadata',
                        label: 'TMDB details not enriched',
                      },
                    ]}
                    value={filters.metadata_status || null}
                    onChange={(value) => {
                      setFilters({ metadata_status: value || '' });
                      setPage(1);
                    }}
                    clearable
                  />
                  <TextInput
                    label="Genre contains"
                    placeholder="e.g. Horror"
                    value={filters.genre || ''}
                    onChange={(event) => {
                      setFilters({ genre: event.currentTarget.value });
                      setPage(1);
                    }}
                  />
                  <Select
                    label="Anime"
                    placeholder="Any"
                    clearable
                    data={[
                      { value: 'yes', label: 'Yes' },
                      { value: 'no', label: 'No' },
                    ]}
                    value={filters.anime_mode || null}
                    onChange={(value) => {
                      setFilters({ anime_mode: value || '' });
                      setPage(1);
                    }}
                  />
                  <Select
                    label="Adult content"
                    placeholder="Any"
                    clearable
                    data={[
                      { value: 'yes', label: 'Yes' },
                      { value: 'no', label: 'No' },
                    ]}
                    value={filters.adult_mode || null}
                    onChange={(value) => {
                      setFilters({ adult_mode: value || '' });
                      setPage(1);
                    }}
                  />
                  <TextInput
                    type="date"
                    label="Added since"
                    value={filters.library_added_after || ''}
                    onChange={(event) => {
                      setFilters({
                        library_added_after: event.currentTarget.value,
                      });
                      setPage(1);
                    }}
                  />
                </SimpleGrid>
                <Group justify="flex-end">
                  <Button
                    size="xs"
                    variant="subtle"
                    disabled={!advancedFilterCount}
                    onClick={clearAdvancedFilters}
                  >
                    Clear filters
                  </Button>
                </Group>
              </Stack>
            </PopoverDropdown>
          </Popover>
        </Group>

        <ScrollArea
          data-testid="vod-list-scroll"
          type="always"
          scrollbars="xy"
          offsetScrollbars
          style={{ flex: 1, minHeight: 0, minWidth: 0, width: '100%' }}
        >
          {initialLoad ? (
            <Flex justify="center" py="xl">
              <Loader size="lg" />
            </Flex>
          ) : viewMode === 'list' ? (
            <Table
              striped
              highlightOnHover
              withTableBorder
              stickyHeader
              miw={1400}
            >
              <TableThead>
                <TableTr>
                  {user?.user_level >= 10 && (
                    <TableTh w={44}>
                      <Checkbox
                        aria-label="Select all filtered VODs"
                        checked={allVisibleSelected}
                        indeterminate={
                          (selectAllMatching && selected.size > 0) ||
                          (!selectAllMatching &&
                            selected.size > 0 &&
                            !allVisibleSelected)
                        }
                        onChange={(event) =>
                          toggleAllMatching(event.currentTarget.checked)
                        }
                      />
                    </TableTh>
                  )}
                  <TableTh w={62}>Artwork</TableTh>
                  <TableTh>Title</TableTh>
                  <TableTh w={100}>Type</TableTh>
                  <TableTh w={90}>Year</TableTh>
                  <TableTh w={180}>
                    {filters.representation === 'variants'
                      ? 'Source'
                      : 'Sources'}
                  </TableTh>
                  <TableTh>Genre</TableTh>
                  <TableTh w={125}>DUB</TableTh>
                  <TableTh w={125}>SUB</TableTh>
                  <TableTh w={130}>Resolution</TableTh>
                  <TableTh w={100}>Format</TableTh>
                  <TableTh w={160}>Features</TableTh>
                  <TableTh w={60}>Details</TableTh>
                </TableTr>
              </TableThead>
              <TableTbody>
                {items.map((item) => (
                  <TableTr key={itemKey(item)}>
                    {user?.user_level >= 10 && (
                      <TableTd>
                        <Checkbox
                          aria-label={`Select ${item.name}`}
                          checked={
                            selectAllMatching
                              ? !selected.has(itemKey(item))
                              : selected.has(itemKey(item))
                          }
                          onChange={(event) =>
                            toggleItem(
                              itemKey(item),
                              event.currentTarget.checked
                            )
                          }
                        />
                      </TableTd>
                    )}
                    <TableTd>
                      {logoUrl(item) ? (
                        <Image
                          src={logoUrl(item)}
                          loading="lazy"
                          h={54}
                          w={40}
                          fit="contain"
                        />
                      ) : (
                        <Box h={54} w={40} bg="dark.6" />
                      )}
                    </TableTd>
                    <TableTd>
                      <Text fw={500}>{item.name}</Text>
                      {item.clean_title &&
                        (item.is_variant ||
                          (item.tmdb_status !== 'matched' &&
                            item.clean_title !== item.name)) && (
                          <Text size="xs" c="dimmed" lineClamp={1}>
                            Clean: {item.clean_title}
                          </Text>
                        )}
                      <Text
                        size="xs"
                        c={
                          ['not_found', 'ambiguous'].includes(item.tmdb_status)
                            ? 'orange.5'
                            : 'dimmed'
                        }
                      >
                        {item.tmdb_status === 'ambiguous'
                          ? 'Multiple TMDB matches'
                          : item.tmdb_status === 'not_found'
                            ? 'No TMDB match found'
                            : item.tmdb_id
                              ? `TMDB ${item.tmdb_id}`
                              : 'No TMDB ID'}
                      </Text>
                    </TableTd>
                    <TableTd>
                      {item.contentType === 'series' ? 'Series' : 'Movie'}
                    </TableTd>
                    <TableTd>{item.year || '—'}</TableTd>
                    <TableTd>
                      {item.is_variant ? (
                        <Stack gap={1}>
                          <ClampedCellText
                            value={item.m3u_account?.name || 'Unknown'}
                          />
                          <Text size="xs" c="dimmed" lineClamp={2}>
                            {item.category?.name || 'Uncategorized'}
                          </Text>
                        </Stack>
                      ) : (
                        <ClampedCellText value={sourceCount(item)} />
                      )}
                    </TableTd>
                    <TableTd>
                      <ClampedCellText value={item.genre} />
                    </TableTd>
                    <TableTd>
                      <ClampedCellText
                        value={sourceMetadataValue(item, 'audio_languages')}
                      />
                    </TableTd>
                    <TableTd>
                      <ClampedCellText
                        value={sourceMetadataValue(item, 'subtitle_languages')}
                      />
                    </TableTd>
                    <TableTd>
                      <ClampedCellText
                        value={sourceMetadataValue(item, 'resolutions')}
                      />
                    </TableTd>
                    <TableTd>
                      <ClampedCellText
                        value={
                          item.contentType === 'series'
                            ? '—'
                            : sourceMetadataValue(item, 'container_extensions')
                        }
                      />
                    </TableTd>
                    <TableTd>
                      <ClampedCellText
                        value={
                          (item.source_metadata?.video_features || []).length
                            ? item.source_metadata.video_features
                                .map(videoFeatureLabel)
                                .join(', ')
                            : '—'
                        }
                      />
                    </TableTd>
                    <TableTd>
                      <Group gap={2} wrap="nowrap" justify="center">
                        {item.metadata_auto_locked && (
                          <Tooltip
                            label="Automatic cleanup and TMDB matching are locked until this title is explicitly unlocked."
                            withArrow
                            multiline
                            maw={320}
                          >
                            <LockKeyhole
                              size={15}
                              aria-label="Automatic metadata matching locked"
                              color="var(--mantine-color-dimmed)"
                            />
                          </Tooltip>
                        )}
                        <ActionIcon
                          aria-label={`Details ${item.name}`}
                          variant="subtle"
                          onClick={() => openItem(item)}
                        >
                          <Eye size={16} />
                        </ActionIcon>
                      </Group>
                    </TableTd>
                  </TableTr>
                ))}
              </TableTbody>
            </Table>
          ) : (
            <Box
              p="xs"
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
                gap: 'var(--mantine-spacing-md)',
              }}
            >
              {items.map((item) => (
                <Box
                  key={itemKey(item)}
                  role="button"
                  tabIndex={0}
                  aria-label={`Details ${item.name}`}
                  onClick={() => openItem(item)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') {
                      event.preventDefault();
                      openItem(item);
                    }
                  }}
                  style={{
                    position: 'relative',
                    padding: 0,
                    border: '1px solid var(--mantine-color-dark-4)',
                    borderRadius: 'var(--mantine-radius-md)',
                    overflow: 'hidden',
                    background: 'var(--mantine-color-dark-7)',
                    color: 'inherit',
                    textAlign: 'left',
                    cursor: 'pointer',
                  }}
                >
                  {logoUrl(item) ? (
                    <Image
                      src={logoUrl(item)}
                      alt=""
                      loading="lazy"
                      w="100%"
                      style={{ aspectRatio: '2 / 3' }}
                      fit="cover"
                    />
                  ) : (
                    <Flex
                      align="center"
                      justify="center"
                      bg="dark.6"
                      style={{ aspectRatio: '2 / 3' }}
                    >
                      <Play size={36} color="var(--mantine-color-dimmed)" />
                    </Flex>
                  )}
                  <Stack gap={2} p="xs" pr="sm">
                    <Text
                      fw={600}
                      size="sm"
                      lineClamp={2}
                      title={item.name}
                      pr={2}
                      style={{
                        overflowWrap: 'anywhere',
                        wordBreak: 'break-word',
                        flex: 1,
                      }}
                    >
                      {item.name}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {item.contentType === 'series' ? 'Series' : 'Movie'}
                      {item.year ? ` · ${item.year}` : ''}
                    </Text>
                    <Text size="xs" c="dimmed" lineClamp={2}>
                      {item.is_variant
                        ? item.m3u_account?.name || 'Unknown source'
                        : `${sourceCount(item)} sources`}
                    </Text>
                    {item.clean_title &&
                      (item.is_variant ||
                        (item.tmdb_status !== 'matched' &&
                          item.clean_title !== item.name)) && (
                        <Text size="xs" c="dimmed" lineClamp={1}>
                          Clean: {item.clean_title}
                        </Text>
                      )}
                  </Stack>
                </Box>
              ))}
            </Box>
          )}
        </ScrollArea>

        <Group gap={5} justify="center" wrap="wrap">
          <Text size="xs">Rows</Text>
          <Select
            aria-label="Rows"
            size="xs"
            value={String(pageSize)}
            onChange={(value) => {
              setPageSize(Number(value));
              setPage(1);
              localStorage.setItem('vodsPageSize', value);
            }}
            data={['24', '48', '96'].map((value) => ({
              value,
              label: value,
            }))}
            allowDeselect={false}
            w={70}
          />
          {totalCount > 0 && (
            <Pagination
              value={currentPage}
              onChange={setPage}
              total={Math.max(1, totalPages)}
              size="xs"
              withEdges
            />
          )}
          <Text size="xs" c="dimmed">
            {totalCount
              ? `${(currentPage - 1) * pageSize + 1}–${Math.min(
                  currentPage * pageSize,
                  totalCount
                )} of ${totalCount}`
              : '0 of 0'}
          </Text>
        </Group>
        {selectAllMatching && selectedCount > 0 && (
          <Text size="sm" c="blue" ta="center">
            All {selectedCount} VODs matching the current filters are selected.
          </Text>
        )}
      </Stack>

      <Modal
        opened={bulkEditorOpened}
        onClose={bulkEditorHandlers.close}
        title={`Edit metadata for ${selectedCount} selected VODs`}
      >
        <Stack>
          <Text size="sm" c="dimmed">
            Values are applied only to the selected provider sources. For a
            selected series source, its episode sources are kept together.
            Manual values are locked against later playback observations.
          </Text>
          <VODMetadataFields
            value={bulkMetadata}
            onChange={setBulkMetadata}
            descriptions={{
              resolution: 'Leave empty to keep existing values',
            }}
          />
          {filters.representation !== 'variants' && (
            <TextInput
              label="Move selected sources to TMDB ID"
              description="Leave empty to keep the current canonical assignment. The target is fetched once and shared by all selected sources."
              value={bulkTmdbId}
              onChange={(event) => setBulkTmdbId(event.currentTarget.value)}
              inputMode="numeric"
            />
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={bulkEditorHandlers.close}>
              Cancel
            </Button>
            <Button
              loading={bulkSaving}
              disabled={
                !bulkTmdbId.trim() &&
                !Object.values(bulkMetadata).some((value) =>
                  Array.isArray(value) ? value.length : Boolean(value)
                )
              }
              onClick={() => saveBulkMetadata()}
            >
              Apply and lock
            </Button>
          </Group>
        </Stack>
        <Modal
          opened={Boolean(bulkConfirmation)}
          onClose={() => setBulkConfirmation(null)}
          title="Replace existing TMDB assignments?"
          centered
        >
          <Stack>
            <Alert color="orange">
              TMDB metadata was already fetched for{' '}
              {bulkConfirmation?.previously_enriched_sources || 0} of the
              selected sources. Continuing moves every selected source to TMDB{' '}
              {bulkTmdbId.trim()}.
            </Alert>
            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={() => setBulkConfirmation(null)}
              >
                Cancel
              </Button>
              <Button
                color="orange"
                loading={bulkSaving}
                onClick={() => saveBulkMetadata({ confirmed: true })}
              >
                Move all selected sources
              </Button>
            </Group>
          </Stack>
        </Modal>
      </Modal>

      <ErrorBoundary inline>
        <Suspense fallback={<LoadingOverlay />}>
          <SeriesModal
            series={selectedSeries}
            opened={seriesModalOpened}
            onClose={seriesModalHandlers.close}
            onMetadataChanged={fetchContent}
            onCanonicalMoved={setSelectedSeries}
            initialRelationId={selectedSeries?.relation_id}
            allowSourceEditing
          />
        </Suspense>
      </ErrorBoundary>
      <ErrorBoundary>
        <Suspense fallback={<LoadingOverlay />}>
          <VODMetadataModal
            opened={metadataOpened}
            onClose={metadataHandlers.close}
            initialStatus={metadataStatus}
            selectionContext={canonicalSelectionContext}
            onStatusChange={setMetadataStatus}
            onCatalogChanged={() => fetchContent()}
          />
        </Suspense>
      </ErrorBoundary>
      <ErrorBoundary inline>
        <Suspense fallback={<LoadingOverlay />}>
          <VODModal
            vod={selectedVOD}
            opened={vodModalOpened}
            onClose={vodModalHandlers.close}
            onMetadataChanged={fetchContent}
            onCanonicalMoved={setSelectedVOD}
            initialRelationId={selectedVOD?.relation_id}
            allowSourceEditing
          />
        </Suspense>
      </ErrorBoundary>
      <VODProfileRebuildNotice
        onOpenProfiles={() => navigate('/vods/profiles')}
      />
    </Box>
  );
};

export default VODsPage;
