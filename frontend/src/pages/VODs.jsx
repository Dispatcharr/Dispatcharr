import React, { Suspense, useEffect, useMemo, useState } from 'react';
import { Navigate } from 'react-router-dom';
import {
  Box,
  Button,
  SegmentedControl,
  Select,
  Stack,
  Text,
  TextInput,
  Title,
} from '@mantine/core';
import { Search } from 'lucide-react';
import { useDisclosure } from '@mantine/hooks';
import useAuthStore from '../store/auth';
import useVODStore from '../store/useVODStore';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
import ListPagination from '../components/ListPagination.jsx';
import {
  hideNotification,
  showNotification,
} from '../utils/notificationUtils.js';
import classes from '../components/VODLayout.module.css';
import {
  filterCategoriesToEnabled,
  getCategoryOptions,
} from '../utils/pages/VODsUtils.js';
import {
  canViewVod,
  isVodMoviesEnabled,
  isVodSeriesEnabled,
} from '../utils/vodAccess';
const SeriesModal = React.lazy(() => import('../components/SeriesModal'));
const VODModal = React.lazy(() => import('../components/VODModal'));
const VODCard = React.lazy(() => import('../components/cards/VODCard'));
const SeriesCard = React.lazy(() => import('../components/cards/SeriesCard'));

const PAGE_SIZES = [12, 24, 48, 96];
const LOAD_ERROR_ID = 'vod-library-load-error';
const CATEGORIES_ERROR_ID = 'vod-library-categories-error';

const VODsPage = () => {
  const authUser = useAuthStore((s) => s.user);
  const moviesEnabled = isVodMoviesEnabled(authUser);
  const seriesEnabled = isVodSeriesEnabled(authUser);
  const vodAllowed = canViewVod(authUser);

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
  const categoriesError = useVODStore((s) => s.categoriesError);
  const categoriesLoading = useVODStore((s) => s.categoriesLoading);

  // Hydrate page size from localStorage before the first content fetch so a
  // stored size that differs from the store default does not cause a refetch.
  const [pageSizeReady, setPageSizeReady] = useState(false);
  useEffect(() => {
    const stored = localStorage.getItem('vodsPageSize');
    if (PAGE_SIZES.includes(Number(stored)) && Number(stored) !== pageSize) {
      setPageSize(Number(stored));
    }
    setPageSizeReady(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- mount-only hydrate
  }, []);

  const handlePageSizeChange = (value) => {
    setPageSize(value);
    localStorage.setItem('vodsPageSize', String(value));
  };

  const [selectedSeries, setSelectedSeries] = useState(null);
  const [selectedVOD, setSelectedVOD] = useState(null);
  const [
    seriesModalOpened,
    { open: openSeriesModal, close: closeSeriesModal },
  ] = useDisclosure(false);
  const [vodModalOpened, { open: openVODModal, close: closeVODModal }] =
    useDisclosure(false);
  const [initialLoad, setInitialLoad] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [contentError, setContentError] = useState(null);
  const [reload, setReload] = useState(0);
  const [categories, setCategories] = useState({});

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
    if (!vodAllowed || !categoriesError) {
      hideNotification(CATEGORIES_ERROR_ID);
      return;
    }
    showNotification({
      id: CATEGORIES_ERROR_ID,
      title: 'Library categories could not be loaded',
      message:
        'Titles remain available. Retry categories to update the category filter.',
      color: 'red',
      autoClose: false,
    });
  }, [vodAllowed, categoriesError]);

  useEffect(() => {
    if (!vodAllowed || !pageSizeReady) return;
    if (requiredType && filters.type !== requiredType) return;
    let cancelled = false;
    setFetching(true);
    fetchContent().finally(() => {
      if (cancelled) return;
      const error = useVODStore.getState().error;
      setContentError(error);
      setInitialLoad(false);
      setFetching(false);
      if (error) {
        showNotification({
          id: LOAD_ERROR_ID,
          title: 'Library could not be loaded',
          message: error,
          color: 'red',
          autoClose: false,
        });
      } else {
        hideNotification(LOAD_ERROR_ID);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [
    vodAllowed,
    pageSizeReady,
    requiredType,
    filters,
    currentPage,
    pageSize,
    fetchContent,
    reload,
  ]);

  useEffect(
    () => () => {
      hideNotification(LOAD_ERROR_ID);
      hideNotification(CATEGORIES_ERROR_ID);
    },
    []
  );

  if (!vodAllowed) {
    return <Navigate to="/channels" replace />;
  }

  const handleVODCardClick = (vod) => {
    setSelectedVOD(vod);
    openVODModal();
  };

  const handleSeriesClick = (series) => {
    setSelectedSeries(series);
    openSeriesModal();
  };

  const onCategoryChange = (value) => {
    setFilters({ category: value });
    setPage(1);
  };

  // When type changes, reset category to all
  const handleTypeChange = (value) => {
    setFilters({ type: value, category: '' });
    setPage(1);
  };

  const categoryOptions = getCategoryOptions(categories, filters);

  const showTypeControl = typeOptions.length > 1;

  return (
    <Box p="md" id="vods-container" className={classes.library}>
      <Stack gap="md">
        <Title order={2}>Library</Title>
        <div className={classes.toolbar}>
          {showTypeControl && (
            <SegmentedControl
              value={filters.type}
              onChange={handleTypeChange}
              data={typeOptions}
              aria-label="Content type"
            />
          )}

          <TextInput
            placeholder="Search VODs..."
            aria-label="Search library"
            leftSection={<Search size={16} />}
            value={filters.search}
            onChange={(e) => setFilters({ search: e.target.value })}
            className={classes.search}
          />

          <Select
            placeholder="Category"
            aria-label="Category"
            data={categoryOptions}
            value={filters.category}
            onChange={onCategoryChange}
            clearable
            className={classes.category}
            searchable
            error={!!categoriesError}
            disabled={categoriesLoading}
            aria-busy={categoriesLoading}
          />
          {categoriesError && (
            <Button
              variant="default"
              onClick={() => fetchCategories()}
              disabled={categoriesLoading}
            >
              {categoriesLoading ? 'Retrying categories…' : 'Retry categories'}
            </Button>
          )}
        </div>

        {/* Content */}
        {initialLoad ? (
          <Text role="status" c="dimmed" ta="center" py="xl">
            Loading library…
          </Text>
        ) : contentError ? (
          <Stack align="center" py="xl" gap="sm">
            <Text c="red">Library could not be loaded.</Text>
            <Button
              variant="default"
              onClick={() => setReload((value) => value + 1)}
              disabled={fetching}
            >
              Retry
            </Button>
          </Stack>
        ) : (
          <>
            <Box aria-busy={fetching}>
              {fetching && (
                <Text size="sm" c="dimmed" role="status" mb="sm">
                  Updating library…
                </Text>
              )}
              {currentPageContent.length ? (
                <div className={classes.grid}>
                  <ErrorBoundary inline>
                    <Suspense
                      fallback={
                        <Text c="dimmed" role="status">
                          Loading titles…
                        </Text>
                      }
                    >
                      {currentPageContent.map((item) => (
                        <React.Fragment key={`${item.contentType}_${item.id}`}>
                          {item.contentType === 'series' ? (
                            <SeriesCard
                              series={item}
                              onClick={handleSeriesClick}
                            />
                          ) : (
                            <VODCard vod={item} onClick={handleVODCardClick} />
                          )}
                        </React.Fragment>
                      ))}
                    </Suspense>
                  </ErrorBoundary>
                </div>
              ) : (
                !fetching && (
                  <Stack align="center" gap="xs" py="xl">
                    <Text fw={600}>No titles found.</Text>
                    <Text size="sm" c="dimmed">
                      {filters.search || filters.category
                        ? 'Try a different search or category.'
                        : 'No movies or series have been imported yet.'}
                    </Text>
                  </Stack>
                )
              )}
            </Box>
            <ListPagination
              page={currentPage}
              pageSize={pageSize}
              total={totalCount}
              onPageChange={setPage}
              onPageSizeChange={handlePageSizeChange}
              pageSizeOptions={PAGE_SIZES}
              itemLabel="Items"
              disabled={fetching}
            />
          </>
        )}
      </Stack>

      {/* Series Episodes Modal */}
      <ErrorBoundary inline>
        <Suspense fallback={null}>
          <SeriesModal
            series={selectedSeries}
            opened={seriesModalOpened}
            onClose={closeSeriesModal}
          />
        </Suspense>
      </ErrorBoundary>

      {/* VOD Details Modal */}
      <ErrorBoundary inline>
        <Suspense fallback={null}>
          <VODModal
            vod={selectedVOD}
            opened={vodModalOpened}
            onClose={closeVODModal}
          />
        </Suspense>
      </ErrorBoundary>
    </Box>
  );
};

export default VODsPage;
