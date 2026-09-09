import React, { Suspense, useEffect, useMemo, useState } from 'react';
import { Navigate } from 'react-router-dom';
import {
  Box,
  Flex,
  Grid,
  GridCol,
  Group,
  Loader,
  LoadingOverlay,
  Pagination,
  SegmentedControl,
  Select,
  Stack,
  TextInput,
  Title,
} from '@mantine/core';
import { Search } from 'lucide-react';
import { useDisclosure } from '@mantine/hooks';
import useAuthStore from '../store/auth';
import useVODStore from '../store/useVODStore';
import ErrorBoundary from '../components/ErrorBoundary.jsx';
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

const MIN_CARD_WIDTH = 260;
const MAX_CARD_WIDTH = 320;

const useCardColumns = () => {
  const [columns, setColumns] = useState(4);

  useEffect(() => {
    const calcColumns = () => {
      const container = document.getElementById('vods-container');
      const width = container ? container.offsetWidth : window.innerWidth;
      let colCount = Math.floor(width / MIN_CARD_WIDTH);
      if (colCount < 1) colCount = 1;
      if (colCount > 6) colCount = 6;
      setColumns(colCount);
    };
    calcColumns();
    window.addEventListener('resize', calcColumns);
    return () => window.removeEventListener('resize', calcColumns);
  }, []);

  return columns;
};

const VODsPage = () => {
  const authUser = useAuthStore((s) => s.user);
  const moviesEnabled = isVodMoviesEnabled(authUser);
  const seriesEnabled = isVodSeriesEnabled(authUser);
  const vodAllowed = canViewVod(authUser);

  const currentPageContent = useVODStore((s) => s.currentPageContent); // Direct subscription
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

  const handlePageSizeChange = (value) => {
    setPageSize(Number(value));
    localStorage.setItem('vodsPageSize', value);
  };

  // const showVideo = useVideoStore((s) => s.showVideo); - removed as unused
  const [selectedSeries, setSelectedSeries] = useState(null);
  const [selectedVOD, setSelectedVOD] = useState(null);
  const [
    seriesModalOpened,
    { open: openSeriesModal, close: closeSeriesModal },
  ] = useDisclosure(false);
  const [vodModalOpened, { open: openVODModal, close: closeVODModal }] =
    useDisclosure(false);
  const [initialLoad, setInitialLoad] = useState(true);
  const columns = useCardColumns();
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

  // Helper function to get display data based on current filters
  const getDisplayData = () => {
    return (currentPageContent || []).map((item) => ({
      ...item,
      _vodType: item.contentType === 'movie' ? 'movie' : 'series',
    }));
  };

  useEffect(() => {
    setCategories(filterCategoriesToEnabled(allCategories));
  }, [allCategories]);

  useEffect(() => {
    if (!vodAllowed) return;
    fetchCategories();
  }, [vodAllowed, fetchCategories]);

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

  const totalPages = Math.ceil(totalCount / pageSize);
  const showTypeControl = typeOptions.length > 1;

  return (
    <Box p="md" id="vods-container">
      <Stack spacing="md">
        <Group position="apart">
          <Title order={2}>Video on Demand</Title>
        </Group>

        {/* Filters */}
        <Group spacing="md" align="end">
          {showTypeControl && (
            <SegmentedControl
              value={filters.type}
              onChange={handleTypeChange}
              data={typeOptions}
            />
          )}

          <TextInput
            placeholder="Search VODs..."
            icon={<Search size={16} />}
            value={filters.search}
            onChange={(e) => setFilters({ search: e.target.value })}
            miw={200}
          />

          <Select
            placeholder="Category"
            data={categoryOptions}
            value={filters.category}
            onChange={onCategoryChange}
            clearable
            miw={150}
          />

          <Select
            label="Page Size"
            value={String(pageSize)}
            onChange={handlePageSizeChange}
            data={['12', '24', '48', '96'].map((v) => ({
              value: v,
              label: v,
            }))}
            w={110}
          />
        </Group>

        {/* Content */}
        {initialLoad ? (
          <Flex justify="center" py="xl">
            <Loader size="lg" />
          </Flex>
        ) : (
          <>
            <Grid gutter="md">
              <ErrorBoundary inline>
                <Suspense fallback={<Loader />}>
                  {getDisplayData().map((item) => (
                    <GridCol
                      span={12 / columns}
                      key={`${item.contentType}_${item.id}`}
                      miw={MIN_CARD_WIDTH}
                      maw={MAX_CARD_WIDTH}
                      m={'0 auto'}
                    >
                      {item.contentType === 'series' ? (
                        <SeriesCard series={item} onClick={handleSeriesClick} />
                      ) : (
                        <VODCard vod={item} onClick={handleVODCardClick} />
                      )}
                    </GridCol>
                  ))}
                </Suspense>
              </ErrorBoundary>
            </Grid>

            {/* Pagination */}
            {totalPages > 1 && (
              <Flex justify="center" mt="md">
                <Pagination
                  page={currentPage}
                  onChange={setPage}
                  total={totalPages}
                />
              </Flex>
            )}
          </>
        )}
      </Stack>

      {/* Series Episodes Modal */}
      <ErrorBoundary inline>
        <Suspense fallback={<LoadingOverlay />}>
          <SeriesModal
            series={selectedSeries}
            opened={seriesModalOpened}
            onClose={closeSeriesModal}
          />
        </Suspense>
      </ErrorBoundary>

      {/* VOD Details Modal */}
      <ErrorBoundary inline>
        <Suspense fallback={<LoadingOverlay />}>
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
