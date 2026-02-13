import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ActionIcon, Box, Button, Divider, Group, Loader, Paper, Portal, Select, Stack, Text, TextInput, Title, SegmentedControl } from '@mantine/core';
import { notifications } from '@mantine/notifications';
import { useDebouncedValue } from '@mantine/hooks';
import { ListChecks, Play, RefreshCcw, Search, Trash2, XCircle } from 'lucide-react';

import useLibraryStore from '../store/library';
import useMediaLibraryStore from '../store/mediaLibrary';
import MediaDetailModal from '../components/library/MediaDetailModal';
import LibraryScanDrawer from '../components/library/LibraryScanDrawer';
import MediaCarousel from '../components/library/MediaCarousel';
import MediaGrid from '../components/library/MediaGrid';
import AlphabetSidebar from '../components/library/AlphabetSidebar';
import API from '../api';

const TABS = [
  { label: 'Recommended', value: 'recommended' },
  { label: 'Library', value: 'library' },
  { label: 'Categories', value: 'categories' },
];

const SORT_OPTIONS = [
  { label: 'Name (A-Z)', value: 'alpha' },
  { label: 'Release Year', value: 'year' },
  { label: 'Recently Added', value: 'recent' },
  { label: 'Genre', value: 'genre' },
];

const INITIAL_LIBRARY_LIMIT = 60;

const parseDate = (value) => {
  if (!value) return 0;
  const timestamp = Date.parse(value);
  return Number.isNaN(timestamp) ? 0 : timestamp;
};

const alphaLetterFromItem = (item) => {
  const name = item?.sort_title || item?.title || '';
  const firstChar = name.charAt(0).toUpperCase();
  return /[A-Z]/.test(firstChar) ? firstChar : '#';
};

const getOrderingForSort = (sortOption) => {
  switch (sortOption) {
    case 'alpha':
      return 'sort_title,title,id';
    case 'year':
      return '-release_year,sort_title,title,id';
    case 'recent':
      return '-first_imported_at,-updated_at,-id';
    default:
      return '-updated_at,-id';
  }
};

const LibraryPage = () => {
  const navigate = useNavigate();
  const { mediaType } = useParams();
  const normalizedMediaType =
    mediaType === 'shows' ? 'shows' : mediaType === 'movies' ? 'movies' : null;

  useEffect(() => {
    if (!normalizedMediaType) {
      navigate('/library/movies', { replace: true });
    }
  }, [normalizedMediaType, navigate]);

  const isMovies = normalizedMediaType !== 'shows';
  const itemTypeFilter = isMovies ? 'movie' : 'show';

  const handleMediaTypeChange = (value) => {
    if (!value || value === normalizedMediaType) return;
    navigate(`/library/${value}`);
  };

  const [scanDrawerOpen, setScanDrawerOpen] = useState(false);
  const [playbackModalOpen, setPlaybackModalOpen] = useState(false);
  const [activeTab, setActiveTab] = useState('recommended');
  const [sortOption, setSortOption] = useState('alpha');
  const [searchTerm, setSearchTerm] = useState('');
  const [contextMenu, setContextMenu] = useState(null);
  const contextMenuPosition = useMemo(() => {
    if (!contextMenu) return null;
    if (typeof window === 'undefined') {
      return { top: contextMenu.y, left: contextMenu.x };
    }
    return {
      top: Math.min(contextMenu.y, window.innerHeight - 220),
      left: Math.min(contextMenu.x, window.innerWidth - 260),
    };
  }, [contextMenu]);

  const [debouncedSearch] = useDebouncedValue(searchTerm, 350);
  const libraryOrdering = useMemo(
    () => getOrderingForSort(sortOption),
    [sortOption]
  );

  // Library store hooks
  const libraries = useLibraryStore((s) => s.libraries);
  const librariesLoading = useLibraryStore((s) => s.loading);
  const fetchLibraries = useLibraryStore((s) => s.fetchLibraries);
  const scansByKey = useLibraryStore((s) => s.scans);
  const fetchScans = useLibraryStore((s) => s.fetchScans);
  const triggerScan = useLibraryStore((s) => s.triggerScan);
  const upsertScan = useLibraryStore((s) => s.upsertScan);
  const removeScan = useLibraryStore((s) => s.removeScan);

  // Media store hooks
  const items = useMediaLibraryStore((s) => s.items);
  const itemsLoading = useMediaLibraryStore((s) => s.loading);
  const itemsBackgroundLoading = useMediaLibraryStore((s) => s.backgroundLoading);
  const itemsTotalCount = useMediaLibraryStore((s) => s.totalCount);
  const setItemFilters = useMediaLibraryStore((s) => s.setFilters);
  const fetchItems = useMediaLibraryStore((s) => s.fetchItems);
  const fetchItemsIncremental = useMediaLibraryStore((s) => s.fetchItemsIncremental);
  const clearItems = useMediaLibraryStore((s) => s.clearItems);
  const setSelectedMediaLibrary = useMediaLibraryStore((s) => s.setSelectedLibraryId);
  const openItem = useMediaLibraryStore((s) => s.openItem);
  const closeItem = useMediaLibraryStore((s) => s.closeItem);
  const removeItems = useMediaLibraryStore((s) => s.removeItems);
  const upsertItems = useMediaLibraryStore((s) => s.upsertItems);
  const pollItem = useMediaLibraryStore((s) => s.pollItem);

  // Fetch libraries on mount
  useEffect(() => {
    fetchLibraries();
  }, [fetchLibraries]);

  const relevantLibraryIds = useMemo(() => {
    if (!libraries || libraries.length === 0) return [];
    return libraries
      .filter((lib) =>
        isMovies
          ? lib.library_type === 'movies'
          : lib.library_type === 'shows'
      )
      .map((lib) => lib.id);
  }, [libraries, isMovies]);

  const allLibraryIds = useMemo(
    () => (Array.isArray(libraries) ? libraries.map((lib) => lib.id) : []),
    [libraries]
  );

  const hasLibraries = relevantLibraryIds.length > 0;
  const hasAnyLibraries = allLibraryIds.length > 0;
  const hasActiveScans = useMemo(() => {
    const scans = scansByKey?.all;
    if (!Array.isArray(scans) || scans.length === 0 || relevantLibraryIds.length === 0) {
      return false;
    }
    const relevantSet = new Set(relevantLibraryIds);
    return scans.some((scan) => (
      relevantSet.has(scan.library)
      && ['pending', 'queued', 'running'].includes(scan.status)
    ));
  }, [scansByKey, relevantLibraryIds]);

  useEffect(() => {
    if (!hasLibraries || scanDrawerOpen) return undefined;

    let cancelled = false;
    let timer;

    const runFetch = async (background) => {
      try {
        await fetchScans(null, { background });
      } catch (error) {
        if (!background) {
          console.error('Failed to refresh library scan state', error);
        }
      }
    };

    const loop = () => {
      if (cancelled) return;
      const delay = hasActiveScans ? 2500 : 8000;
      timer = setTimeout(async () => {
        await runFetch(true);
        loop();
      }, delay);
    };

    void runFetch(false).then(loop);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [hasLibraries, hasActiveScans, fetchScans, scanDrawerOpen]);

  useEffect(() => {
    if (scanDrawerOpen || !hasActiveScans || relevantLibraryIds.length === 0) {
      return undefined;
    }

    let cancelled = false;
    let timer;

    const refreshItemsWhileScanning = async () => {
      if (cancelled) return;
      await fetchItemsIncremental(relevantLibraryIds, {
        background: true,
        limit: Math.max(INITIAL_LIBRARY_LIMIT, 120),
        ordering: libraryOrdering,
      });
    };

    const loop = () => {
      if (cancelled) return;
      timer = setTimeout(async () => {
        await refreshItemsWhileScanning();
        loop();
      }, 4000);
    };

    void refreshItemsWhileScanning().then(loop);

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [
    hasActiveScans,
    relevantLibraryIds,
    fetchItemsIncremental,
    scanDrawerOpen,
    libraryOrdering,
  ]);

  // Sync media filters with current type and search
  useEffect(() => {
    setItemFilters({
      type: itemTypeFilter,
      search: debouncedSearch,
    });
  }, [itemTypeFilter, debouncedSearch, setItemFilters]);

  // Fetch items when library changes or filters update
  useEffect(() => {
    const ids = relevantLibraryIds;
    const libraryList = Array.isArray(libraries) ? libraries : [];

    if (libraryList.length === 0) {
      setSelectedMediaLibrary(null);
      if (!librariesLoading) {
        clearItems();
      }
      return;
    }

    if (ids.length === 0) {
      setSelectedMediaLibrary(null);
      if (!librariesLoading) {
        clearItems();
      }
      return;
    }

    setSelectedMediaLibrary(ids.length === 1 ? ids[0] : null);

    let cancelled = false;

    const loadItems = async () => {
      await fetchItems(ids, {
        background: false,
        append: false,
        all: true,
        ordering: libraryOrdering,
      });
      if (cancelled) return;
    };

    loadItems();

    return () => {
      cancelled = true;
    };
  }, [
    libraries,
    relevantLibraryIds,
    fetchItems,
    clearItems,
    setSelectedMediaLibrary,
    debouncedSearch,
    itemTypeFilter,
    librariesLoading,
    libraryOrdering,
  ]);

  const filteredItems = useMemo(() => {
    const typeFiltered = items.filter((item) => item.item_type === itemTypeFilter);
    if (!debouncedSearch) return typeFiltered;
    const query = debouncedSearch.toLowerCase();
    return typeFiltered.filter((item) =>
      (item.title || '').toLowerCase().includes(query)
    );
  }, [items, itemTypeFilter, debouncedSearch]);

  const shouldComputeRecommendedRows = activeTab === 'recommended';
  const shouldComputeGenreRows =
    activeTab === 'categories' || (activeTab === 'library' && sortOption === 'genre');

  const continueWatching = useMemo(() => {
    if (!shouldComputeRecommendedRows) return [];
    return filteredItems
      .filter((item) => {
        if (item.item_type === 'show') {
          return item.watch_summary?.status === 'in_progress';
        }
        const progress = item.watch_progress;
        return progress && !progress.completed;
      })
      .sort((a, b) => {
        const aTime = parseDate(a.watch_progress?.last_watched_at || a.updated_at);
        const bTime = parseDate(b.watch_progress?.last_watched_at || b.updated_at);
        return bTime - aTime;
      })
      .slice(0, 20);
  }, [filteredItems, shouldComputeRecommendedRows]);

  const recentlyReleased = useMemo(() => {
    if (!shouldComputeRecommendedRows) return [];
    return [...filteredItems]
      .filter((item) => item.release_year)
      .sort((a, b) => (b.release_year || 0) - (a.release_year || 0))
      .slice(0, 30);
  }, [filteredItems, shouldComputeRecommendedRows]);

  const recentlyAdded = useMemo(() => {
    if (!shouldComputeRecommendedRows) return [];
    return [...filteredItems]
      .sort((a, b) => parseDate(b.first_imported_at) - parseDate(a.first_imported_at))
      .slice(0, 30);
  }, [filteredItems, shouldComputeRecommendedRows]);

  const genresMap = useMemo(() => {
    if (!shouldComputeGenreRows) return new Map();
    const map = new Map();
    filteredItems.forEach((item) => {
      const genres = Array.isArray(item.genres) ? item.genres : [];
      if (genres.length === 0) return;
      const primary = genres[0];
      if (!map.has(primary)) {
        map.set(primary, []);
      }
      map.get(primary).push(item);
    });
    return map;
  }, [filteredItems, shouldComputeGenreRows]);

  const genreCarousels = useMemo(() => {
    if (!shouldComputeGenreRows) return [];
    const entries = Array.from(genresMap.entries());
    return entries
      .map(([genre, genreItems]) => ({
        genre,
        items: genreItems
          .slice()
          .sort((a, b) => parseDate(b.first_imported_at) - parseDate(a.first_imported_at))
          .slice(0, 25),
      }))
      .filter((entry) => entry.items.length > 0)
      .slice(0, 12);
  }, [genresMap, shouldComputeGenreRows]);

  const primaryLibraryId = useMemo(
    () => (relevantLibraryIds.length === 1 ? relevantLibraryIds[0] : null),
    [relevantLibraryIds]
  );

  const aggregatedSubtitle = useMemo(() => {
    if (!libraries || libraries.length === 0) {
      return 'No libraries configured yet.';
    }
    if (!hasLibraries) {
      return isMovies
        ? 'No movie libraries configured.'
        : 'No TV show libraries configured.';
    }
    return '';
  }, [libraries, hasLibraries, isMovies]);

  const sortedLibraryItems = useMemo(() => {
    return filteredItems;
  }, [filteredItems]);

  const availableLetters = useMemo(() => {
    if (sortOption !== 'alpha') return new Set();
    const letters = new Set();
    sortedLibraryItems.forEach((item) => {
      letters.add(alphaLetterFromItem(item));
    });
    return letters;
  }, [sortedLibraryItems, sortOption]);

  const letterRefs = useRef({});

  const handleLetterSelect = useCallback((letter) => {
    if (sortOption !== 'alpha') return;
    const node = letterRefs.current[letter];
    if (node && node.scrollIntoView) {
      node.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [sortOption]);

  const handleOpenItem = (item) => {
    setPlaybackModalOpen(true);
    openItem(item.id).catch((error) => {
      console.error('Failed to open media item', error);
      setPlaybackModalOpen(false);
      notifications.show({
        title: 'Error loading media',
        message: 'Unable to open media details.',
        color: 'red',
      });
    });
  };

  const refreshItem = async (id) => {
    try {
      const data = await API.getMediaItem(id);
      upsertItems([data]);
    } catch (error) {
      console.error('Failed to refresh media item', error);
    }
  };

  const handleMarkWatched = async (item) => {
    try {
      if (item.item_type === 'show') {
        const response = await API.markSeriesWatched(item.id);
        if (response?.item) {
          upsertItems([response.item]);
        } else {
          await refreshItem(item.id);
        }
        notifications.show({
          title: 'Series updated',
          message: 'All episodes marked as watched.',
          color: 'green',
        });
      } else {
        await API.markMediaItemWatched(item.id);
        await refreshItem(item.id);
        notifications.show({
          title: 'Marked as watched',
          message: `${item.title} marked as watched.`,
          color: 'green',
        });
      }
    } catch (error) {
      console.error('Failed to mark watched', error);
      notifications.show({
        title: 'Action failed',
        message: 'Unable to mark item as watched at this time.',
        color: 'red',
      });
    }
  };

  const handleMarkUnwatched = async (item) => {
    try {
      if (item.item_type === 'show') {
        const response = await API.markSeriesUnwatched(item.id);
        if (response?.item) {
          upsertItems([response.item]);
        } else {
          await refreshItem(item.id);
        }
        notifications.show({
          title: 'Series updated',
          message: 'Watch history cleared.',
          color: 'blue',
        });
      } else {
        await API.clearMediaItemProgress(item.id);
        await refreshItem(item.id);
        notifications.show({
          title: 'Progress cleared',
          message: `${item.title} marked as unwatched.`,
          color: 'blue',
        });
      }
    } catch (error) {
      console.error('Failed to mark unwatched', error);
      notifications.show({
        title: 'Action failed',
        message: 'Unable to update watch state right now.',
        color: 'red',
      });
    }
  };

  const handleDeleteItem = async (item) => {
    const label = item.item_type === 'show' ? 'series and all episodes' : 'media item';
    if (!window.confirm(`Delete ${item.title}? This will remove the ${label} from your library.`)) {
      return;
    }
    try {
      await API.deleteMediaItem(item.id);
      removeItems(item.id);
      notifications.show({
        title: 'Deleted',
        message: `${item.title} removed from your library.`,
        color: 'red',
      });
    } catch (error) {
      console.error('Failed to delete media item', error);
      notifications.show({
        title: 'Delete failed',
        message: 'Unable to delete this item right now.',
        color: 'red',
      });
    }
  };

  const handleContextMenu = (event, item) => {
    event.preventDefault();
    setContextMenu({
      x: event.clientX,
      y: event.clientY,
      item,
    });
  };

  useEffect(() => {
    if (!contextMenu) return;
    const handleOutsideClick = () => setContextMenu(null);
    document.addEventListener('click', handleOutsideClick);
    return () => document.removeEventListener('click', handleOutsideClick);
  }, [contextMenu]);

  // --- SCAN CONTROLS ---

  // Open the drawer only (do NOT start a scan)
  const handleOpenScanDrawer = () => {
    if (!hasAnyLibraries) {
      notifications.show({
        title: 'No libraries configured',
        message: 'Add a library to manage scans.',
        color: 'yellow',
      });
      return;
    }
    setScanDrawerOpen(true);
  };

  // Explicitly start a scan (quick or full)
  const handleStartScan = async (full = false, targetLibraryId = null, options = {}) => {
    if (!hasAnyLibraries) {
      notifications.show({
        title: 'Scan unavailable',
        message: 'Add a library before starting a scan.',
        color: 'yellow',
      });
      return null;
    }
    const resolvedLibraryId = targetLibraryId || primaryLibraryId;
    if (!resolvedLibraryId) {
      setScanDrawerOpen(true);
      if (!options?.suppressNotification) {
        notifications.show({
          title: 'Choose scan scope',
          message: 'Use the scan drawer to choose a library or scan all libraries.',
          color: 'blue',
        });
      }
      return null;
    }
    try {
      const scan = await triggerScan(resolvedLibraryId, { full });
      if (!scan) {
        return null;
      }
      if (!options?.suppressNotification) {
        const libraryName =
          libraries.find((library) => library.id === resolvedLibraryId)?.name || 'selected library';
        notifications.show({
          title: full ? 'Full scan started' : 'Scan started',
          message: full
            ? `A full scan for ${libraryName} has been queued.`
            : `A quick scan for ${libraryName} has been queued.`,
          color: 'blue',
        });
      }
      setScanDrawerOpen(true);
      return scan;
    } catch (error) {
      console.error('Failed to start scan', error);
      if (!options?.suppressNotification) {
        notifications.show({
          title: 'Scan failed',
          message: 'Unable to start scan at this time.',
          color: 'red',
        });
      }
      return null;
    }
  };

  // Cancel a running scan by job id
  const handleCancelScanJob = async (jobId) => {
    try {
      const updated = await API.cancelLibraryScan(jobId);
      if (updated) {
        upsertScan(updated);
      }
      notifications.show({
        title: 'Scan canceled',
        message: 'The running scan has been stopped.',
        color: 'yellow',
      });
    } catch (e) {
      console.error(e);
      notifications.show({
        title: 'Cancel failed',
        message: 'Could not cancel this scan.',
        color: 'red',
      });
    }
  };

  // Remove a queued scan by job id
  const handleDeleteQueuedScan = async (jobId) => {
    try {
      await API.deleteLibraryScan(jobId);
      removeScan(jobId);
      notifications.show({
        title: 'Removed from queue',
        message: 'The queued scan was removed.',
        color: 'green',
      });
    } catch (e) {
      console.error(e);
      notifications.show({
        title: 'Remove failed',
        message: 'Could not remove this queued scan.',
        color: 'red',
      });
    }
  };

  const recommendedView = (
    <Stack spacing="xl">
      <MediaCarousel
        title="Continue Watching"
        items={continueWatching}
        onSelect={handleOpenItem}
        onContextMenu={handleContextMenu}
        emptyMessage="Start watching to see items here."
      />
      <MediaCarousel
        title="Recently Released"
        items={recentlyReleased}
        onSelect={handleOpenItem}
        onContextMenu={handleContextMenu}
      />
      <MediaCarousel
        title="Recently Added"
        items={recentlyAdded}
        onSelect={handleOpenItem}
        onContextMenu={handleContextMenu}
      />
    </Stack>
  );

  const libraryView = (() => {
    return (
      <Box style={{ position: 'relative' }}>
        <Stack spacing="lg">
          <Group justify="space-between" align="center">
            <Group align="flex-end" gap="sm">
              <Select
                label="Sort by"
                data={SORT_OPTIONS}
                value={sortOption}
                onChange={(value) => setSortOption(value || 'alpha')}
                w={220}
              />
              {itemsBackgroundLoading && <Loader size="xs" />}
            </Group>
            <Button
              variant="subtle"
              leftSection={<RefreshCcw size={16} />}
              onClick={() =>
                fetchItems(relevantLibraryIds, {
                  append: false,
                  all: true,
                  ordering: libraryOrdering,
                })}
            >
              Refresh
            </Button>
          </Group>
          {sortOption === 'genre' ? (
            <Stack spacing="xl">
              {genreCarousels.map(({ genre, items: genreItems }) => (
                <MediaCarousel
                  key={genre}
                  title={genre}
                  items={genreItems}
                  onSelect={handleOpenItem}
                  onContextMenu={handleContextMenu}
                />
              ))}
            </Stack>
          ) : (
            <Box style={{ position: 'relative' }}>
              {sortOption === 'alpha' && availableLetters.size > 0 && (
                <AlphabetSidebar available={availableLetters} onSelect={handleLetterSelect} />
              )}
              <MediaGrid
                items={sortedLibraryItems}
                loading={itemsLoading}
                onSelect={handleOpenItem}
                onContextMenu={handleContextMenu}
                groupByLetter={sortOption === 'alpha'}
                letterRefs={letterRefs}
                cardSize="md"
              />
              <Group justify="space-between" mt="md">
                <Text size="sm" c="dimmed">
                  Loaded {sortedLibraryItems.length}
                  {itemsTotalCount > 0 ? ` of ${itemsTotalCount}` : ''} items
                </Text>
              </Group>
            </Box>
          )}
        </Stack>
      </Box>
    );
  })();

  const categoriesView = (
    <Stack spacing="xl">
      {genreCarousels.length === 0 ? (
        <Text c="dimmed">No categories available.</Text>
      ) : (
        genreCarousels.map(({ genre, items: genreItems }) => (
          <MediaCarousel
            key={genre}
            title={genre}
            items={genreItems}
            onSelect={handleOpenItem}
            onContextMenu={handleContextMenu}
          />
        ))
      )}
    </Stack>
  );

  const contextItem = contextMenu?.item;
  const contextStatus = contextItem?.watch_summary?.status;

  return (
    <Box p="lg">
      <Stack spacing="xl">
        <Group justify="space-between" align="flex-start" wrap="wrap">
          <Stack spacing={4}>
            <Title order={2}>{isMovies ? 'Movies' : 'TV Shows'}</Title>
            {aggregatedSubtitle && (
              <Text c="dimmed" size="sm">
                {aggregatedSubtitle}
              </Text>
            )}
          </Stack>
          <Group align="center" gap="sm">
            <ActionIcon
              variant="light"
              color="blue"
              onClick={handleOpenScanDrawer}
              title="View recent scans"
            >
              <ListChecks size={18} />
            </ActionIcon>
            <ActionIcon
              variant="filled"
              color="blue"
              onClick={handleOpenScanDrawer}
              title="Open scan drawer"
            >
              <RefreshCcw size={18} />
            </ActionIcon>
          </Group>
        </Group>

        <Group justify="space-between" align="center" wrap="wrap">
          <Group align="center" gap="sm">
            <SegmentedControl
              value={normalizedMediaType || 'movies'}
              onChange={handleMediaTypeChange}
              data={[
                { label: 'Movies', value: 'movies' },
                { label: 'TV Shows', value: 'shows' },
              ]}
            />
            <SegmentedControl
              value={activeTab}
              onChange={setActiveTab}
              data={TABS}
            />
          </Group>
          <Group align="center" gap="sm">
            <TextInput
              leftSection={<Search size={16} />}
              placeholder="Search library"
              value={searchTerm}
              onChange={(event) => setSearchTerm(event.currentTarget.value)}
              w={260}
            />
          </Group>
        </Group>

        {relevantLibraryIds.length > 0 ? (
          <div>
            {activeTab === 'recommended' && recommendedView}
            {activeTab === 'library' && libraryView}
            {activeTab === 'categories' && categoriesView}
          </div>
        ) : (
          <Stack align="center" py="xl" spacing="md">
            <Text c="dimmed">Add a media library to begin importing content.</Text>
          </Stack>
        )}
      </Stack>

      <LibraryScanDrawer
        opened={scanDrawerOpen && hasAnyLibraries}
        onClose={() => setScanDrawerOpen(false)}
        libraryId={primaryLibraryId || relevantLibraryIds[0] || allLibraryIds[0] || null}
        libraryIds={allLibraryIds}
        onCancelJob={handleCancelScanJob}
        onDeleteQueuedJob={handleDeleteQueuedScan}
        onStartScan={(targetLibraryId, options) =>
          handleStartScan(false, targetLibraryId, options)
        }
        onStartFullScan={(targetLibraryId, options) =>
          handleStartScan(true, targetLibraryId, options)
        }
      />

      <MediaDetailModal
        opened={playbackModalOpen}
        onClose={() => {
          setPlaybackModalOpen(false);
          closeItem();
        }}
      />

      {contextMenu && contextItem && contextMenuPosition && (
        <Portal>
          <Paper
            shadow="md"
            p="xs"
            withBorder
            style={{
              position: 'fixed',
              top: contextMenuPosition.top,
              left: contextMenuPosition.left,
              zIndex: 1000,
              minWidth: 220,
              background: 'rgba(18, 21, 35, 0.97)',
            }}
          >
            <Stack spacing={4}>
              <Button
                variant="subtle"
                leftSection={<Play size={16} />}
                onClick={() => {
                  handleOpenItem(contextItem);
                  setContextMenu(null);
                }}
              >
                {contextStatus === 'in_progress' ? 'Continue Watching' : 'Play'}
              </Button>
                <Button
                  variant="subtle"
                  leftSection={<RefreshCcw size={16} />}
                  onClick={async () => {
                    await API.refreshMediaItemMetadata(contextItem.id);
                    pollItem(contextItem.id);
                    notifications.show({
                      title: 'Metadata queued',
                      message: 'Metadata refresh has been requested.',
                      color: 'blue',
                    });
                    setContextMenu(null);
                  }}
                >
                Refresh Metadata
              </Button>
              <Divider my="xs" />
              {contextStatus === 'watched' ? (
                <Button
                  variant="subtle"
                  onClick={async () => {
                    await handleMarkUnwatched(contextItem);
                    setContextMenu(null);
                  }}
                >
                  Mark unwatched
                </Button>
              ) : (
                <>
                  <Button
                    variant="subtle"
                    onClick={async () => {
                      await handleMarkWatched(contextItem);
                      setContextMenu(null);
                    }}
                  >
                    Mark watched
                  </Button>
                  {contextStatus === 'in_progress' && (
                    <Button
                      variant="subtle"
                      leftSection={<XCircle size={16} />}
                      onClick={async () => {
                        await handleMarkUnwatched(contextItem);
                        setContextMenu(null);
                      }}
                    >
                      Clear Watch Progress
                    </Button>
                  )}
                </>
              )}
              <Button
                variant="subtle"
                color="red"
                leftSection={<Trash2 size={16} />}
                onClick={async () => {
                  await handleDeleteItem(contextItem);
                  setContextMenu(null);
                }}
              >
                Delete
              </Button>
            </Stack>
          </Paper>
        </Portal>
      )}
    </Box>
  );
};

export default LibraryPage;
